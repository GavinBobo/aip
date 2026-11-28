# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reads and writes for the knowledge-ontology tier.

The knowledge tier deliberately mirrors the data tier's shape: every list is a
plain ``list[dict]`` read from Core statements, and mutations happen in one
transaction so a failed extraction cannot leave half a graph behind.

The important boundary is *evidence*. A concept, relation or fact is a claim;
the evidence rows are why the claim is allowed to exist. Re-extracting one
document replaces that document's claims and citations while leaving claims
from other documents alone, which is why the delete clauses are scoped by
``source_document_id`` rather than by network.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import aliased

from all_ontology.dal import schema as s
from all_ontology.dal.schema import (
    ZONE_PERMISSION_MANAGE,
    ZONE_PERMISSION_RANK,
    ZONE_PERMISSION_READ,
)
from all_ontology.dal import access as access_dal
from all_ontology.dal.session import store, write_transaction
from all_ontology.dal.users import resolve_accessible_catalog_ids

_NETWORK_FIELDS = {
    "name",
    "description",
    "domain",
    "zone_id",
    "status",
    "version",
    "modified_by",
}
_CONCEPT_FIELDS = {
    "name",
    "description",
    "kind",
    "aliases",
    "attributes",
    "status",
    "confidence",
}
_RELATION_FIELDS = {"name", "description", "kind", "status", "confidence"}
_FACT_FIELDS = {
    "predicate",
    "statement",
    "object_text",
    "status",
    "confidence",
}
_ACTION_FIELDS = {
    "name",
    "description",
    "action_intent",
    "bound_concept_id",
    "parameters",
    "status",
    "confidence",
}
_RISK_FIELDS = {
    "name",
    "description",
    "severity",
    "mitigation",
    "related_concept_id",
    "status",
    "confidence",
}
_METRIC_FIELDS = {
    "name",
    "description",
    "expression",
    "unit",
    "concept_id",
    "sql_attribute_id",
    "status",
    "confidence",
}
_GROUP_FIELDS = {"name", "description"}
_CAPABILITY_FIELDS = {"name", "kind", "description", "config", "enabled"}


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _count_map(table: Any, network_ids: list[str]) -> dict[str, int]:
    if not network_ids:
        return {}
    rows = store().query_read(
        select(table.c.network_id, func.count().label("n"))
        .where(table.c.network_id.in_(network_ids))
        .group_by(table.c.network_id)
    )
    return {str(row["network_id"]): int(row["n"]) for row in rows}


def _network_counts(network_ids: list[str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        network_id: {
            "concept_count": 0,
            "relation_count": 0,
            "fact_count": 0,
            "action_count": 0,
            "risk_count": 0,
            "metric_count": 0,
            "group_count": 0,
            "capability_count": 0,
            "eval_case_count": 0,
            "document_count": 0,
            "data_link_count": 0,
        }
        for network_id in network_ids
    }
    for key, table in (
        ("concept_count", s.knowledge_concept),
        ("relation_count", s.knowledge_relation),
        ("fact_count", s.knowledge_fact),
        ("action_count", s.knowledge_action),
        ("risk_count", s.knowledge_risk),
        ("metric_count", s.knowledge_metric),
        ("group_count", s.knowledge_concept_group),
        ("capability_count", s.knowledge_capability),
        ("eval_case_count", s.knowledge_eval_case),
        ("document_count", s.knowledge_document),
    ):
        for network_id, value in _count_map(table, network_ids).items():
            counts.setdefault(network_id, {})[key] = value
    if network_ids:
        rows = store().query_read(
            select(
                s.knowledge_concept.c.network_id,
                func.count().label("n"),
            )
            .select_from(
                s.knowledge_concept__data.join(
                    s.knowledge_concept,
                    s.knowledge_concept__data.c.concept_id == s.knowledge_concept.c.id,
                )
            )
            .where(s.knowledge_concept.c.network_id.in_(network_ids))
            .group_by(s.knowledge_concept.c.network_id)
        )
        for row in rows:
            counts.setdefault(str(row["network_id"]), {})["data_link_count"] = int(
                row["n"]
            )
    return counts


def _grant_map(network_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not network_ids:
        return {}
    rows = store().query_read(
        select(
            s.knowledge_network_grant.c.network_id,
            s.knowledge_network_grant.c.user_id,
            s.knowledge_network_grant.c.dept_id,
            s.knowledge_network_grant.c.permission,
            s.knowledge_network_grant.c.expires_at,
        ).where(s.knowledge_network_grant.c.network_id.in_(network_ids))
    )
    result: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"users": {}, "depts": {}, "restricted": False}
    )
    for row in rows:
        # An expired grant still marks the network as explicitly shared, so the
        # zone fallback must not silently re-open it once the last grant lapses.
        bucket = result[str(row["network_id"])]
        bucket["restricted"] = True
        expires_at = row["expires_at"]
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                continue
        permission = str(row["permission"])
        if row["user_id"]:
            bucket["users"][str(row["user_id"])] = permission
        if row["dept_id"]:
            bucket["depts"][str(row["dept_id"])] = permission
    return result


def _network_visible(
    row: dict[str, Any],
    *,
    zone_ids: list[str] | None,
    user_id: str | None,
    dept_ids: tuple[str, ...] | list[str],
    grants: dict[str, Any],
) -> bool:
    if zone_ids is None:
        return True
    grant = grants.get(str(row["id"])) or {
        "users": {},
        "depts": {},
        "restricted": False,
    }
    if grant.get("restricted") or grant["users"] or grant["depts"]:
        return (user_id is not None and user_id in grant["users"]) or bool(
            set(dept_ids) & set(grant["depts"])
        )
    return row.get("zone_id") is None or row["zone_id"] in zone_ids


def network_permission(
    row: dict[str, Any],
    *,
    zone_permissions: dict[str, str] | None,
    user_id: str | None,
    dept_ids: tuple[str, ...] | list[str],
    grants: dict[str, Any] | None = None,
) -> str | None:
    """Strongest permission the caller holds on one knowledge network."""
    if zone_permissions is None:
        return str(ZONE_PERMISSION_MANAGE)
    grant = (grants or {}).get(str(row["id"])) or {
        "users": {},
        "depts": {},
        "restricted": False,
    }
    candidates = []
    has_explicit = bool(grant.get("restricted") or grant["users"] or grant["depts"])
    if user_id is not None and user_id in grant["users"]:
        candidates.append(str(grant["users"][user_id]))
    candidates.extend(
        str(grant["depts"][dept_id])
        for dept_id in dept_ids
        if dept_id in grant["depts"]
    )
    if not has_explicit:
        zone_id = row.get("zone_id")
        if zone_id is not None:
            zone_level = zone_permissions.get(str(zone_id))
            if zone_level:
                candidates.append(zone_level)
        if not candidates and zone_id is None:
            candidates.append(str(ZONE_PERMISSION_READ))
    if not candidates:
        return None
    return max(candidates, key=lambda permission: ZONE_PERMISSION_RANK[permission])


def list_networks(
    zone_ids: list[str] | None = None,
    *,
    user_id: str | None = None,
    dept_ids: tuple[str, ...] | list[str] = (),
    zone_permissions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_network).order_by(
            s.knowledge_network.c.created.desc(),
            s.knowledge_network.c.name,
        )
    )
    if zone_ids is not None:
        grants = _grant_map([str(row["id"]) for row in rows])
        rows = [
            row
            for row in rows
            if _network_visible(
                row,
                zone_ids=zone_ids,
                user_id=user_id,
                dept_ids=dept_ids,
                grants=grants,
            )
        ]
    ids = [str(row["id"]) for row in rows]
    counts = _network_counts(ids)
    grants = _grant_map(ids)
    return [
        {
            **row,
            **counts.get(str(row["id"]), {}),
            "permission": network_permission(
                row,
                zone_permissions=zone_permissions,
                user_id=user_id,
                dept_ids=dept_ids,
                grants=grants,
            ),
        }
        for row in rows
    ]


def visible_network_ids(
    zone_ids: list[str] | None,
    *,
    user_id: str | None,
    dept_ids: tuple[str, ...] | list[str],
    zone_permissions: dict[str, str] | None = None,
) -> list[str]:
    """Ids of knowledge networks the caller may read in this request."""
    rows = store().query_read(select(s.knowledge_network))
    grants = _grant_map([str(row["id"]) for row in rows])
    return [
        str(row["id"])
        for row in rows
        if _network_visible(
            row,
            zone_ids=zone_ids,
            user_id=user_id,
            dept_ids=dept_ids,
            grants=grants,
        )
        and network_permission(
            row,
            zone_permissions=zone_permissions,
            user_id=user_id,
            dept_ids=dept_ids,
            grants=grants,
        )
        is not None
    ]


