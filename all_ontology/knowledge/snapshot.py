# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Whole-network snapshots for versioning and rollback.

A snapshot is deliberately the *definitions* graph, not the source documents
themselves. Documents stay in the parse library; rolling a network back swaps
its concepts/relations/facts/actions/risks/metrics/groups/capabilities and
their evidence, leaving the documents and their parsing runs untouched.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, select

from all_ontology.dal import knowledge as knowledge_dal
from all_ontology.dal import schema as s
from all_ontology.dal.session import store, write_transaction


def build_snapshot(network_id: str) -> dict[str, Any]:
    network = knowledge_dal.get_network(network_id)
    if network is None:
        raise ValueError("Knowledge network not found.")
    return {
        "network": {
            key: network.get(key)
            for key in (
                "name",
                "description",
                "domain",
                "status",
                "version",
            )
        },
        "concepts": knowledge_dal.list_concepts(network_id),
        "relations": knowledge_dal.list_relations(network_id),
        "facts": knowledge_dal.list_facts(network_id),
        "actions": knowledge_dal.list_actions(network_id),
        "risks": knowledge_dal.list_risks(network_id),
        "metrics": knowledge_dal.list_metrics(network_id),
        "groups": knowledge_dal.list_concept_groups(network_id),
        "capabilities": knowledge_dal.list_capabilities(network_id),
    }


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def create_version(
    network_id: str, *, label: str | None, created_by: str | None
) -> dict[str, Any]:
    if knowledge_dal.get_network(network_id) is None:
        raise ValueError("Knowledge network not found.")
    snapshot = _json_safe(build_snapshot(network_id))
    version = (
        store().query_read(
            select(
                func.coalesce(func.max(s.knowledge_network_version.c.version), 0).label(
                    "v"
                )
            ).where(s.knowledge_network_version.c.network_id == network_id)
        )[0]["v"]
        + 1
    )
    row = store().query_write(
        s.knowledge_network_version.insert()
        .values(
            network_id=network_id,
            version=version,
            label=(label or "").strip() or None,
            snapshot=snapshot,
            created_by=created_by,
        )
        .returning(
            s.knowledge_network_version.c.id,
            s.knowledge_network_version.c.version,
            s.knowledge_network_version.c.label,
            s.knowledge_network_version.c.created,
        )
    )[0]
    return dict(row)


def list_versions(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(
            s.knowledge_network_version.c.id,
            s.knowledge_network_version.c.version,
            s.knowledge_network_version.c.label,
            s.knowledge_network_version.c.created,
            s.knowledge_network_version.c.created_by,
        )
        .where(s.knowledge_network_version.c.network_id == network_id)
        .order_by(s.knowledge_network_version.c.version.desc())
    )
    return [dict(row) for row in rows]


def get_version(version_id: str) -> dict[str, Any] | None:
    return next(
        iter(
            store().query_read(
                select(s.knowledge_network_version).where(
                    s.knowledge_network_version.c.id == version_id
                )
            )
        ),
        None,
    )


_DIFF_COLLECTIONS = (
    "concepts",
    "relations",
    "facts",
    "actions",
    "risks",
    "metrics",
    "groups",
    "capabilities",
)


def _item_key(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("id") or item.get("statement") or "")


def _item_label(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("statement") or item.get("key") or "")


def _stable(item: dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)


def _diff_collection(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, Any]:
    before_map = {_item_key(item): item for item in before if _item_key(item)}
    after_map = {_item_key(item): item for item in after if _item_key(item)}
    added = [
        {"key": key, "label": _item_label(item)}
        for key, item in after_map.items()
        if key not in before_map
    ]
    removed = [
        {"key": key, "label": _item_label(item)}
        for key, item in before_map.items()
        if key not in after_map
    ]
    changed = []
    for key in sorted(before_map.keys() & after_map.keys()):
        before_item = before_map[key]
        after_item = after_map[key]
        if _stable(before_item) == _stable(after_item):
            continue
        fields = sorted(
            field
            for field in before_item.keys() | after_item.keys()
            if _stable({field: before_item.get(field)})
            != _stable({field: after_item.get(field)})
        )
        changed.append(
            {
                "key": key,
                "label": _item_label(after_item),
                "fields": fields,
                "before": {field: before_item.get(field) for field in fields},
                "after": {field: after_item.get(field) for field in fields},
            }
        )
    return {
        "before_count": len(before_map),
        "after_count": len(after_map),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    network_before = before.get("network") or {}
    network_after = after.get("network") or {}
    collections = {
        name: _diff_collection(
            before.get(name) or [],
            after.get(name) or [],
        )
        for name in _DIFF_COLLECTIONS
    }
    return {
        "network_changed": _stable(network_before) != _stable(network_after),
        "network_before": network_before,
        "network_after": network_after,
        "collections": collections,
    }


def diff_version(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise ValueError("Knowledge network version not found.")
    network_id = str(version["network_id"])
    current = build_snapshot(network_id)
    result = diff_snapshots(version["snapshot"], current)
    return {
        "version_id": version_id,
        "version": version["version"],
        "label": version.get("label"),
        **result,
    }


def _insert_evidence(
    *,
    network_id: str,
    document_id: str,
    item: dict[str, Any],
    concept_id: str | None = None,
    relation_id: str | None = None,
    fact_id: str | None = None,
    action_id: str | None = None,
    risk_id: str | None = None,
    metric_id: str | None = None,
) -> None:
    quote = str(item.get("quote") or "").strip()
    if not quote:
        return
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
            page=item.get("page"),
            block_index=item.get("block_index"),
            quote=quote[:4000],
        )
    )


