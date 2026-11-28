# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ERD -> data-ontology candidate API.

The route exposes two things:

* a read-only report that joins the canvas with the catalog and the compiled
  semantic layer;
* an explicit apply step for the candidates a reviewer selected.

Nothing is written by the report. Applying is intentionally a separate action:
an ERD note is a design hint, not a certification.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from all_ontology.dal import erd as erd_dal
from all_ontology.dal import schema as s
from all_ontology.dal.attributes import merge_column_attribute, merge_semantic_fk
from all_ontology.dal.session import store, write_transaction
from all_ontology.dal.terms import update_term, upsert_table_term
from all_ontology.semantic.erd_candidates import build_candidate_report
from all_ontology.server.access import require_zone, require_zone_permission
from all_ontology.server.erd.schemas import OntologyApplyRequest
from all_ontology.server.responses import (
    ErdOntologyApplyResponse,
    ErdOntologyCandidateResponse,
)
from all_ontology.dal.schema import ZONE_PERMISSION_EDIT

router = APIRouter()


def _json_values(raw: Any) -> list[Any]:
    """Decode the catalog's JSON-encoded sample/distinct value lists."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _table_ids(canvas: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(node["table_id"])
            for node in canvas.get("nodes") or []
            if node.get("table_id")
        }
    )


def _load_tables(table_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not table_ids:
        return {}
    rows = store().query_read(
        select(
            s.catalog_table.c.id,
            s.catalog_table.c.name.label("table_name"),
            s.catalog_table.c.description,
            s.catalog_table.c.description_certified,
            s.catalog_table.c.pk,
            s.catalog_table.c.table_type,
            s.catalog_table.c.is_junction_table,
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
        .where(s.catalog_table.c.id.in_(table_ids))
    )
    tables = {
        str(row["id"]): {
            **dict(row),
            "columns": [],
            "term": None,
            "column_attribute_count": 0,
            "semantic_fk_count": 0,
        }
        for row in rows
    }
    if not tables:
        return tables

    for row in store().query_read(
        select(
            s.catalog_column.c.id,
            s.catalog_column.c.table_id,
            s.catalog_column.c.name,
            s.catalog_column.c.description,
            s.catalog_column.c.description_certified,
            s.catalog_column.c.data_type,
            s.catalog_column.c.sample_values,
            s.catalog_column.c.distinct_values,
            s.catalog_column.c.is_unique,
            s.catalog_column.c.distinct_ratio,
            s.catalog_column.c.is_nullable,
            s.catalog_column.c.ordinal_position,
        )
        .where(s.catalog_column.c.table_id.in_(table_ids))
        .order_by(
            s.catalog_column.c.table_id,
            s.catalog_column.c.ordinal_position.nulls_last(),
            s.catalog_column.c.name,
        )
    ):
        table = tables.get(str(row["table_id"]))
        if table is None:
            continue
        table["columns"].append(
            {
                **dict(row),
                "sample_values": _json_values(row["sample_values"]),
                "distinct_values": _json_values(row["distinct_values"]),
            }
        )

    for row in store().query_read(
        select(
            s.table__term.c.table_id,
            s.term.c.id,
            s.term.c.name,
            s.term.c.description,
            s.term.c.name_certified,
            s.term.c.description_certified,
        )
        .select_from(
            s.table__term.join(s.term, s.term.c.id == s.table__term.c.term_id)
        )
        .where(s.table__term.c.table_id.in_(table_ids))
        .order_by(s.table__term.c.table_id, s.term.c.id)
    ):
        table = tables.get(str(row["table_id"]))
        if table is not None and table["term"] is None:
            table["term"] = {**dict(row), "exists": True}

    for row in store().query_read(
        select(
            s.column_attribute.c.table_id,
            func.count().label("count"),
        )
        .where(s.column_attribute.c.table_id.in_(table_ids))
        .group_by(s.column_attribute.c.table_id)
    ):
        table = tables.get(str(row["table_id"]))
        if table is not None:
            table["column_attribute_count"] = int(row["count"] or 0)

    source_column = aliased(s.catalog_column)
    for row in store().query_read(
        select(
            source_column.c.table_id,
            func.count().label("count"),
        )
        .select_from(
            s.column__semantic_fk.join(
                source_column,
                source_column.c.id == s.column__semantic_fk.c.column_id,
            )
        )
        .where(source_column.c.table_id.in_(table_ids))
        .group_by(source_column.c.table_id)
    ):
        table = tables.get(str(row["table_id"]))
        if table is not None:
            table["semantic_fk_count"] = int(row["count"] or 0)
    return tables


def _load_catalog_fks(table_ids: list[str]) -> list[dict[str, Any]]:
    if not table_ids:
        return []
    source = aliased(s.catalog_column)
    target = aliased(s.catalog_column)
    rows = store().query_read(
        select(
            source.c.id.label("source_column_id"),
            source.c.table_id.label("source_table_id"),
            source.c.name.label("source_column"),
            target.c.id.label("target_column_id"),
            target.c.table_id.label("target_table_id"),
            target.c.name.label("target_column"),
        )
        .select_from(
            s.column__foreign_key.join(
                source, source.c.id == s.column__foreign_key.c.source_column_id
            ).join(
                target, target.c.id == s.column__foreign_key.c.target_column_id
            )
        )
        .where(
            source.c.table_id.in_(table_ids),
            target.c.table_id.in_(table_ids),
        )
        .order_by(
            source.c.table_id,
            source.c.name,
            target.c.table_id,
            target.c.name,
        )
    )
    return [dict(row) for row in rows]


def _load_semantic_fks(table_ids: list[str]) -> list[dict[str, Any]]:
    if not table_ids:
        return []
    source = aliased(s.catalog_column)
    rows = store().query_read(
        select(
            s.column__semantic_fk.c.column_id.label("source_column_id"),
            source.c.table_id.label("source_table_id"),
            source.c.name.label("source_column"),
            s.column__semantic_fk.c.attribute_id,
            s.column_attribute.c.table_id.label("target_table_id"),
            s.column_attribute.c.source_column.label("target_column"),
        )
        .select_from(
            s.column__semantic_fk.join(
                source, source.c.id == s.column__semantic_fk.c.column_id
            ).join(
                s.column_attribute,
                s.column_attribute.c.id == s.column__semantic_fk.c.attribute_id,
            )
        )
        .where(source.c.table_id.in_(table_ids))
    )
    return [dict(row) for row in rows]


def build_report(zone_id: str) -> dict[str, Any] | None:
    """Build the full candidate report for one zone's ER canvas."""
    canvas = erd_dal.get_or_create_canvas(zone_id)
    if canvas is None:
        return None
    table_ids = _table_ids(canvas)
    report = build_candidate_report(
        canvas,
        _load_tables(table_ids),
        catalog_fks=_load_catalog_fks(table_ids),
        semantic_fks=_load_semantic_fks(table_ids),
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report


def _entity_by_table(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entity["table_id"]): entity
        for entity in report.get("entities") or []
        if entity.get("table_id")
    }