def get_network(
    network_id: str,
    zone_ids: list[str] | None = None,
    *,
    user_id: str | None = None,
    dept_ids: tuple[str, ...] | list[str] = (),
    zone_permissions: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    row = next(
        iter(
            store().query_read(
                select(s.knowledge_network).where(
                    s.knowledge_network.c.id == network_id
                )
            )
        ),
        None,
    )
    if row is None:
        return None
    grants = _grant_map([network_id])
    if not _network_visible(
        row,
        zone_ids=zone_ids,
        user_id=user_id,
        dept_ids=dept_ids,
        grants=grants,
    ):
        return None
    permission = network_permission(
        row,
        zone_permissions=zone_permissions,
        user_id=user_id,
        dept_ids=dept_ids,
        grants=grants,
    )
    return {
        **row,
        **_network_counts([network_id]).get(network_id, {}),
        "permission": permission,
    }


_NETWORK_ENTITY_TABLES = {
    "document": s.knowledge_document,
    "concept": s.knowledge_concept,
    "relation": s.knowledge_relation,
    "fact": s.knowledge_fact,
    "action": s.knowledge_action,
    "risk": s.knowledge_risk,
    "metric": s.knowledge_metric,
    "concept_group": s.knowledge_concept_group,
    "capability": s.knowledge_capability,
    "eval_case": s.knowledge_eval_case,
}


def entity_network_id(kind: str, entity_id: str) -> str | None:
    """The network owning one knowledge entity, or ``None`` when absent."""
    table = _NETWORK_ENTITY_TABLES.get(kind)
    if table is None:
        return None
    rows = store().query_read(
        select(table.c.network_id).where(table.c.id == entity_id).limit(1)
    )
    return str(rows[0]["network_id"]) if rows else None


def data_link_network_id(link_id: str) -> str | None:
    rows = store().query_read(
        select(s.knowledge_concept.c.network_id)
        .select_from(
            s.knowledge_concept__data.join(
                s.knowledge_concept,
                s.knowledge_concept.c.id == s.knowledge_concept__data.c.concept_id,
            )
        )
        .where(s.knowledge_concept__data.c.id == link_id)
        .limit(1)
    )
    return str(rows[0]["network_id"]) if rows else None


def create_network(
    *,
    name: str,
    description: str | None,
    domain: str | None,
    zone_id: str | None = None,
    created_by: str | None,
) -> dict[str, Any]:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Knowledge network name is required.")
    existing = store().query_read(
        select(s.knowledge_network.c.id).where(
            func.lower(func.trim(s.knowledge_network.c.name)) == func.lower(trimmed)
        )
    )
    if existing:
        raise ValueError("A knowledge network with this name already exists.")
    row = store().query_write(
        s.knowledge_network.insert()
        .values(
            name=trimmed,
            description=(description or "").strip() or None,
            domain=(domain or "").strip() or None,
            zone_id=zone_id,
            created_by=created_by,
        )
        .returning(s.knowledge_network)
    )[0]
    if created_by:
        store().query_write(
            s.knowledge_network_grant.insert().values(
                network_id=str(row["id"]),
                user_id=created_by,
                dept_id=None,
                permission=str(ZONE_PERMISSION_MANAGE),
            )
        )
    return {**row, **_network_counts([str(row["id"])]).get(str(row["id"]), {})}


def update_network(
    network_id: str,
    *,
    patch: dict[str, Any],
    modified_by: str | None,
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _NETWORK_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Knowledge network name is required.")
        duplicate = store().query_read(
            select(s.knowledge_network.c.id).where(
                s.knowledge_network.c.id != network_id,
                func.lower(func.trim(s.knowledge_network.c.name)) == func.lower(name),
            )
        )
        if duplicate:
            raise ValueError("A knowledge network with this name already exists.")
        values["name"] = name
    for key in ("description", "domain"):
        if key in values:
            values[key] = (
                str(values[key]).strip() if values[key] is not None else None
            ) or None
    if modified_by is not None:
        values["modified_by"] = modified_by
    if not values:
        return get_network(network_id)
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_network)
                .where(s.knowledge_network.c.id == network_id)
                .values(**values)
                .returning(s.knowledge_network)
            )
        ),
        None,
    )
    return get_network(network_id) if row is not None else None


def delete_network(network_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_network)
        .where(s.knowledge_network.c.id == network_id)
        .returning(s.knowledge_network.c.id)
    )
    return bool(deleted)


def list_network_grants(network_id: str) -> dict[str, Any]:
    rows = store().query_read(
        select(
            s.knowledge_network_grant.c.id,
            s.knowledge_network_grant.c.user_id,
            s.knowledge_network_grant.c.dept_id,
            s.knowledge_network_grant.c.permission,
            s.knowledge_network_grant.c.expires_at,
            s.knowledge_network_grant.c.created,
            s.department.c.name.label("dept_name"),
        )
        .select_from(
            s.knowledge_network_grant.outerjoin(
                s.department,
                s.department.c.id == s.knowledge_network_grant.c.dept_id,
            )
        )
        .where(s.knowledge_network_grant.c.network_id == network_id)
    )
    return {
        "user_ids": [row["user_id"] for row in rows if row["user_id"]],
        "dept_ids": [row["dept_id"] for row in rows if row["dept_id"]],
        "grants": [dict(row) for row in rows],
    }


def replace_network_grants(
    network_id: str,
    *,
    grants: list[dict[str, Any]] | None = None,
    user_ids: list[str] | None = None,
    dept_ids: list[str] | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before = [
        {
            "subject_type": "user" if row["user_id"] else "department",
            "subject_id": row["user_id"] or row["dept_id"],
            "permission": row["permission"],
        }
        for row in list_network_grants(network_id).get("grants", [])
    ]
    normalized: dict[tuple[str, str], str] = {}
    expiry_by_key: dict[tuple[str, str], datetime | None] = {}
    raw_grants = list(grants or [])
    raw_grants.extend(
        {"subject_type": "user", "subject_id": subject_id, "permission": "read"}
        for subject_id in (user_ids or [])
    )
    raw_grants.extend(
        {
            "subject_type": "department",
            "subject_id": subject_id,
            "permission": "read",
        }
        for subject_id in (dept_ids or [])
    )
    for grant in raw_grants:
        subject_type = str(grant.get("subject_type") or "").strip()
        subject_id = str(grant.get("subject_id") or "").strip()
        permission = str(grant.get("permission") or "read").strip()
        if subject_type not in {"user", "department"} or not subject_id:
            raise ValueError("Each grant needs a user or department subject")
        if permission not in ZONE_PERMISSION_RANK:
            raise ValueError(f"Unknown permission {permission!r}")
        key = (subject_type, subject_id)
        raw_expiry = grant.get("expires_at")
        expires_at: datetime | None = None
        if raw_expiry:
            try:
                expires_at = datetime.fromisoformat(
                    str(raw_expiry).replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError("Invalid grant expiry") from exc
        expiry_by_key[key] = expires_at
        current = normalized.get(key)
        if (
            current is None
            or ZONE_PERMISSION_RANK[permission] > (ZONE_PERMISSION_RANK[current])
        ):
            normalized[key] = permission

    for (subject_type, subject_id), _permission in normalized.items():
        if subject_type != "user":
            continue
        user_id = subject_id
        if access_dal.account_access(user_id) is None:
            raise ValueError(f"Unknown user id: {user_id}")
    for (subject_type, dept_id), _permission in normalized.items():
        if subject_type != "department":
            continue
        if not store().query_read(
            select(s.department.c.id).where(s.department.c.id == dept_id)
        ):
            raise ValueError(f"Unknown department id: {dept_id}")
    with write_transaction():
        store().query_write(
            delete(s.knowledge_network_grant).where(
                s.knowledge_network_grant.c.network_id == network_id
            )
        )
        for (subject_type, subject_id), permission in normalized.items():
            store().query_write(
                s.knowledge_network_grant.insert().values(
                    network_id=network_id,
                    user_id=subject_id if subject_type == "user" else None,
                    dept_id=subject_id if subject_type == "department" else None,
                    permission=permission,
                    expires_at=expiry_by_key.get((subject_type, subject_id)),
                )
            )
        after = [
            {
                "subject_type": "user" if user_id else "department",
                "subject_id": user_id or dept_id,
                "permission": permission,
                "expires_at": (
                    expiry_by_key.get((subject_type, subject_id)).isoformat()
                    if expiry_by_key.get((subject_type, subject_id))
                    else None
                ),
            }
            for (subject_type, subject_id), permission in normalized.items()
            for user_id, dept_id in [
                (
                    subject_id if subject_type == "user" else None,
                    subject_id if subject_type == "department" else None,
                )
            ]
        ]
        store().query_write(
            s.knowledge_network_grant_audit.insert().values(
                network_id=network_id,
                actor_user_id=actor_user_id,
                action="replace",
                before=before,
                after=after,
            )
        )
    return list_network_grants(network_id)


def list_network_grant_audit(
    network_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_network_grant_audit)
        .where(s.knowledge_network_grant_audit.c.network_id == network_id)
        .order_by(s.knowledge_network_grant_audit.c.created.desc())
        .limit(limit)
    )
    return [dict(row) for row in rows]


def list_documents(network_id: str) -> list[dict[str, Any]]:
    alias_run = aliased(s.parsing_run)
    rows = store().query_read(
        select(
            s.knowledge_document,
            alias_run.c.status.label("run_status"),
        )
        .select_from(
            s.knowledge_document.outerjoin(
                alias_run, alias_run.c.id == s.knowledge_document.c.run_id
            )
        )
        .where(s.knowledge_document.c.network_id == network_id)
        .order_by(s.knowledge_document.c.created.desc())
    )
    return [dict(row) for row in rows]


def get_document(document_id: str) -> dict[str, Any] | None:
    return next(
        iter(
            store().query_read(
                select(s.knowledge_document).where(
                    s.knowledge_document.c.id == document_id
                )
            )
        ),
        None,
    )


def create_document(
    *,
    network_id: str,
    run_id: str | None,
    title: str,
    source_name: str | None,
    created_by: str | None,
) -> tuple[dict[str, Any], bool]:
    if run_id:
        existing = next(
            iter(
                store().query_read(
                    select(s.knowledge_document).where(
                        s.knowledge_document.c.network_id == network_id,
                        s.knowledge_document.c.run_id == run_id,
                    )
                )
            ),
            None,
        )
        if existing is not None:
            return existing, False
    source_md5 = source_path = parsed_md_path = None
    if run_id:
        parsed = next(
            iter(
                store().query_read(
                    select(
                        s.parsing_document.c.source_md5,
                        s.parsing_document.c.source_path,
                        s.parsing_document.c.parsed_md_path,
                    )
                    .select_from(
                        s.parsing_run.join(
                            s.parsing_document,
                            s.parsing_document.c.id == s.parsing_run.c.document_id,
                        )
                    )
                    .where(s.parsing_run.c.id == run_id)
                )
            ),
            None,
        )
        if parsed is not None:
            source_md5 = parsed["source_md5"]
            source_path = parsed["source_path"]
            parsed_md_path = parsed["parsed_md_path"]
    row = store().query_write(
        s.knowledge_document.insert()
        .values(
            network_id=network_id,
            run_id=run_id,
            title=title.strip() or "Untitled document",
            source_name=source_name,
            source_md5=source_md5,
            source_path=source_path,
            parsed_md_path=parsed_md_path,
            created_by=created_by,
        )
        .returning(s.knowledge_document)
    )[0]
    return row, True


def update_document(
    document_id: str,
    *,
    status: str | None = None,
    summary: str | None = None,
    error_message: str | None = None,
    chunk_count: int | None = None,
    extracted_at: datetime | None = None,
) -> dict[str, Any] | None:
    values: dict[str, Any] = {}
    if status is not None:
        values["status"] = status
    if summary is not None:
        values["summary"] = summary
    if error_message is not None:
        values["error_message"] = error_message
    if chunk_count is not None:
        values["chunk_count"] = chunk_count
    if extracted_at is not None:
        values["extracted_at"] = extracted_at
    if not values:
        return get_document(document_id)
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_document)
                .where(s.knowledge_document.c.id == document_id)
                .values(**values)
                .returning(s.knowledge_document)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_document(document_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_document)
        .where(s.knowledge_document.c.id == document_id)
        .returning(s.knowledge_document.c.id)
    )
    return bool(deleted)