def restore_version(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise ValueError("Knowledge network version not found.")
    network_id = str(version["network_id"])
    snapshot = version["snapshot"]
    document_ids = {
        str(row["id"])
        for row in store().query_read(
            select(s.knowledge_document.c.id).where(
                s.knowledge_document.c.network_id == network_id
            )
        )
    }
    term_ids = {str(row["id"]) for row in store().query_read(select(s.term.c.id))}
    table_ids = {
        str(row["id"]) for row in store().query_read(select(s.catalog_table.c.id))
    }

    with write_transaction():
        store().query_write(
            delete(s.knowledge_concept_group__concept).where(
                s.knowledge_concept_group__concept.c.group_id.in_(
                    select(s.knowledge_concept_group.c.id).where(
                        s.knowledge_concept_group.c.network_id == network_id
                    )
                )
            )
        )
        for table in (
            s.knowledge_concept_group,
            s.knowledge_capability,
            s.knowledge_metric,
            s.knowledge_action,
            s.knowledge_risk,
            s.knowledge_fact,
            s.knowledge_evidence,
            s.knowledge_relation,
            s.knowledge_concept,
        ):
            store().query_write(delete(table).where(table.c.network_id == network_id))
        store().query_write(
            delete(s.knowledge_concept__data).where(
                s.knowledge_concept__data.c.concept_id.in_(
                    select(s.knowledge_concept.c.id).where(
                        s.knowledge_concept.c.network_id == network_id
                    )
                )
            )
        )

        network_values = snapshot.get("network") or {}
        store().query_write(
            s.knowledge_network.update()
            .where(s.knowledge_network.c.id == network_id)
            .values(
                name=network_values.get("name") or "Untitled",
                description=network_values.get("description"),
                domain=network_values.get("domain"),
                status=network_values.get("status") or "draft",
                version=network_values.get("version") or "1.0",
                modified=func.now(),
            )
        )

        for concept in snapshot.get("concepts") or []:
            source_document_id = concept.get("source_document_id")
            store().query_write(
                s.knowledge_concept.insert().values(
                    id=concept["id"],
                    network_id=network_id,
                    key=concept["key"],
                    name=concept["name"],
                    description=concept.get("description"),
                    kind=concept.get("kind") or "entity",
                    aliases=concept.get("aliases") or [],
                    attributes=concept.get("attributes") or [],
                    status=concept.get("status") or "draft",
                    confidence=float(concept.get("confidence") or 0.6),
                    source_document_id=(
                        source_document_id
                        if source_document_id in document_ids
                        else None
                    ),
                )
            )
            for link in concept.get("data_links") or []:
                term_id = link.get("target_id") if link.get("kind") == "term" else None
                table_id = (
                    link.get("target_id") if link.get("kind") == "table" else None
                )
                if (term_id and term_id not in term_ids) or (
                    table_id and table_id not in table_ids
                ):
                    continue
                link_values = {
                    "concept_id": concept["id"],
                    "term_id": term_id,
                    "table_id": table_id,
                    "confidence": float(link.get("confidence") or 0.8),
                    "note": link.get("note"),
                }
                if link.get("id"):
                    link_values["id"] = link["id"]
                store().query_write(
                    s.knowledge_concept__data.insert().values(**link_values)
                )
            for item in concept.get("evidence") or []:
                if item.get("document_id") in document_ids:
                    _insert_evidence(
                        network_id=network_id,
                        document_id=item["document_id"],
                        item=item,
                        concept_id=concept["id"],
                    )

        for relation in snapshot.get("relations") or []:
            store().query_write(
                s.knowledge_relation.insert().values(
                    id=relation["id"],
                    network_id=network_id,
                    key=relation["key"],
                    source_concept_id=relation["source_concept_id"],
                    target_concept_id=relation["target_concept_id"],
                    name=relation["name"],
                    description=relation.get("description"),
                    kind=relation.get("kind") or "association",
                    status=relation.get("status") or "draft",
                    confidence=float(relation.get("confidence") or 0.6),
                    source_document_id=(
                        relation.get("source_document_id")
                        if relation.get("source_document_id") in document_ids
                        else None
                    ),
                )
            )
            for item in relation.get("evidence") or []:
                if item.get("document_id") in document_ids:
                    _insert_evidence(
                        network_id=network_id,
                        document_id=item["document_id"],
                        item=item,
                        relation_id=relation["id"],
                    )

        for fact in snapshot.get("facts") or []:
            store().query_write(
                s.knowledge_fact.insert().values(
                    id=fact["id"],
                    network_id=network_id,
                    subject_concept_id=fact["subject_concept_id"],
                    relation_id=fact.get("relation_id"),
                    object_concept_id=fact.get("object_concept_id"),
                    object_text=fact.get("object_text"),
                    predicate=fact["predicate"],
                    statement=fact["statement"],
                    status=fact.get("status") or "draft",
                    confidence=float(fact.get("confidence") or 0.6),
                    source_document_id=(
                        fact.get("source_document_id")
                        if fact.get("source_document_id") in document_ids
                        else None
                    ),
                )
            )
            for item in fact.get("evidence") or []:
                if item.get("document_id") in document_ids:
                    _insert_evidence(
                        network_id=network_id,
                        document_id=item["document_id"],
                        item=item,
                        fact_id=fact["id"],
                    )

        for table, key, target in (
            (s.knowledge_action, "action_id", "actions"),
            (s.knowledge_risk, "risk_id", "risks"),
            (s.knowledge_metric, "metric_id", "metrics"),
        ):
            for item in snapshot.get(target) or []:
                values = {
                    "id": item["id"],
                    "network_id": network_id,
                    "key": item["key"],
                    "name": item["name"],
                    "description": item.get("description"),
                }
                if target == "actions":
                    values.update(
                        action_intent=item.get("action_intent") or "execute",
                        bound_concept_id=item.get("bound_concept_id"),
                        parameters=item.get("parameters") or [],
                    )
                elif target == "risks":
                    values.update(
                        severity=item.get("severity") or "medium",
                        mitigation=item.get("mitigation"),
                        related_concept_id=item.get("related_concept_id"),
                    )
                else:
                    values.update(
                        expression=item.get("expression"),
                        unit=item.get("unit"),
                        concept_id=item.get("concept_id"),
                        sql_attribute_id=item.get("sql_attribute_id"),
                        status=item.get("status") or "draft",
                        confidence=float(item.get("confidence") or 0.6),
                    )
                if target != "metrics":
                    values.update(
                        status=item.get("status") or "draft",
                        confidence=float(item.get("confidence") or 0.6),
                        source_document_id=(
                            item.get("source_document_id")
                            if item.get("source_document_id") in document_ids
                            else None
                        ),
                    )
                store().query_write(table.insert().values(**values))
                for evidence in item.get("evidence") or []:
                    if evidence.get("document_id") in document_ids:
                        _insert_evidence(
                            network_id=network_id,
                            document_id=evidence["document_id"],
                            item=evidence,
                            **{key: item["id"]},
                        )

        for group in snapshot.get("groups") or []:
            store().query_write(
                s.knowledge_concept_group.insert().values(
                    id=group["id"],
                    network_id=network_id,
                    key=group["key"],
                    name=group["name"],
                    description=group.get("description"),
                )
            )
            for member in group.get("concepts") or []:
                store().query_write(
                    s.knowledge_concept_group__concept.insert().values(
                        group_id=group["id"], concept_id=member["id"]
                    )
                )

        for capability in snapshot.get("capabilities") or []:
            store().query_write(
                s.knowledge_capability.insert().values(
                    id=capability["id"],
                    network_id=network_id,
                    key=capability["key"],
                    name=capability["name"],
                    kind=capability.get("kind") or "skill",
                    description=capability.get("description"),
                    config=capability.get("config") or {},
                    enabled=bool(capability.get("enabled", True)),
                )
            )
        for action in snapshot.get("actions") or []:
            for capability in action.get("capabilities") or []:
                if capability.get("id"):
                    store().query_write(
                        s.knowledge_action__capability.insert().values(
                            action_id=action["id"],
                            capability_id=capability["id"],
                        )
                    )

    return {
        "network_id": network_id,
        "version": version["version"],
        "restored": True,
    }