def _entity_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entity["id"]): entity for entity in report.get("entities") or []}


def _relationship_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(relationship["id"]): relationship
        for relationship in report.get("relationships") or []
    }


def apply_candidates(
    zone_id: str,
    body: OntologyApplyRequest,
) -> dict[str, Any]:
    """Apply selected candidates, in the semantic layer, as one transaction.

    Terms are only created when they do not exist. An existing Term with an
    empty description may receive the ERD/catalog description; a curated
    description is never overwritten. Relationships become SEMANTIC_FK edges
    only when both endpoints are catalog-bound and the selected candidate
    passed the blocking checks.
    """
    report = build_report(zone_id)
    if report is None:
        raise ValueError("Canvas not found.")
    entities_by_id = _entity_by_id(report)
    entities_by_table = _entity_by_table(report)
    relationships_by_id = _relationship_by_id(report)
    table_ids = sorted(entities_by_table)
    tables = _load_tables(table_ids)
    term_by_table: dict[str, dict[str, Any]] = {
        table_id: entity["term"]
        for table_id, entity in entities_by_table.items()
        if entity.get("term")
    }

    result: dict[str, Any] = {
        "terms_created": [],
        "terms_updated": [],
        "terms_reused": [],
        "semantic_fks_created": [],
        "skipped": [],
        "errors": [],
    }

    with write_transaction():
        for node_id in body.entity_node_ids:
            entity = entities_by_id.get(node_id)
            if entity is None:
                result["skipped"].append(
                    {"id": node_id, "reason": "candidate_not_found"}
                )
                continue
            table_id = entity.get("table_id")
            if not table_id:
                result["skipped"].append(
                    {"id": node_id, "reason": "virtual_table"}
                )
                continue
            existing = term_by_table.get(str(table_id))
            if existing:
                proposed_description = str(
                    (entity.get("proposed_term") or {}).get("description") or ""
                ).strip()
                if not str(existing.get("description") or "").strip() and proposed_description:
                    updated = update_term(
                        str(existing["id"]),
                        description=proposed_description,
                        modified_by=None,
                        touch=False,
                    )
                    if updated is not None:
                        term_by_table[str(table_id)] = {
                            **existing,
                            "description": proposed_description,
                        }
                        result["terms_updated"].append(
                            {
                                "table_id": table_id,
                                "term_id": str(existing["id"]),
                                "name": existing.get("name"),
                            }
                        )
                else:
                    result["terms_reused"].append(
                        {
                            "table_id": table_id,
                            "term_id": str(existing["id"]),
                            "name": existing.get("name"),
                        }
                    )
                continue
            if not body.create_terms:
                result["skipped"].append(
                    {"id": node_id, "reason": "term_creation_disabled"}
                )
                continue
            proposed = entity.get("proposed_term") or {}
            created = upsert_table_term(
                name=str(proposed.get("name") or "").strip(),
                description=str(proposed.get("description") or "").strip(),
                table_id=str(table_id),
                synonyms=list(proposed.get("synonyms") or []),
            )
            if created is None:
                result["errors"].append(
                    {"id": node_id, "reason": "term_creation_failed"}
                )
                continue
            term_id, term_name = created
            term_by_table[str(table_id)] = {
                "id": term_id,
                "name": term_name,
                "description": str(proposed.get("description") or "").strip(),
            }
            result["terms_created"].append(
                {"table_id": table_id, "term_id": term_id, "name": term_name}
            )

        if not body.create_semantic_fks:
            return result

        for relationship_id in body.relationship_ids:
            relationship = relationships_by_id.get(relationship_id)
            if relationship is None:
                result["skipped"].append(
                    {"id": relationship_id, "reason": "candidate_not_found"}
                )
                continue
            if relationship.get("status") in {"invalid", "logical_only"}:
                result["skipped"].append(
                    {
                        "id": relationship_id,
                        "reason": f"relationship_{relationship.get('status')}",
                    }
                )
                continue
            apply = relationship.get("apply") or {}
            referencing_table_id = str(apply.get("referencing_table_id") or "")
            referenced_table_id = str(apply.get("referenced_table_id") or "")
            if not referencing_table_id or not referenced_table_id:
                result["skipped"].append(
                    {"id": relationship_id, "reason": "relationship_not_mapped"}
                )
                continue
            referenced_entity = entities_by_table.get(referenced_table_id)
            referencing_entity = entities_by_table.get(referencing_table_id)
            if referenced_entity is None or referencing_entity is None:
                result["skipped"].append(
                    {"id": relationship_id, "reason": "relationship_table_missing"}
                )
                continue
            referenced_term = term_by_table.get(referenced_table_id)
            if referenced_term is None:
                if not body.create_terms:
                    result["skipped"].append(
                        {
                            "id": relationship_id,
                            "reason": "referenced_table_has_no_term",
                        }
                    )
                    continue
                proposed = referenced_entity.get("proposed_term") or {}
                created = upsert_table_term(
                    name=str(proposed.get("name") or "").strip(),
                    description=str(proposed.get("description") or "").strip(),
                    table_id=referenced_table_id,
                    synonyms=list(proposed.get("synonyms") or []),
                )
                if created is None:
                    result["errors"].append(
                        {
                            "id": relationship_id,
                            "reason": "referenced_term_creation_failed",
                        }
                    )
                    continue
                term_id, term_name = created
                referenced_term = {
                    "id": term_id,
                    "name": term_name,
                    "description": str(proposed.get("description") or "").strip(),
                }
                term_by_table[referenced_table_id] = referenced_term
                result["terms_created"].append(
                    {
                        "table_id": referenced_table_id,
                        "term_id": term_id,
                        "name": term_name,
                    }
                )
            referenced_table = tables.get(referenced_table_id) or {}
            referencing_table = tables.get(referencing_table_id) or {}
            referencing_columns = {
                str(column.get("name")): column
                for column in referencing_table.get("columns") or []
            }
            referenced_columns = {
                str(column.get("name")): column
                for column in referenced_table.get("columns") or []
            }
            applied_pairs = 0
            for index in range(
                min(
                    len(apply.get("referencing_columns") or []),
                    len(apply.get("referenced_columns") or []),
                )
            ):
                referencing_name = str(apply["referencing_columns"][index])
                referenced_name = str(apply["referenced_columns"][index])
                referencing_column = referencing_columns.get(referencing_name)
                referenced_column = referenced_columns.get(referenced_name)
                if referencing_column is None or referenced_column is None:
                    result["errors"].append(
                        {
                            "id": relationship_id,
                            "reason": "relationship_column_missing",
                            "column": referencing_name
                            if referencing_column is None
                            else referenced_name,
                        }
                    )
                    continue
                attribute_id = merge_column_attribute(
                    term_name=str(referenced_term["name"]),
                    table_id=referenced_table_id,
                    source_column=referenced_name,
                    attr_name=referenced_name,
                    datatype=str(referenced_column.get("data_type") or ""),
                    description=referenced_column.get("description"),
                )
                if attribute_id is None:
                    result["errors"].append(
                        {
                            "id": relationship_id,
                            "reason": "attribute_creation_failed",
                            "column": referenced_name,
                        }
                    )
                    continue
                created_fk = merge_semantic_fk(
                    str(referencing_column["id"]), attribute_id
                )
                if not created_fk:
                    result["errors"].append(
                        {
                            "id": relationship_id,
                            "reason": "semantic_fk_refused",
                            "column": referencing_name,
                        }
                    )
                    continue
                applied_pairs += 1
                result["semantic_fks_created"].append(
                    {
                        "relationship_id": relationship_id,
                        "source_table_id": referencing_table_id,
                        "source_column": referencing_name,
                        "target_table_id": referenced_table_id,
                        "target_column": referenced_name,
                        "attribute_id": attribute_id,
                    }
                )
            if applied_pairs == 0:
                result["skipped"].append(
                    {"id": relationship_id, "reason": "no_pair_applied"}
                )

    return result


@router.get(
    "/erd/canvases/{zone_id}/ontology-candidates",
    response_model=ErdOntologyCandidateResponse,
)
def get_ontology_candidates(zone_id: str) -> dict[str, Any]:
    """Return a read-only data-ontology proposal for the zone's ER canvas."""
    require_zone(zone_id)
    report = build_report(zone_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Canvas not found.")
    return {"data": report}


@router.post(
    "/erd/canvases/{zone_id}/ontology-candidates/apply",
    response_model=ErdOntologyApplyResponse,
)
def apply_ontology_candidates(
    zone_id: str, body: OntologyApplyRequest
) -> dict[str, Any]:
    """Apply selected candidates to the semantic layer."""
    require_zone_permission(zone_id, ZONE_PERMISSION_EDIT)
    try:
        result = apply_candidates(zone_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": result}