def _links_for_concepts(concept_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not concept_ids:
        return {}
    rows = store().query_read(
        select(
            s.knowledge_concept__data,
            s.term.c.name.label("term_name"),
            s.catalog_table.c.name.label("table_name"),
            s.catalog_schema.c.name.label("schema_name"),
            s.catalog_database.c.name.label("database_name"),
        )
        .select_from(
            s.knowledge_concept__data.outerjoin(
                s.term, s.term.c.id == s.knowledge_concept__data.c.term_id
            )
            .outerjoin(
                s.catalog_table,
                s.catalog_table.c.id == s.knowledge_concept__data.c.table_id,
            )
            .outerjoin(
                s.catalog_schema,
                s.catalog_schema.c.id == s.catalog_table.c.schema_id,
            )
            .outerjoin(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.knowledge_concept__data.c.concept_id.in_(concept_ids))
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["term_id"] is not None:
            kind = "term"
            target_id = row["term_id"]
            name = row["term_name"]
            detail = ""
        else:
            kind = "table"
            target_id = row["table_id"]
            name = row["table_name"]
            parts = [
                str(part)
                for part in (
                    row["database_name"],
                    row["schema_name"],
                    row["table_name"],
                )
                if part
            ]
            detail = ".".join(parts)
        grouped[str(row["concept_id"])].append(
            {
                "id": row["id"],
                "kind": kind,
                "target_id": target_id,
                "name": name,
                "detail": detail,
                "confidence": row["confidence"],
                "note": row["note"],
            }
        )
    return grouped


def _evidence_counts(table: Any, column: Any, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = store().query_read(
        select(column, func.count().label("n")).where(column.in_(ids)).group_by(column)
    )
    return {str(row[column.name]): int(row["n"]) for row in rows if row[column.name]}


def _evidence_for(column: Any, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not ids:
        return {}
    rows = store().query_read(
        select(
            column,
            s.knowledge_evidence.c.page,
            s.knowledge_evidence.c.block_index,
            s.knowledge_evidence.c.quote,
            s.knowledge_evidence.c.document_id,
            s.knowledge_evidence.c.image_id,
            s.knowledge_evidence.c.source_path,
            s.knowledge_evidence.c.image_path,
        )
        .where(column.in_(ids))
        .order_by(s.knowledge_evidence.c.page, s.knowledge_evidence.c.block_index)
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = row[column.name]
        if key:
            grouped[str(key)].append(
                {
                    "page": row["page"],
                    "block_index": row["block_index"],
                    "quote": row["quote"],
                    "document_id": row["document_id"],
                    "image_id": row["image_id"],
                    "source_path": row["source_path"],
                    "image_path": row["image_path"],
                }
            )
    return grouped


def _filter_links_for_zones(
    links: dict[str, list[dict[str, Any]]], zone_ids: list[str] | None
) -> dict[str, list[dict[str, Any]]]:
    if zone_ids is None:
        return links
    from all_ontology.dal.terms import term_is_in_scope

    resolved = resolve_accessible_catalog_ids(zone_ids)
    table_ids = resolved["table_ids"]
    return {
        concept_id: [
            link
            for link in items
            if (link["kind"] == "table" and str(link["target_id"]) in table_ids)
            or (
                link["kind"] == "term"
                and term_is_in_scope(str(link["target_id"]), zone_ids, resolved)
            )
        ]
        for concept_id, items in links.items()
    }


def list_concepts(
    network_id: str, zone_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_concept)
        .where(s.knowledge_concept.c.network_id == network_id)
        .order_by(s.knowledge_concept.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    links = _filter_links_for_zones(_links_for_concepts(ids), zone_ids)
    evidence = _evidence_counts(
        s.knowledge_evidence,
        s.knowledge_evidence.c.concept_id,
        ids,
    )
    evidence_rows = _evidence_for(s.knowledge_evidence.c.concept_id, ids)
    return [
        {
            **row,
            "data_links": links.get(str(row["id"]), []),
            "evidence_count": evidence.get(str(row["id"]), 0),
            "evidence": evidence_rows.get(str(row["id"]), []),
        }
        for row in rows
    ]


def get_concept(
    concept_id: str, zone_ids: list[str] | None = None
) -> dict[str, Any] | None:
    row = next(
        iter(
            store().query_read(
                select(s.knowledge_concept).where(
                    s.knowledge_concept.c.id == concept_id
                )
            )
        ),
        None,
    )
    if row is None:
        return None
    return {
        **row,
        "data_links": _filter_links_for_zones(
            _links_for_concepts([concept_id]), zone_ids
        ).get(concept_id, []),
        "evidence_count": _evidence_counts(
            s.knowledge_evidence,
            s.knowledge_evidence.c.concept_id,
            [concept_id],
        ).get(concept_id, 0),
        "evidence": _evidence_for(s.knowledge_evidence.c.concept_id, [concept_id]).get(
            concept_id, []
        ),
    }


def update_concept(
    concept_id: str,
    *,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _CONCEPT_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Concept name is required.")
        values["name"] = name
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return get_concept(concept_id)
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_concept)
                .where(s.knowledge_concept.c.id == concept_id)
                .values(**values)
                .returning(s.knowledge_concept.c.id)
            )
        ),
        None,
    )
    return get_concept(concept_id) if row is not None else None


def delete_concept(concept_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_concept)
        .where(s.knowledge_concept.c.id == concept_id)
        .returning(s.knowledge_concept.c.id)
    )
    return bool(deleted)


def list_relations(network_id: str) -> list[dict[str, Any]]:
    source = aliased(s.knowledge_concept)
    target = aliased(s.knowledge_concept)
    rows = store().query_read(
        select(
            s.knowledge_relation,
            source.c.key.label("source_key"),
            source.c.name.label("source_name"),
            target.c.key.label("target_key"),
            target.c.name.label("target_name"),
        )
        .select_from(
            s.knowledge_relation.join(
                source, source.c.id == s.knowledge_relation.c.source_concept_id
            ).join(target, target.c.id == s.knowledge_relation.c.target_concept_id)
        )
        .where(s.knowledge_relation.c.network_id == network_id)
        .order_by(s.knowledge_relation.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    evidence = _evidence_counts(
        s.knowledge_evidence,
        s.knowledge_evidence.c.relation_id,
        ids,
    )
    evidence_rows = _evidence_for(s.knowledge_evidence.c.relation_id, ids)
    return [
        {
            **row,
            "evidence_count": evidence.get(str(row["id"]), 0),
            "evidence": evidence_rows.get(str(row["id"]), []),
        }
        for row in rows
    ]


def update_relation(
    relation_id: str,
    *,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _RELATION_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Relation name is required.")
        values["name"] = name
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_relation)
                .where(s.knowledge_relation.c.id == relation_id)
                .values(**values)
                .returning(s.knowledge_relation)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_relation(relation_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_relation)
        .where(s.knowledge_relation.c.id == relation_id)
        .returning(s.knowledge_relation.c.id)
    )
    return bool(deleted)


def list_facts(network_id: str) -> list[dict[str, Any]]:
    subject = aliased(s.knowledge_concept)
    object_concept = aliased(s.knowledge_concept)
    rows = store().query_read(
        select(
            s.knowledge_fact,
            subject.c.name.label("subject_name"),
            subject.c.key.label("subject_key"),
            object_concept.c.name.label("object_name"),
            object_concept.c.key.label("object_key"),
        )
        .select_from(
            s.knowledge_fact.join(
                subject, subject.c.id == s.knowledge_fact.c.subject_concept_id
            ).outerjoin(
                object_concept,
                object_concept.c.id == s.knowledge_fact.c.object_concept_id,
            )
        )
        .where(s.knowledge_fact.c.network_id == network_id)
        .order_by(s.knowledge_fact.c.created.desc())
    )
    ids = [str(row["id"]) for row in rows]
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        for row in store().query_read(
            select(
                s.knowledge_evidence.c.fact_id,
                s.knowledge_evidence.c.page,
                s.knowledge_evidence.c.block_index,
                s.knowledge_evidence.c.quote,
                s.knowledge_evidence.c.document_id,
                s.knowledge_evidence.c.image_id,
                s.knowledge_evidence.c.source_path,
                s.knowledge_evidence.c.image_path,
            )
            .where(s.knowledge_evidence.c.fact_id.in_(ids))
            .order_by(s.knowledge_evidence.c.page, s.knowledge_evidence.c.block_index)
        ):
            evidence[str(row["fact_id"])].append(dict(row))
    return [{**row, "evidence": evidence.get(str(row["id"]), [])} for row in rows]


def update_fact(
    fact_id: str,
    *,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _FACT_FIELDS}
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_fact)
                .where(s.knowledge_fact.c.id == fact_id)
                .values(**values)
                .returning(s.knowledge_fact)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_fact(fact_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_fact)
        .where(s.knowledge_fact.c.id == fact_id)
        .returning(s.knowledge_fact.c.id)
    )
    return bool(deleted)


def list_actions(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(
            s.knowledge_action,
            s.knowledge_concept.c.name.label("bound_concept_name"),
            s.knowledge_concept.c.key.label("bound_concept_key"),
        )
        .select_from(
            s.knowledge_action.outerjoin(
                s.knowledge_concept,
                s.knowledge_concept.c.id == s.knowledge_action.c.bound_concept_id,
            )
        )
        .where(s.knowledge_action.c.network_id == network_id)
        .order_by(s.knowledge_action.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    evidence = _evidence_for(s.knowledge_evidence.c.action_id, ids)
    capabilities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        for row in store().query_read(
            select(
                s.knowledge_action__capability.c.action_id,
                s.knowledge_capability.c.id,
                s.knowledge_capability.c.key,
                s.knowledge_capability.c.name,
                s.knowledge_capability.c.kind,
                s.knowledge_capability.c.config,
            )
            .select_from(
                s.knowledge_action__capability.join(
                    s.knowledge_capability,
                    s.knowledge_capability.c.id
                    == s.knowledge_action__capability.c.capability_id,
                )
            )
            .where(s.knowledge_action__capability.c.action_id.in_(ids))
        ):
            capabilities[str(row["action_id"])].append(
                {
                    "id": row["id"],
                    "key": row["key"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "config": row["config"] or {},
                }
            )
    return [
        {
            **row,
            "evidence": evidence.get(str(row["id"]), []),
            "capabilities": capabilities.get(str(row["id"]), []),
        }
        for row in rows
    ]


def link_action_capability(action_id: str, capability_id: str) -> dict[str, Any]:
    action = next(
        iter(
            store().query_read(
                select(s.knowledge_action.c.network_id).where(
                    s.knowledge_action.c.id == action_id
                )
            )
        ),
        None,
    )
    capability = next(
        iter(
            store().query_read(
                select(s.knowledge_capability.c.network_id).where(
                    s.knowledge_capability.c.id == capability_id
                )
            )
        ),
        None,
    )
    if action is None or capability is None:
        raise ValueError("Action or capability not found.")
    if action["network_id"] != capability["network_id"]:
        raise ValueError(
            "The action and capability must belong to the same knowledge network."
        )
    existing = store().query_read(
        select(s.knowledge_action__capability.c.id).where(
            s.knowledge_action__capability.c.action_id == action_id,
            s.knowledge_action__capability.c.capability_id == capability_id,
        )
    )
    if existing:
        return {"action_id": action_id, "capability_id": capability_id}
    store().query_write(
        s.knowledge_action__capability.insert().values(
            action_id=action_id, capability_id=capability_id
        )
    )
    return {"action_id": action_id, "capability_id": capability_id}


def unlink_action_capability(action_id: str, capability_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_action__capability)
        .where(
            s.knowledge_action__capability.c.action_id == action_id,
            s.knowledge_action__capability.c.capability_id == capability_id,
        )
        .returning(s.knowledge_action__capability.c.id)
    )
    return bool(deleted)


def get_action(action_id: str) -> dict[str, Any] | None:
    row = next(
        iter(
            store().query_read(
                select(s.knowledge_action.c.network_id).where(
                    s.knowledge_action.c.id == action_id
                )
            )
        ),
        None,
    )
    if row is None:
        return None
    return next(
        (
            item
            for item in list_actions(str(row["network_id"]))
            if item["id"] == action_id
        ),
        None,
    )


def create_action_execution(
    *,
    network_id: str,
    action_id: str,
    parameters: dict[str, Any],
    plan: dict[str, Any],
    created_by: str | None,
) -> dict[str, Any]:
    return dict(
        store().query_write(
            s.knowledge_action_execution.insert()
            .values(
                network_id=network_id,
                action_id=action_id,
                status="planned",
                parameters=parameters,
                plan=plan,
                created_by=created_by,
            )
            .returning(s.knowledge_action_execution)
        )[0]
    )


def list_action_executions(network_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_action_execution)
        .where(s.knowledge_action_execution.c.network_id == network_id)
        .order_by(s.knowledge_action_execution.c.created.desc())
        .limit(limit)
    )
    return [dict(row) for row in rows]


def update_action(action_id: str, *, patch: dict[str, Any]) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _ACTION_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Action name is required.")
        values["name"] = name
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_action)
                .where(s.knowledge_action.c.id == action_id)
                .values(**values)
                .returning(s.knowledge_action)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_action(action_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_action)
        .where(s.knowledge_action.c.id == action_id)
        .returning(s.knowledge_action.c.id)
    )
    return bool(deleted)


def list_risks(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(
            s.knowledge_risk,
            s.knowledge_concept.c.name.label("related_concept_name"),
            s.knowledge_concept.c.key.label("related_concept_key"),
        )
        .select_from(
            s.knowledge_risk.outerjoin(
                s.knowledge_concept,
                s.knowledge_concept.c.id == s.knowledge_risk.c.related_concept_id,
            )
        )
        .where(s.knowledge_risk.c.network_id == network_id)
        .order_by(s.knowledge_risk.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    evidence = _evidence_for(s.knowledge_evidence.c.risk_id, ids)
    return [{**row, "evidence": evidence.get(str(row["id"]), [])} for row in rows]


def update_risk(risk_id: str, *, patch: dict[str, Any]) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _RISK_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Risk name is required.")
        values["name"] = name
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_risk)
                .where(s.knowledge_risk.c.id == risk_id)
                .values(**values)
                .returning(s.knowledge_risk)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_risk(risk_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_risk)
        .where(s.knowledge_risk.c.id == risk_id)
        .returning(s.knowledge_risk.c.id)
    )
    return bool(deleted)


def list_metrics(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(
            s.knowledge_metric,
            s.knowledge_concept.c.name.label("concept_name"),
            s.knowledge_concept.c.key.label("concept_key"),
            s.sql_attribute.c.name.label("sql_attribute_name"),
            s.sql_attribute.c.expression.label("sql_attribute_expression"),
        )
        .select_from(
            s.knowledge_metric.outerjoin(
                s.knowledge_concept,
                s.knowledge_concept.c.id == s.knowledge_metric.c.concept_id,
            ).outerjoin(
                s.sql_attribute,
                s.sql_attribute.c.id == s.knowledge_metric.c.sql_attribute_id,
            )
        )
        .where(s.knowledge_metric.c.network_id == network_id)
        .order_by(s.knowledge_metric.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    evidence = _evidence_for(s.knowledge_evidence.c.metric_id, ids)
    return [{**dict(row), "evidence": evidence.get(str(row["id"]), [])} for row in rows]


def create_metric(
    *,
    network_id: str,
    key: str,
    name: str,
    description: str | None,
    expression: str | None,
    unit: str | None,
    concept_id: str | None,
    sql_attribute_id: str | None,
) -> dict[str, Any]:
    row = store().query_write(
        s.knowledge_metric.insert()
        .values(
            network_id=network_id,
            key=key,
            name=name.strip(),
            description=(description or "").strip() or None,
            expression=(expression or "").strip() or None,
            unit=(unit or "").strip() or None,
            concept_id=concept_id,
            sql_attribute_id=sql_attribute_id,
        )
        .returning(s.knowledge_metric)
    )[0]
    return next(item for item in list_metrics(network_id) if item["id"] == row["id"])


def update_metric(metric_id: str, *, patch: dict[str, Any]) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _METRIC_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Metric name is required.")
        values["name"] = name
    for key in ("description", "expression", "unit"):
        if key in values:
            values[key] = str(values[key] or "").strip() or None
    if "confidence" in values and values["confidence"] is not None:
        values["confidence"] = max(0.0, min(1.0, float(values["confidence"])))
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_metric)
                .where(s.knowledge_metric.c.id == metric_id)
                .values(**values)
                .returning(s.knowledge_metric.c.id)
            )
        ),
        None,
    )
    if row is None:
        return None
    return next(
        (
            item
            for item in list_metrics(
                str(
                    store().query_read(
                        select(s.knowledge_metric.c.network_id).where(
                            s.knowledge_metric.c.id == metric_id
                        )
                    )[0]["network_id"]
                )
            )
            if item["id"] == metric_id
        ),
        None,
    )


