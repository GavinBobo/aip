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
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import aliased

from all_ontology.dal import schema as s
from all_ontology.dal.session import store, write_transaction

_NETWORK_FIELDS = {
    "name",
    "description",
    "domain",
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
            "document_count": 0,
            "data_link_count": 0,
        }
        for network_id in network_ids
    }
    for key, table in (
        ("concept_count", s.knowledge_concept),
        ("relation_count", s.knowledge_relation),
        ("fact_count", s.knowledge_fact),
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


def list_networks() -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_network).order_by(
            s.knowledge_network.c.created.desc(),
            s.knowledge_network.c.name,
        )
    )
    ids = [str(row["id"]) for row in rows]
    counts = _network_counts(ids)
    return [{**row, **counts.get(str(row["id"]), {})} for row in rows]


def get_network(network_id: str) -> dict[str, Any] | None:
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
    return {**row, **_network_counts([network_id]).get(network_id, {})}


def create_network(
    *,
    name: str,
    description: str | None,
    domain: str | None,
    created_by: str | None,
) -> dict[str, Any]:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("知识网络名称不能为空。")
    existing = store().query_read(
        select(s.knowledge_network.c.id).where(
            func.lower(func.trim(s.knowledge_network.c.name)) == func.lower(trimmed)
        )
    )
    if existing:
        raise ValueError("同名知识网络已经存在。")
    row = store().query_write(
        s.knowledge_network.insert()
        .values(
            name=trimmed,
            description=(description or "").strip() or None,
            domain=(domain or "").strip() or None,
            created_by=created_by,
        )
        .returning(s.knowledge_network)
    )[0]
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
            raise ValueError("知识网络名称不能为空。")
        duplicate = store().query_read(
            select(s.knowledge_network.c.id).where(
                s.knowledge_network.c.id != network_id,
                func.lower(func.trim(s.knowledge_network.c.name)) == func.lower(name),
            )
        )
        if duplicate:
            raise ValueError("同名知识网络已经存在。")
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
    row = store().query_write(
        s.knowledge_document.insert()
        .values(
            network_id=network_id,
            run_id=run_id,
            title=title.strip() or "未命名文档",
            source_name=source_name,
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
            detail = "术语"
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
                }
            )
    return grouped


def list_concepts(network_id: str) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.knowledge_concept)
        .where(s.knowledge_concept.c.network_id == network_id)
        .order_by(s.knowledge_concept.c.name)
    )
    ids = [str(row["id"]) for row in rows]
    links = _links_for_concepts(ids)
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


def get_concept(concept_id: str) -> dict[str, Any] | None:
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
        "data_links": _links_for_concepts([concept_id]).get(concept_id, []),
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
            raise ValueError("概念名称不能为空。")
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
            raise ValueError("关系名称不能为空。")
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


def list_data_targets(query: str | None, *, limit: int = 25) -> list[dict[str, Any]]:
    pattern = f"%{(query or '').strip()}%"
    terms = store().query_read(
        select(
            s.term.c.id,
            s.term.c.name,
            s.term.c.description,
        )
        .where(s.term.c.name.ilike(pattern))
        .order_by(s.term.c.name)
        .limit(limit)
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
        .limit(limit)
    )
    targets = [
        {
            "kind": "term",
            "id": row["id"],
            "name": row["name"],
            "detail": row["description"] or "术语",
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
) -> dict[str, Any]:
    concept = get_concept(concept_id)
    if concept is None:
        raise ValueError("概念不存在。")
    if target_kind not in {"term", "table"}:
        raise ValueError("target_kind 只能是 term 或 table。")
    column = s.term.c.id if target_kind == "term" else s.catalog_table.c.id
    table = s.term if target_kind == "term" else s.catalog_table
    if not store().query_read(select(column).where(column == target_id)):
        raise ValueError("数据对象不存在。")
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
        raise ValueError("该概念已经关联了这个数据对象。")
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
        "detail": "术语" if target_kind == "term" else name,
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


def save_extraction(
    document_id: str,
    *,
    summary: str,
    concepts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    chunk_count: int,
) -> dict[str, Any]:
    """Replace one document's claims and citations in a single transaction."""
    document = get_document(document_id)
    if document is None:
        raise ValueError("知识文档不存在。")
    network_id = str(document["network_id"])

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
                _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    concept_id=concept_id,
                    evidence=evidence,
                )

        relation_ids: dict[str, str] = {}
        for relation in relations:
            source_id = concept_ids.get(str(relation["source_key"]))
            target_id = concept_ids.get(str(relation["target_key"]))
            if source_id is None or target_id is None:
                continue
            relation_id = str(
                store().query_write(
                    s.knowledge_relation.insert()
                    .values(
                        network_id=network_id,
                        key=relation["key"],
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
            relation_ids[str(relation["key"])] = relation_id
            for evidence in relation.get("evidence") or []:
                _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    relation_id=relation_id,
                    evidence=evidence,
                )

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
                _insert_evidence(
                    network_id=network_id,
                    document_id=document_id,
                    fact_id=fact_id,
                    evidence=evidence,
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

    concept_count = store().query_read(
        select(func.count())
        .select_from(s.knowledge_concept)
        .where(s.knowledge_concept.c.network_id == network_id)
    )[0]["count"]
    relation_count = store().query_read(
        select(func.count())
        .select_from(s.knowledge_relation)
        .where(s.knowledge_relation.c.network_id == network_id)
    )[0]["count"]
    fact_count = store().query_read(
        select(func.count())
        .select_from(s.knowledge_fact)
        .where(s.knowledge_fact.c.network_id == network_id)
    )[0]["count"]
    return {
        "network_id": network_id,
        "concept_count": int(concept_count),
        "relation_count": int(relation_count),
        "fact_count": int(fact_count),
    }


def _insert_evidence(
    *,
    network_id: str,
    document_id: str,
    evidence: dict[str, Any],
    concept_id: str | None = None,
    relation_id: str | None = None,
    fact_id: str | None = None,
) -> None:
    quote = str(evidence.get("quote") or "").strip()
    if not quote:
        return
    store().query_write(
        s.knowledge_evidence.insert().values(
            network_id=network_id,
            document_id=document_id,
            concept_id=concept_id,
            relation_id=relation_id,
            fact_id=fact_id,
            page=evidence.get("page"),
            block_index=evidence.get("block_index"),
            quote=quote[:4000],
        )
    )