def delete_metric(metric_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_metric)
        .where(s.knowledge_metric.c.id == metric_id)
        .returning(s.knowledge_metric.c.id)
    )
    return bool(deleted)


def get_metric_context(metric_id: str) -> dict[str, Any] | None:
    """Metric fields plus the data-ontology objects it can be validated against."""
    row = next(
        iter(
            store().query_read(
                select(
                    s.knowledge_metric,
                    s.sql_attribute.c.expression.label("sql_attribute_expression"),
                )
                .select_from(
                    s.knowledge_metric.outerjoin(
                        s.sql_attribute,
                        s.sql_attribute.c.id == s.knowledge_metric.c.sql_attribute_id,
                    )
                )
                .where(s.knowledge_metric.c.id == metric_id)
            )
        ),
        None,
    )
    if row is None:
        return None
    result = dict(row)
    if result.get("concept_id"):
        term = next(
            iter(
                store().query_read(
                    select(s.knowledge_concept__data.c.term_id).where(
                        s.knowledge_concept__data.c.concept_id == result["concept_id"],
                        s.knowledge_concept__data.c.term_id.is_not(None),
                    )
                )
            ),
            None,
        )
        result["term_id"] = term["term_id"] if term else None
    else:
        result["term_id"] = None
    result.update(
        {
            "table_id": None,
            "table_name": None,
            "schema_name": None,
            "database_name": None,
        }
    )
    if result.get("concept_id"):
        table = next(
            iter(
                store().query_read(
                    select(
                        s.catalog_table.c.id.label("table_id"),
                        s.catalog_table.c.name.label("table_name"),
                        s.catalog_schema.c.name.label("schema_name"),
                        s.catalog_database.c.name.label("database_name"),
                    )
                    .select_from(
                        s.knowledge_concept__data.join(
                            s.catalog_table,
                            s.catalog_table.c.id
                            == s.knowledge_concept__data.c.table_id,
                        )
                        .join(
                            s.catalog_schema,
                            s.catalog_schema.c.id == s.catalog_table.c.schema_id,
                        )
                        .join(
                            s.catalog_database,
                            s.catalog_database.c.id == s.catalog_schema.c.database_id,
                        )
                    )
                    .where(
                        s.knowledge_concept__data.c.concept_id == result["concept_id"],
                        s.knowledge_concept__data.c.table_id.is_not(None),
                    )
                    .limit(1)
                )
            ),
            None,
        )
        if table:
            result.update(table)
    return result


def list_concept_groups(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_concept_group)
        .where(s.knowledge_concept_group.c.network_id == network_id)
        .order_by(s.knowledge_concept_group.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        for row in store().query_read(
            select(
                s.knowledge_concept_group__concept.c.group_id,
                s.knowledge_concept.c.id,
                s.knowledge_concept.c.key,
                s.knowledge_concept.c.name,
            )
            .select_from(
                s.knowledge_concept_group__concept.join(
                    s.knowledge_concept,
                    s.knowledge_concept.c.id
                    == s.knowledge_concept_group__concept.c.concept_id,
                )
            )
            .where(s.knowledge_concept_group__concept.c.group_id.in_(ids))
            .order_by(s.knowledge_concept.c.name)
        ):
            members[str(row["group_id"])].append(
                {"id": row["id"], "key": row["key"], "name": row["name"]}
            )
    return [{**row, "concepts": members.get(str(row["id"]), [])} for row in rows]


def create_concept_group(
    *,
    network_id: str,
    name: str,
    description: str | None,
    key: str,
    concept_ids: list[str],
) -> dict[str, Any]:
    group = store().query_write(
        s.knowledge_concept_group.insert()
        .values(
            network_id=network_id,
            key=key,
            name=name.strip(),
            description=(description or "").strip() or None,
        )
        .returning(s.knowledge_concept_group)
    )[0]
    for concept_id in dict.fromkeys(concept_ids):
        store().query_write(
            s.knowledge_concept_group__concept.insert().values(
                group_id=group["id"], concept_id=concept_id
            )
        )
    return next(
        item for item in list_concept_groups(network_id) if item["id"] == group["id"]
    )


def update_concept_group(
    group_id: str, *, patch: dict[str, Any]
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _GROUP_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Concept group name is required.")
        values["name"] = name
    if "description" in values:
        values["description"] = str(values["description"] or "").strip() or None
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_concept_group)
                .where(s.knowledge_concept_group.c.id == group_id)
                .values(**values)
                .returning(s.knowledge_concept_group)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_concept_group(group_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_concept_group)
        .where(s.knowledge_concept_group.c.id == group_id)
        .returning(s.knowledge_concept_group.c.id)
    )
    return bool(deleted)


def list_capabilities(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_capability)
        .where(s.knowledge_capability.c.network_id == network_id)
        .order_by(s.knowledge_capability.c.name)
    )
    return [dict(row) for row in rows]


def create_capability(
    *,
    network_id: str,
    key: str,
    name: str,
    kind: str,
    description: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    return dict(
        store().query_write(
            s.knowledge_capability.insert()
            .values(
                network_id=network_id,
                key=key,
                name=name.strip(),
                kind=kind,
                description=(description or "").strip() or None,
                config=config or {},
            )
            .returning(s.knowledge_capability)
        )[0]
    )


def update_capability(
    capability_id: str, *, patch: dict[str, Any]
) -> dict[str, Any] | None:
    values = {key: value for key, value in patch.items() if key in _CAPABILITY_FIELDS}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            raise ValueError("Capability name is required.")
        values["name"] = name
    if "description" in values:
        values["description"] = str(values["description"] or "").strip() or None
    if not values:
        return None
    values["modified"] = func.now()
    row = next(
        iter(
            store().query_write(
                update(s.knowledge_capability)
                .where(s.knowledge_capability.c.id == capability_id)
                .values(**values)
                .returning(s.knowledge_capability)
            )
        ),
        None,
    )
    return dict(row) if row is not None else None


def delete_capability(capability_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_capability)
        .where(s.knowledge_capability.c.id == capability_id)
        .returning(s.knowledge_capability.c.id)
    )
    return bool(deleted)


def list_eval_cases(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_eval_case)
        .where(s.knowledge_eval_case.c.network_id == network_id)
        .order_by(s.knowledge_eval_case.c.created.desc())
    )
    return [dict(row) for row in rows]


def create_eval_case(
    *,
    network_id: str,
    question: str,
    expected_concepts: list[str],
    expected_facts: list[str],
    notes: str | None,
) -> dict[str, Any]:
    return dict(
        store().query_write(
            s.knowledge_eval_case.insert()
            .values(
                network_id=network_id,
                question=question.strip(),
                expected_concepts=expected_concepts,
                expected_facts=expected_facts,
                notes=(notes or "").strip() or None,
            )
            .returning(s.knowledge_eval_case)
        )[0]
    )


def delete_eval_case(case_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_eval_case)
        .where(s.knowledge_eval_case.c.id == case_id)
        .returning(s.knowledge_eval_case.c.id)
    )
    return bool(deleted)


def list_eval_runs(network_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_eval_run)
        .where(s.knowledge_eval_run.c.network_id == network_id)
        .order_by(s.knowledge_eval_run.c.created.desc())
        .limit(limit)
    )
    return [dict(row) for row in rows]


def save_eval_run(
    *,
    network_id: str,
    total: int,
    passed: int,
    details: list[dict[str, Any]],
    created_by: str | None,
) -> dict[str, Any]:
    return dict(
        store().query_write(
            s.knowledge_eval_run.insert()
            .values(
                network_id=network_id,
                total=total,
                passed=passed,
                details=details,
                created_by=created_by,
            )
            .returning(s.knowledge_eval_run)
        )[0]
    )


def import_bkn_definitions(
    network_id: str,
    *,
    concepts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Upsert a parsed BKN package without inventing document evidence."""
    with write_transaction():
        existing_concepts = {
            str(row["key"]): row
            for row in store().query_read(
                select(s.knowledge_concept).where(
                    s.knowledge_concept.c.network_id == network_id
                )
            )
        }
        concept_ids: dict[str, str] = {}
        for concept in concepts:
            key = str(concept["key"])
            values = {
                "name": concept["name"],
                "description": concept.get("description") or None,
                "kind": concept.get("kind") or "entity",
                "aliases": concept.get("aliases") or [],
                "attributes": concept.get("attributes") or [],
            }
            existing = existing_concepts.get(key)
            if existing is None:
                concept_ids[key] = str(
                    store().query_write(
                        s.knowledge_concept.insert()
                        .values(network_id=network_id, key=key, **values)
                        .returning(s.knowledge_concept.c.id)
                    )[0]["id"]
                )
            else:
                concept_ids[key] = str(existing["id"])
                store().query_write(
                    update(s.knowledge_concept)
                    .where(s.knowledge_concept.c.id == concept_ids[key])
                    .values(
                        **values,
                        aliases=_merge_aliases(
                            existing.get("aliases"), values["aliases"]
                        ),
                        attributes=_merge_attributes(
                            existing.get("attributes"), values["attributes"]
                        ),
                        modified=func.now(),
                    )
                )

        existing_relations = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_relation.c.id, s.knowledge_relation.c.key).where(
                    s.knowledge_relation.c.network_id == network_id
                )
            )
        }
        for relation in relations:
            source_id = concept_ids.get(str(relation["source_key"]))
            target_id = concept_ids.get(str(relation["target_key"]))
            if source_id is None or target_id is None:
                continue
            key = str(relation["key"])
            values = {
                "name": relation["name"],
                "description": relation.get("description") or None,
                "kind": relation.get("kind") or "association",
                "source_concept_id": source_id,
                "target_concept_id": target_id,
            }
            relation_id = existing_relations.get(key)
            if relation_id is None:
                store().query_write(
                    s.knowledge_relation.insert().values(
                        network_id=network_id, key=key, **values
                    )
                )
            else:
                store().query_write(
                    update(s.knowledge_relation)
                    .where(s.knowledge_relation.c.id == relation_id)
                    .values(**values, modified=func.now())
                )

        existing_actions = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_action.c.id, s.knowledge_action.c.key).where(
                    s.knowledge_action.c.network_id == network_id
                )
            )
        }
        for action in actions:
            key = str(action["key"])
            bound_id = concept_ids.get(str(action.get("bound_key") or ""))
            values = {
                "name": action["name"],
                "description": action.get("description") or None,
                "action_intent": action.get("action_intent") or "execute",
                "bound_concept_id": bound_id,
                "parameters": action.get("parameters") or [],
            }
            action_id = existing_actions.get(key)
            if action_id is None:
                store().query_write(
                    s.knowledge_action.insert().values(
                        network_id=network_id, key=key, **values
                    )
                )
            else:
                store().query_write(
                    update(s.knowledge_action)
                    .where(s.knowledge_action.c.id == action_id)
                    .values(**values, modified=func.now())
                )

        existing_risks = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_risk.c.id, s.knowledge_risk.c.key).where(
                    s.knowledge_risk.c.network_id == network_id
                )
            )
        }
        for risk in risks:
            key = str(risk["key"])
            related_id = concept_ids.get(str(risk.get("related_key") or ""))
            values = {
                "name": risk["name"],
                "description": risk.get("description") or None,
                "severity": risk.get("severity") or "medium",
                "mitigation": risk.get("mitigation") or None,
                "related_concept_id": related_id,
            }
            risk_id = existing_risks.get(key)
            if risk_id is None:
                store().query_write(
                    s.knowledge_risk.insert().values(
                        network_id=network_id, key=key, **values
                    )
                )
            else:
                store().query_write(
                    update(s.knowledge_risk)
                    .where(s.knowledge_risk.c.id == risk_id)
                    .values(**values, modified=func.now())
                )

        existing_metrics = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_metric.c.id, s.knowledge_metric.c.key).where(
                    s.knowledge_metric.c.network_id == network_id
                )
            )
        }
        for metric in metrics:
            key = str(metric["key"])
            concept_id = concept_ids.get(str(metric.get("concept_key") or ""))
            values = {
                "name": metric["name"],
                "description": metric.get("description") or None,
                "expression": metric.get("expression") or None,
                "unit": metric.get("unit") or None,
                "concept_id": concept_id,
            }
            metric_id = existing_metrics.get(key)
            if metric_id is None:
                store().query_write(
                    s.knowledge_metric.insert().values(
                        network_id=network_id, key=key, **values
                    )
                )
            else:
                store().query_write(
                    update(s.knowledge_metric)
                    .where(s.knowledge_metric.c.id == metric_id)
                    .values(**values, modified=func.now())
                )

        existing_groups = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(
                    s.knowledge_concept_group.c.id, s.knowledge_concept_group.c.key
                ).where(s.knowledge_concept_group.c.network_id == network_id)
            )
        }
        for group in groups:
            key = str(group["key"])
            group_id = existing_groups.get(key)
            values = {
                "name": group["name"],
                "description": group.get("description") or None,
            }
            if group_id is None:
                group_id = str(
                    store().query_write(
                        s.knowledge_concept_group.insert()
                        .values(network_id=network_id, key=key, **values)
                        .returning(s.knowledge_concept_group.c.id)
                    )[0]["id"]
                )
                existing_groups[key] = group_id
            else:
                store().query_write(
                    update(s.knowledge_concept_group)
                    .where(s.knowledge_concept_group.c.id == group_id)
                    .values(**values, modified=func.now())
                )
            for concept_key in group.get("concept_keys") or []:
                concept_id = concept_ids.get(str(concept_key))
                if concept_id is None:
                    continue
                duplicate = store().query_read(
                    select(s.knowledge_concept_group__concept.c.id).where(
                        s.knowledge_concept_group__concept.c.group_id == group_id,
                        s.knowledge_concept_group__concept.c.concept_id == concept_id,
                    )
                )
                if not duplicate:
                    store().query_write(
                        s.knowledge_concept_group__concept.insert().values(
                            group_id=group_id, concept_id=concept_id
                        )
                    )

        existing_capabilities = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_capability.c.id, s.knowledge_capability.c.key).where(
                    s.knowledge_capability.c.network_id == network_id
                )
            )
        }
        for capability in capabilities or []:
            key = str(capability["key"])
            values = {
                "name": capability["name"],
                "kind": capability.get("kind") or "skill",
                "description": capability.get("description") or None,
                "config": capability.get("config") or {},
            }
            capability_id = existing_capabilities.get(key)
            if capability_id is None:
                store().query_write(
                    s.knowledge_capability.insert().values(
                        network_id=network_id, key=key, **values
                    )
                )
            else:
                store().query_write(
                    update(s.knowledge_capability)
                    .where(s.knowledge_capability.c.id == capability_id)
                    .values(**values, modified=func.now())
                )

    return {
        "concept_count": len(concepts),
        "relation_count": len(relations),
        "action_count": len(actions),
        "risk_count": len(risks),
        "metric_count": len(metrics),
        "group_count": len(groups),
        "capability_count": len(capabilities or []),
    }


def list_data_targets(
    query: str | None,
    *,
    limit: int = 25,
    zone_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    pattern = f"%{(query or '').strip()}%"
    from all_ontology.dal.terms import term_is_in_scope

    resolved = (
        resolve_accessible_catalog_ids(zone_ids) if zone_ids is not None else None
    )
    terms = store().query_read(
        select(
            s.term.c.id,
            s.term.c.name,
            s.term.c.description,
        )
        .where(s.term.c.name.ilike(pattern))
        .order_by(s.term.c.name)
        .limit(limit * 4 if resolved is not None else limit)
    )
    tables = store().query_read(
        select(
            s.catalog_table.c.id,
            s.catalog_table.c.name,
            s.catalog_table.c.description,
            s.catalog_schema.c.name.label("schema_name"),
            s.catalog_database.c.name.label("database_name"),
        )
        .select_from(
            s.catalog_table.join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            ).join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(
            or_(
                s.catalog_table.c.name.ilike(pattern),
                s.catalog_table.c.description.ilike(pattern),
            )
        )
        .order_by(s.catalog_table.c.name)
        .limit(limit * 4 if resolved is not None else limit)
    )
    if resolved is not None:
        terms = [
            row for row in terms if term_is_in_scope(str(row["id"]), zone_ids, resolved)
        ][:limit]
        tables = [row for row in tables if str(row["id"]) in resolved["table_ids"]][
            :limit
        ]
    targets = [
        {
            "kind": "term",
            "id": row["id"],
            "name": row["name"],
            "detail": row["description"] or "",
        }
        for row in terms
    ]
    targets.extend(
        {
            "kind": "table",
            "id": row["id"],
            "name": row["name"],
            "detail": ".".join(
                part
                for part in (
                    row["database_name"],
                    row["schema_name"],
                    row["name"],
                )
                if part
            ),
        }
        for row in tables
    )
    return targets[: limit * 2]


def create_data_link(
    *,
    concept_id: str,
    target_kind: str,
    target_id: str,
    note: str | None,
    zone_ids: list[str] | None = None,
) -> dict[str, Any]:
    concept = get_concept(concept_id)
    if concept is None:
        raise ValueError("Concept not found.")
    if target_kind not in {"term", "table"}:
        raise ValueError("target_kind must be term or table.")
    column = s.term.c.id if target_kind == "term" else s.catalog_table.c.id
    table = s.term if target_kind == "term" else s.catalog_table
    if not store().query_read(select(column).where(column == target_id)):
        raise ValueError("Data object not found.")
    if zone_ids is not None:
        from all_ontology.dal.terms import term_is_in_scope

        resolved = resolve_accessible_catalog_ids(zone_ids)
        if target_kind == "term":
            if not term_is_in_scope(target_id, zone_ids, resolved):
                raise ValueError(
                    "The data object is outside your current data permissions."
                )
        elif target_id not in resolved["table_ids"]:
            raise ValueError(
                "The data object is outside your current data permissions."
            )
    target_column = (
        s.knowledge_concept__data.c.term_id
        if target_kind == "term"
        else s.knowledge_concept__data.c.table_id
    )
    existing = store().query_read(
        select(s.knowledge_concept__data.c.id).where(
            s.knowledge_concept__data.c.concept_id == concept_id,
            target_column == target_id,
        )
    )
    if existing:
        raise ValueError("This concept is already linked to that data object.")
    values: dict[str, Any] = {
        "concept_id": concept_id,
        "term_id": target_id if target_kind == "term" else None,
        "table_id": target_id if target_kind == "table" else None,
        "note": note,
    }
    row = store().query_write(
        s.knowledge_concept__data.insert()
        .values(**values)
        .returning(s.knowledge_concept__data)
    )[0]
    name = store().query_read(select(table.c.name).where(table.c.id == target_id))[0][
        "name"
    ]
    return {
        **row,
        "kind": target_kind,
        "target_id": target_id,
        "name": name,
        "detail": "" if target_kind == "term" else name,
    }


def delete_data_link(link_id: str) -> bool:
    deleted = store().query_write(
        delete(s.knowledge_concept__data)
        .where(s.knowledge_concept__data.c.id == link_id)
        .returning(s.knowledge_concept__data.c.id)
    )
    return bool(deleted)


def _merge_aliases(existing: Iterable[Any], incoming: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in list(existing or []) + list(incoming or []):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged[:20]


def _merge_attributes(
    existing: Iterable[Any], incoming: Iterable[Any]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in list(existing or []) + list(incoming or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        current = merged.setdefault(
            name,
            {
                "name": name,
                "display_name": item.get("display_name") or name,
                "type": item.get("type") or "string",
                "value": item.get("value"),
                "description": item.get("description") or "",
            },
        )
        if item.get("value") not in (None, "") and not current.get("value"):
            current["value"] = item.get("value")
        if len(str(item.get("description") or "")) > len(
            str(current.get("description") or "")
        ):
            current["description"] = item.get("description")
    return list(merged.values())[:200]


def _knowledge_parse_context(
    document_id: str,
) -> tuple[dict[str, Any] | None, dict[tuple[Any, Any], dict[str, Any]]]:
    """The parse run's source paths and picture rows for evidence attachment."""
    row = next(
        iter(
            store().query_read(
                select(s.knowledge_document.c.run_id).where(
                    s.knowledge_document.c.id == document_id
                )
            )
        ),
        None,
    )
    run_id = row["run_id"] if row else None
    if not run_id:
        return None, {}
    parsed = next(
        iter(
            store().query_read(
                select(
                    s.parsing_document.c.id.label("parsing_document_id"),
                    s.parsing_document.c.source_md5,
                    s.parsing_document.c.source_path,
                    s.parsing_document.c.parsed_md_path,
                )
                .select_from(
                    s.parsing_run.join(
                        s.parsing_document,
                        s.parsing_document.c.id == s.parsing_run.c.document_id,
                    )
                )
                .where(s.parsing_run.c.id == run_id)
            )
        ),
        None,
    )
    images = store().query_read(
        select(s.parsing_image)
        .where(s.parsing_image.c.run_id == run_id)
        .order_by(s.parsing_image.c.page, s.parsing_image.c.block_index)
    )
    by_page: dict[tuple[Any, Any], dict[str, Any]] = {}
    for image in images:
        item = dict(image)
        by_page[(item["page"], item["block_index"])] = item
        by_page.setdefault((item["page"], None), item)
    context = dict(parsed) if parsed is not None else None
    if context is not None:
        context["run_id"] = run_id
    return context, by_page


def save_extraction(
    document_id: str,
    *,
    summary: str,
    concepts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    chunks: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    chunk_count: int,
) -> dict[str, Any]:
    """Replace one document's claims and citations in a single transaction."""
    document = get_document(document_id)
    if document is None:
        raise ValueError("Knowledge document not found.")
    network_id = str(document["network_id"])
    parse_context, images_by_page = _knowledge_parse_context(document_id)
    source_path = (parse_context or {}).get("source_path")
    learned_images: set[str] = set()

    with write_transaction():
        store().query_write(
            delete(s.knowledge_evidence).where(
                s.knowledge_evidence.c.document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_fact).where(
                s.knowledge_fact.c.source_document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_relation).where(
                s.knowledge_relation.c.source_document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_action).where(
                s.knowledge_action.c.source_document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_chunk).where(
                s.knowledge_chunk.c.document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_risk).where(
                s.knowledge_risk.c.source_document_id == document_id
            )
        )
        store().query_write(
            delete(s.knowledge_metric).where(
                s.knowledge_metric.c.source_document_id == document_id
            )
        )

        existing_rows = store().query_read(
            select(s.knowledge_concept).where(
                s.knowledge_concept.c.network_id == network_id
            )
        )
        by_key = {str(row["key"]): row for row in existing_rows}
        concept_ids: dict[str, str] = {}

        for concept in concepts:
            key = str(concept["key"])
            existing = by_key.get(key)
            values = {
                "name": concept["name"],
                "description": concept.get("description") or None,
                "kind": concept.get("kind") or "entity",
                "aliases": concept.get("aliases") or [],
                "attributes": concept.get("attributes") or [],
                "confidence": float(concept.get("confidence") or 0.6),
            }
            if existing is None:
                row = store().query_write(
                    s.knowledge_concept.insert()
                    .values(
                        network_id=network_id,
                        key=key,
                        source_document_id=document_id,
                        **values,
                    )
                    .returning(s.knowledge_concept.c.id)
                )[0]
                concept_id = str(row["id"])
                by_key[key] = {
                    "id": concept_id,
                    "key": key,
                    **values,
                }
            else:
                concept_id = str(existing["id"])
                description = values["description"]
                if len(str(existing.get("description") or "")) > len(
                    str(description or "")
                ):
                    description = existing.get("description")
                store().query_write(
                    update(s.knowledge_concept)
                    .where(s.knowledge_concept.c.id == concept_id)
                    .values(
                        name=values["name"],
                        description=description,
                        kind=values["kind"]
                        if values["kind"] != "entity"
                        else existing.get("kind") or "entity",
                        aliases=_merge_aliases(
                            existing.get("aliases"), values["aliases"]
                        ),
                        attributes=_merge_attributes(
                            existing.get("attributes"), values["attributes"]
                        ),
                        confidence=max(
                            float(existing.get("confidence") or 0.0),
                            values["confidence"],
                        ),
                        modified=func.now(),
                    )
                )
            concept_ids[key] = concept_id
            for evidence in concept.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    concept_id=concept_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        existing_relations = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_relation.c.id, s.knowledge_relation.c.key).where(
                    s.knowledge_relation.c.network_id == network_id
                )
            )
        }
        relation_ids: dict[str, str] = {}
        for relation in relations:
            source_id = concept_ids.get(str(relation["source_key"]))
            target_id = concept_ids.get(str(relation["target_key"]))
            if source_id is None or target_id is None:
                continue
            key = str(relation["key"])
            relation_id = existing_relations.get(key)
            if relation_id is None:
                relation_id = str(
                    store().query_write(
                        s.knowledge_relation.insert()
                        .values(
                            network_id=network_id,
                            key=key,
                            source_concept_id=source_id,
                            target_concept_id=target_id,
                            name=relation["name"],
                            description=relation.get("description") or None,
                            kind=relation.get("kind") or "association",
                            confidence=float(relation.get("confidence") or 0.6),
                            source_document_id=document_id,
                        )
                        .returning(s.knowledge_relation.c.id)
                    )[0]["id"]
                )
                existing_relations[key] = relation_id
            else:
                store().query_write(
                    update(s.knowledge_relation)
                    .where(s.knowledge_relation.c.id == relation_id)
                    .values(
                        name=relation["name"],
                        description=relation.get("description") or None,
                        kind=relation.get("kind") or "association",
                        confidence=float(relation.get("confidence") or 0.6),
                        modified=func.now(),
                    )
                )
            relation_ids[key] = relation_id
            for evidence in relation.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    relation_id=relation_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        for fact in facts:
            subject_id = concept_ids.get(str(fact["subject_key"]))
            if subject_id is None:
                continue
            object_id = (
                concept_ids.get(str(fact["object_key"]))
                if fact.get("object_key")
                else None
            )
            relation_id = (
                relation_ids.get(str(fact.get("relation_key") or ""))
                if fact.get("relation_key")
                else None
            )
            fact_id = str(
                store().query_write(
                    s.knowledge_fact.insert()
                    .values(
                        network_id=network_id,
                        subject_concept_id=subject_id,
                        relation_id=relation_id,
                        object_concept_id=object_id,
                        object_text=fact.get("object_text") or None,
                        predicate=fact["predicate"],
                        statement=fact["statement"],
                        confidence=float(fact.get("confidence") or 0.6),
                        source_document_id=document_id,
                    )
                    .returning(s.knowledge_fact.c.id)
                )[0]["id"]
            )
            for evidence in fact.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    fact_id=fact_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        existing_actions = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_action.c.id, s.knowledge_action.c.key).where(
                    s.knowledge_action.c.network_id == network_id
                )
            )
        }
        for action in actions or []:
            key = str(action["key"])
            bound_id = (
                concept_ids.get(str(action.get("bound_key") or ""))
                if action.get("bound_key")
                else None
            )
            values = {
                "name": action["name"],
                "description": action.get("description") or None,
                "action_intent": action.get("action_intent") or "execute",
                "bound_concept_id": bound_id,
                "parameters": action.get("parameters") or [],
                "confidence": float(action.get("confidence") or 0.6),
            }
            action_id = existing_actions.get(key)
            if action_id is None:
                action_id = str(
                    store().query_write(
                        s.knowledge_action.insert()
                        .values(
                            network_id=network_id,
                            key=key,
                            source_document_id=document_id,
                            **values,
                        )
                        .returning(s.knowledge_action.c.id)
                    )[0]["id"]
                )
            else:
                store().query_write(
                    update(s.knowledge_action)
                    .where(s.knowledge_action.c.id == action_id)
                    .values(**values, modified=func.now())
                )
            for evidence in action.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    action_id=action_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        existing_risks = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_risk.c.id, s.knowledge_risk.c.key).where(
                    s.knowledge_risk.c.network_id == network_id
                )
            )
        }
        for risk in risks or []:
            key = str(risk["key"])
            related_id = (
                concept_ids.get(str(risk.get("related_key") or ""))
                if risk.get("related_key")
                else None
            )
            values = {
                "name": risk["name"],
                "description": risk.get("description") or None,
                "severity": risk.get("severity") or "medium",
                "mitigation": risk.get("mitigation") or None,
                "related_concept_id": related_id,
                "confidence": float(risk.get("confidence") or 0.6),
            }
            risk_id = existing_risks.get(key)
            if risk_id is None:
                risk_id = str(
                    store().query_write(
                        s.knowledge_risk.insert()
                        .values(
                            network_id=network_id,
                            key=key,
                            source_document_id=document_id,
                            **values,
                        )
                        .returning(s.knowledge_risk.c.id)
                    )[0]["id"]
                )
            else:
                store().query_write(
                    update(s.knowledge_risk)
                    .where(s.knowledge_risk.c.id == risk_id)
                    .values(**values, modified=func.now())
                )
            for evidence in risk.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    risk_id=risk_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        existing_metrics = {
            str(row["key"]): str(row["id"])
            for row in store().query_read(
                select(s.knowledge_metric.c.id, s.knowledge_metric.c.key).where(
                    s.knowledge_metric.c.network_id == network_id
                )
            )
        }
        for metric in metrics or []:
            key = str(metric["key"])
            concept_id = (
                concept_ids.get(str(metric.get("concept_key") or ""))
                if metric.get("concept_key")
                else None
            )
            values = {
                "name": metric["name"],
                "description": metric.get("description") or None,
                "expression": metric.get("expression") or None,
                "unit": metric.get("unit") or None,
                "concept_id": concept_id,
                "confidence": float(metric.get("confidence") or 0.6),
            }
            metric_id = existing_metrics.get(key)
            if metric_id is None:
                metric_id = str(
                    store().query_write(
                        s.knowledge_metric.insert()
                        .values(
                            network_id=network_id,
                            key=key,
                            source_document_id=document_id,
                            **values,
                        )
                        .returning(s.knowledge_metric.c.id)
                    )[0]["id"]
                )
            else:
                store().query_write(
                    update(s.knowledge_metric)
                    .where(s.knowledge_metric.c.id == metric_id)
                    .values(**values, modified=func.now())
                )
            for evidence in metric.get("evidence") or []:
                image_id = _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    metric_id=metric_id,
                    evidence=evidence,
                    images_by_page=images_by_page,
                    source_path=source_path,
                )
                if image_id:
                    learned_images.add(image_id)

        for chunk in chunks or []:
            text = str(chunk.get("text") or "")
            if not text.strip():
                continue
            store().query_write(
                s.knowledge_chunk.insert().values(
                    network_id=network_id,
                    document_id=document_id,
                    chunk_index=int(chunk.get("chunk_index") or 0),
                    text=text,
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                    block_start=chunk.get("block_start"),
                    block_end=chunk.get("block_end"),
                )
            )

        store().query_write(
            update(s.knowledge_document)
            .where(s.knowledge_document.c.id == document_id)
            .values(
                status="extracted",
                summary=summary or None,
                error_message=None,
                chunk_count=chunk_count,
                extracted_at=func.now(),
            )
        )

    if parse_context and parse_context.get("parsing_document_id"):
        from all_ontology.parsing import store as parsing_store

        parsing_store.mark_learned(
            document_id=str(parse_context["parsing_document_id"]),
            knowledge_document_id=document_id,
            image_ids=learned_images,
        )

    concept_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_concept)
        .where(s.knowledge_concept.c.network_id == network_id)
    )[0]["n"]
    relation_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_relation)
        .where(s.knowledge_relation.c.network_id == network_id)
    )[0]["n"]
    fact_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_fact)
        .where(s.knowledge_fact.c.network_id == network_id)
    )[0]["n"]
    action_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_action)
        .where(s.knowledge_action.c.network_id == network_id)
    )[0]["n"]
    risk_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_risk)
        .where(s.knowledge_risk.c.network_id == network_id)
    )[0]["n"]
    metric_count = store().query_read(
        select(func.count().label("n"))
        .select_from(s.knowledge_metric)
        .where(s.knowledge_metric.c.network_id == network_id)
    )[0]["n"]
    return {
        "network_id": network_id,
        "concept_count": int(concept_count),
        "relation_count": int(relation_count),
        "fact_count": int(fact_count),
        "action_count": int(action_count),
        "risk_count": int(risk_count),
        "metric_count": int(metric_count),
    }


def _insert_evidence(
    *,
    network_id: str,
    document_id: str,
    evidence: dict[str, Any],
    concept_id: str | None = None,
    relation_id: str | None = None,
    fact_id: str | None = None,
    action_id: str | None = None,
    risk_id: str | None = None,
    metric_id: str | None = None,
    images_by_page: dict[tuple[int | None, int | None], dict[str, Any]] | None = None,
    source_path: str | None = None,
) -> str | None:
    quote = str(evidence.get("quote") or "").strip()
    if not quote:
        return None
    page = evidence.get("page")
    block_index = evidence.get("block_index")
    image = None
    if images_by_page:
        image = images_by_page.get((page, block_index)) or images_by_page.get(
            (page, None)
        )
    store().query_write(
        s.knowledge_evidence.insert().values(
            network_id=network_id,
            document_id=document_id,
            concept_id=concept_id,
            relation_id=relation_id,
            fact_id=fact_id,
            action_id=action_id,
            risk_id=risk_id,
            metric_id=metric_id,
            image_id=image.get("id") if image else None,
            source_path=source_path,
            image_path=image.get("image_path") if image else None,
            page=page,
            block_index=block_index,
            quote=quote[:4000],
        )
    )
    return str(image["id"]) if image and image.get("id") else None
