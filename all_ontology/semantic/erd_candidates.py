# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build data-ontology candidates from an ER canvas.

The ER canvas is a *logical* model: it records what a modeller intends the
database to mean. The catalog is the *physical* model: it records what the
database actually contains. Neither is a data ontology on its own.

This module joins the two and produces a reviewable proposal:

* entity candidates, with the grain and semantic role implied by the ERD;
* relationship candidates, with the FK direction implied by cardinality;
* physical checks (declared FK, type compatibility, target uniqueness,
  sampled-value overlap);
* gaps where the drawing and the catalog disagree.

It is deliberately pure. The server loads the catalog and semantic context and
passes plain dicts in; tests can exercise the analysis without a database.
"""

from __future__ import annotations

import re
from typing import Any

_ROLE_ALIASES = {
    "fact": "fact",
    "事实": "fact",
    "事实表": "fact",
    "dimension": "dimension",
    "dim": "dimension",
    "维度": "dimension",
    "维度表": "dimension",
    "bridge": "bridge",
    "junction": "bridge",
    "关联": "bridge",
    "关联表": "bridge",
    "staging": "staging",
    "stage": "staging",
    "stg": "staging",
    "暂存": "staging",
    "lookup": "lookup",
    "字典": "lookup",
    "码表": "lookup",
}

_PII_HINTS = (
    "email",
    "phone",
    "mobile",
    "address",
    "ssn",
    "social_security",
    "tax_id",
    "passport",
    "bank_account",
    "card_number",
    "id_card",
)

_MEASURE_HINTS = (
    "amount",
    "price",
    "cost",
    "total",
    "subtotal",
    "qty",
    "quantity",
    "count",
    "balance",
    "revenue",
    "profit",
    "score",
    "rate",
    "ratio",
    "percent",
)

_TEMPORAL_HINTS = ("date", "time", "timestamp", "created", "updated", "deleted")


def humanize_identifier(value: str) -> str:
    """A display name for a table/column, preserving CJK text."""
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    text = re.sub(r"[_\-]+", " ", text).strip()
    return " ".join(part.capitalize() for part in text.split())


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique(values: list[Any], *, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _table_name(table: dict[str, Any] | None, node: dict[str, Any]) -> str:
    if table and table.get("table_name"):
        return str(table["table_name"])
    return str(node.get("name") or "").split(".")[-1]


def _qualified_name(table: dict[str, Any] | None, node: dict[str, Any]) -> str:
    if table:
        parts = [
            table.get("database_name"),
            table.get("schema_name"),
            table.get("table_name"),
        ]
        qualified = ".".join(str(part) for part in parts if part)
        if qualified:
            return qualified
    return str(node.get("name") or "")


def _type_family(data_type: str | None) -> str:
    text = str(data_type or "").lower()
    if not text:
        return "unknown"
    if any(
        token in text
        for token in (
            "int",
            "serial",
            "numeric",
            "decimal",
            "number",
            "float",
            "double",
            "real",
            "money",
        )
    ):
        return "number"
    if any(
        token in text
        for token in ("char", "text", "string", "varchar", "nvarchar", "clob")
    ):
        return "text"
    if any(token in text for token in ("date", "time", "timestamp")):
        return "temporal"
    if "bool" in text:
        return "boolean"
    if "uuid" in text or "uniqueidentifier" in text:
        return "uuid"
    if any(token in text for token in ("json", "variant", "object", "array")):
        return "semi_structured"
    return "unknown"


def _value_set(column: dict[str, Any]) -> set[str]:
    values = [
        *_as_list(column.get("sample_values")),
        *_as_list(column.get("distinct_values")),
    ]
    return {
        str(value).strip().casefold()
        for value in values
        if value is not None and str(value).strip()
    }


def _column_hint(column: dict[str, Any]) -> str:
    name = str(column.get("name") or "").lower()
    data_type = str(column.get("data_type") or "").lower()
    if column.get("is_primary_key"):
        return "primary_key"
    if column.get("is_unique") or float(column.get("distinct_ratio") or 0) >= 0.99:
        return "unique_key"
    if name == "id" or name.endswith("_id") or name.endswith("id"):
        return "foreign_key"
    if any(token in name for token in _TEMPORAL_HINTS) or "date" in data_type:
        return "temporal"
    if any(token in name for token in _MEASURE_HINTS):
        return "measure"
    if any(
        token in name
        for token in ("status", "state", "type", "category", "kind", "code", "level")
    ):
        return "dimension"
    if any(token in data_type for token in ("char", "text", "string")):
        return "text"
    return "attribute"


def _sensitivity_hint(column: dict[str, Any]) -> str | None:
    haystack = " ".join(
        [
            str(column.get("name") or ""),
            str(column.get("description") or ""),
        ]
    ).lower()
    if any(token in haystack for token in _PII_HINTS):
        return "possible_pii"
    return None


def _role_from_category(category: str | None) -> str | None:
    text = str(category or "").strip().casefold()
    return _ROLE_ALIASES.get(text)


def _infer_role(
    node: dict[str, Any],
    table: dict[str, Any] | None,
    *,
    fk_count: int,
    primary_keys: list[str],
) -> str:
    category_role = _role_from_category(node.get("category"))
    if category_role:
        return category_role
    name = _table_name(table, node).casefold()
    if name.startswith(("fact_", "f_", "fct_")):
        return "fact"
    if name.startswith(("dim_", "d_", "dimension_")):
        return "dimension"
    if name.startswith(("stg_", "stage_", "staging_", "tmp_")):
        return "staging"
    if table and table.get("is_junction_table"):
        return "bridge"
    if fk_count >= 2 and len(primary_keys) >= 2:
        return "bridge"
    if fk_count >= 2:
        return "fact"
    if fk_count == 1:
        return "dimension"
    return "unknown"


def _orientation(cardinality: str) -> tuple[str | None, str | None, bool]:
    """Return ``(referencing side, referenced side, unique)``.

    The sides are ``"source"`` / ``"target"`` as drawn. A many-to-many
    relationship has no single FK owner; it needs a junction table.
    """
    if cardinality == "many-to-one":
        return "source", "target", False
    if cardinality == "one-to-many":
        return "target", "source", False
    if cardinality == "one-to-one":
        return "source", "target", True
    return None, None, False


def _entity_by_node(canvas: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in canvas.get("nodes") or []}


def _node_columns(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(column.get("name")): column
        for column in node.get("columns") or []
        if isinstance(column, dict) and column.get("name")
    }


def _entity_warnings(
    *,
    node: dict[str, Any],
    table: dict[str, Any] | None,
    term: dict[str, Any] | None,
    columns: list[dict[str, Any]],
    primary_keys: list[str],
    description: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    if table is None:
        warnings.append(
            {
                "code": "virtual_table",
                "severity": "warning",
                "message": "This table exists only on the canvas and cannot be queried until it is bound to a catalog table.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    if term is None:
        warnings.append(
            {
                "code": "missing_term",
                "severity": "warning",
                "message": "No semantic Term is linked to this table yet.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    elif not str(term.get("description") or "").strip():
        warnings.append(
            {
                "code": "term_missing_description",
                "severity": "info",
                "message": "The Term exists but has no business description.",
                "params": {"term": str(term.get("name") or "")},
            }
        )
    if not description.strip():
        warnings.append(
            {
                "code": "table_missing_description",
                "severity": "info",
                "message": "Neither the catalog description nor the ERD note explains what this table represents.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    if not primary_keys:
        warnings.append(
            {
                "code": "table_missing_primary_key",
                "severity": "warning",
                "message": "No primary key is available, so the row grain is unknown.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    if not columns:
        warnings.append(
            {
                "code": "table_missing_columns",
                "severity": "error",
                "message": "This table has no columns to model.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    if not str(node.get("category") or "").strip():
        warnings.append(
            {
                "code": "category_missing",
                "severity": "info",
                "message": "The ERD has no table category; the semantic role was inferred.",
                "params": {"table": _qualified_name(table, node)},
            }
        )
    possible_pii = [
        str(column["name"])
        for column in columns
        if _sensitivity_hint(column) == "possible_pii"
    ]
    if possible_pii:
        warnings.append(
            {
                "code": "possible_pii",
                "severity": "info",
                "message": "Some columns look like they may contain personal data; verify their PII tags.",
                "params": {"columns": ", ".join(possible_pii[:8])},
            }
        )
    return warnings


def _relationship_warnings(
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    source_table: dict[str, Any] | None,
    target_table: dict[str, Any] | None,
    cardinality: str,
    source_columns: list[str],
    target_columns: list[str],
    source_catalog_columns: dict[str, dict[str, Any]],
    target_catalog_columns: dict[str, dict[str, Any]],
    actual_fk: bool,
    type_compatible: bool | None,
    target_unique: bool | None,
    value_overlap: float | None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if source_table is None or target_table is None:
        warnings.append(
            {
                "code": "relationship_virtual_endpoint",
                "severity": "warning",
                "message": "At least one endpoint is a diagram-only table, so this relationship cannot be applied to the catalog.",
                "params": {
                    "source": _qualified_name(source_table, source),
                    "target": _qualified_name(target_table, target),
                },
            }
        )
    if cardinality == "many-to-many":
        warnings.append(
            {
                "code": "relationship_many_to_many",
                "severity": "warning",
                "message": "A many-to-many relationship needs a junction table before it can become a semantic foreign key.",
                "params": {},
            }
        )
    if not source_columns or not target_columns:
        warnings.append(
            {
                "code": "relationship_missing_columns",
                "severity": "warning",
                "message": "The relationship does not name a column pair, so there is nothing to validate.",
                "params": {},
            }
        )
        return warnings
    if len(source_columns) > 1 or len(target_columns) > 1:
        warnings.append(
            {
                "code": "relationship_composite_key",
                "severity": "info",
                "message": "Composite key pairs are reviewed as one relationship but applied as individual semantic FK edges; verify the join semantics.",
                "params": {},
            }
        )
    missing = [
        name for name in source_columns if name not in source_catalog_columns
    ] + [name for name in target_columns if name not in target_catalog_columns]
    if missing:
        warnings.append(
            {
                "code": "relationship_missing_columns_in_catalog",
                "severity": "error",
                "message": "The relationship names columns that do not exist on the mapped tables.",
                "params": {"columns": ", ".join(_unique(missing))},
            }
        )
    if type_compatible is False:
        warnings.append(
            {
                "code": "relationship_type_mismatch",
                "severity": "warning",
                "message": "The two sides of the relationship have incompatible data types.",
                "params": {},
            }
        )
    if target_unique is False:
        warnings.append(
            {
                "code": "relationship_target_not_unique",
                "severity": "warning",
                "message": "The referenced columns are not a primary or unique key, so the join may multiply rows.",
                "params": {},
            }
        )
    if not actual_fk:
        warnings.append(
            {
                "code": "relationship_not_declared",
                "severity": "info",
                "message": "The catalog does not declare this foreign key; it is currently an ERD-only relationship.",
                "params": {},
            }
        )
    if value_overlap is None:
        warnings.append(
            {
                "code": "relationship_not_profiled",
                "severity": "info",
                "message": "No sampled values are available to check whether the key values overlap.",
                "params": {},
            }
        )
    elif value_overlap <= 0:
        warnings.append(
            {
                "code": "relationship_value_overlap_empty",
                "severity": "warning",
                "message": "The sampled values on the two sides do not overlap.",
                "params": {},
            }
        )
    return warnings


def build_candidate_report(
    canvas: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    *,
    catalog_fks: list[dict[str, Any]] | None = None,
    semantic_fks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a reviewable data-ontology proposal for one ER canvas."""
    nodes = [node for node in canvas.get("nodes") or [] if isinstance(node, dict)]
    relationships = [
        relationship
        for relationship in canvas.get("relationships") or []
        if isinstance(relationship, dict)
    ]
    by_node = _entity_by_node(canvas)
    catalog_fks = catalog_fks or []
    semantic_fks = semantic_fks or []

    fk_count_by_table: dict[str, int] = {}
    for fk in catalog_fks:
        source_table_id = str(fk.get("source_table_id") or "")
        target_table_id = str(fk.get("target_table_id") or "")
        if source_table_id:
            fk_count_by_table[source_table_id] = (
                fk_count_by_table.get(source_table_id, 0) + 1
            )
        if target_table_id and target_table_id != source_table_id:
            fk_count_by_table[target_table_id] = (
                fk_count_by_table.get(target_table_id, 0) + 1
            )

    entity_rows: list[dict[str, Any]] = []
    node_table_ids: dict[str, str] = {}
    for node in nodes:
        table_id = str(node.get("table_id") or "")
        if table_id:
            node_table_ids[str(node["id"])] = table_id
        table = tables.get(table_id) if table_id else None
        catalog_columns = {
            str(column.get("name")): column
            for column in (table or {}).get("columns") or []
            if isinstance(column, dict) and column.get("name")
        }
        node_columns = [
            column for column in node.get("columns") or [] if isinstance(column, dict)
        ]
        columns: list[dict[str, Any]] = []
        for column in node_columns:
            name = str(column.get("name") or "")
            physical = dict(catalog_columns.get(name) or {})
            merged = {**physical, **column}
            merged["name"] = name
            merged["semantic_hint"] = _column_hint(merged)
            merged["sensitivity_hint"] = _sensitivity_hint(merged)
            merged["is_foreign_key_candidate"] = merged["semantic_hint"] in {
                "foreign_key",
                "primary_key",
                "unique_key",
            } and name.lower().endswith("id")
            columns.append(merged)
        primary_keys = [
            str(column["name"])
            for column in columns
            if column.get("is_primary_key")
        ]
        if not primary_keys:
            primary_keys = [
                str(name) for name in (table or {}).get("pk") or [] if str(name)
            ]
        table_name = _table_name(table, node)
        description = str(
            (table or {}).get("description") or node.get("note") or ""
        ).strip()
        term = (table or {}).get("term") or None
        role = _infer_role(
            node,
            table,
            fk_count=fk_count_by_table.get(table_id, 0),
            primary_keys=primary_keys,
        )
        warnings = _entity_warnings(
            node=node,
            table=table,
            term=term,
            columns=columns,
            primary_keys=primary_keys,
            description=description,
        )
        proposed_name = humanize_identifier(table_name)
        synonyms = _unique(
            [
                table_name,
                f"{table_name}s" if table_name and not table_name.endswith("s") else "",
                humanize_identifier(table_name),
            ]
        )
        confidence = 0.3
        if table is not None:
            confidence += 0.3
        if term is not None:
            confidence += 0.15
        if description:
            confidence += 0.1
        if primary_keys:
            confidence += 0.1
        if node.get("category"):
            confidence += 0.05
        if table is None:
            confidence = min(confidence, 0.2)
        confidence = round(min(0.99, confidence), 2)
        status = (
            "virtual"
            if table is None
            else "existing"
            if term is not None
            else "ready"
            if description and primary_keys
            else "needs_review"
        )
        entity_rows.append(
            {
                "id": str(node["id"]),
                "table_id": table_id or None,
                "name": _qualified_name(table, node),
                "table_name": table_name,
                "database_name": (table or {}).get("database_name"),
                "schema_name": (table or {}).get("schema_name"),
                "category": node.get("category"),
                "semantic_role": role,
                "status": status,
                "confidence": confidence,
                "description": description,
                "simulated": table is None,
                "primary_keys": primary_keys,
                "grain": {
                    "columns": primary_keys,
                    "confidence": "high"
                    if primary_keys
                    else "low"
                    if columns
                    else "unknown",
                },
                "columns": columns,
                "term": term,
                "existing_column_attributes": int(
                    (table or {}).get("column_attribute_count") or 0
                ),
                "existing_semantic_fks": int(
                    (table or {}).get("semantic_fk_count") or 0
                ),
                "proposed_term": {
                    "name": proposed_name,
                    "description": description,
                    "synonyms": synonyms,
                },
                "warnings": warnings,
                "signals": [
                    signal
                    for signal in (
                        f"ERD category: {node.get('category')}"
                        if node.get("category")
                        else "",
                        f"Primary key: {', '.join(primary_keys)}"
                        if primary_keys
                        else "",
                        "Catalog-bound"
                        if table is not None
                        else "Diagram-only",
                        "Existing Term" if term is not None else "",
                    )
                    if signal
                ],
                "apply": {
                    "can_apply": table is not None
                    and (
                        term is None
                        or (
                            not str((term or {}).get("description") or "").strip()
                            and bool(description.strip())
                        )
                    ),
                    "term_name": proposed_name,
                    "description": description,
                    "synonyms": synonyms,
                },
            }
        )

    relationship_rows: list[dict[str, Any]] = []
    for relationship in relationships:
        source = by_node.get(str(relationship.get("source_node_id")))
        target = by_node.get(str(relationship.get("target_node_id")))
        if source is None or target is None:
            continue
        source_table_id = str(source.get("table_id") or "")
        target_table_id = str(target.get("table_id") or "")
        source_table = tables.get(source_table_id) if source_table_id else None
        target_table = tables.get(target_table_id) if target_table_id else None
        source_catalog_columns = {
            str(column.get("name")): column
            for column in (source_table or {}).get("columns") or []
            if isinstance(column, dict) and column.get("name")
        }
        target_catalog_columns = {
            str(column.get("name")): column
            for column in (target_table or {}).get("columns") or []
            if isinstance(column, dict) and column.get("name")
        }
        source_columns = [str(name) for name in relationship.get("source_columns") or []]
        target_columns = [str(name) for name in relationship.get("target_columns") or []]
        cardinality = str(relationship.get("cardinality") or "many-to-one")
        referencing_side, referenced_side, unique = _orientation(cardinality)
        referencing_table_id = (
            source_table_id
            if referencing_side == "source"
            else target_table_id
            if referencing_side == "target"
            else ""
        )
        referenced_table_id = (
            target_table_id
            if referenced_side == "target"
            else source_table_id
            if referenced_side == "source"
            else ""
        )
        referencing_columns = (
            source_columns if referencing_side == "source" else target_columns
        )
        referenced_columns = (
            target_columns if referenced_side == "target" else source_columns
        )
        referencing_catalog_columns = (
            source_catalog_columns
            if referencing_side == "source"
            else target_catalog_columns
        )
        referenced_catalog_columns = (
            target_catalog_columns
            if referenced_side == "target"
            else source_catalog_columns
        )
        actual_fk = any(
            str(fk.get("source_table_id") or "") == referencing_table_id
            and str(fk.get("target_table_id") or "") == referenced_table_id
            and str(fk.get("source_column") or "") == referencing_columns[index]
            and str(fk.get("target_column") or "") == referenced_columns[index]
            for fk in catalog_fks
            for index in range(min(len(referencing_columns), len(referenced_columns)))
        )
        type_compatible: bool | None = None
        type_pairs: list[dict[str, str]] = []
        for index in range(min(len(referencing_columns), len(referenced_columns))):
            source_name = referencing_columns[index]
            target_name = referenced_columns[index]
            source_column = referencing_catalog_columns.get(source_name) or {}
            target_column = referenced_catalog_columns.get(target_name) or {}
            source_family = _type_family(source_column.get("data_type"))
            target_family = _type_family(target_column.get("data_type"))
            type_pairs.append(
                {
                    "source": source_name,
                    "target": target_name,
                    "source_family": source_family,
                    "target_family": target_family,
                }
            )
            if source_family != "unknown" and target_family != "unknown":
                compatible = source_family == target_family
                type_compatible = (
                    compatible
                    if type_compatible is None
                    else type_compatible and compatible
                )
        target_unique: bool | None = None
        for name in referenced_columns:
            column = referenced_catalog_columns.get(name) or {}
            is_key = bool(
                column.get("is_primary_key")
                or column.get("is_unique")
                or float(column.get("distinct_ratio") or 0) >= 0.99
            )
            target_unique = is_key if target_unique is None else target_unique and is_key
        value_overlap: float | None = None
        for index in range(min(len(referencing_columns), len(referenced_columns))):
            source_values = _value_set(
                referencing_catalog_columns.get(referencing_columns[index]) or {}
            )
            target_values = _value_set(
                referenced_catalog_columns.get(referenced_columns[index]) or {}
            )
            if source_values and target_values:
                ratio = len(source_values & target_values) / len(source_values)
                value_overlap = (
                    ratio
                    if value_overlap is None
                    else min(value_overlap, ratio)
                )
        warnings = _relationship_warnings(
            source=source,
            target=target,
            source_table=source_table,
            target_table=target_table,
            cardinality=cardinality,
            source_columns=source_columns,
            target_columns=target_columns,
            source_catalog_columns=source_catalog_columns,
            target_catalog_columns=target_catalog_columns,
            actual_fk=actual_fk,
            type_compatible=type_compatible,
            target_unique=target_unique,
            value_overlap=value_overlap,
        )
        blocking = any(
            warning.get("severity") == "error" for warning in warnings
        ) or (
            source_table is None
            or target_table is None
            or cardinality == "many-to-many"
            or not source_columns
            or not target_columns
        )
        if blocking:
            status = (
                "logical_only"
                if source_table is None
                or target_table is None
                or cardinality == "many-to-many"
                or not source_columns
                or not target_columns
                else "invalid"
            )
        elif actual_fk and type_compatible is not False and target_unique is not False:
            status = "validated"
        elif actual_fk:
            status = "declared"
        elif type_compatible is not False and target_unique is not False:
            status = "probable"
        else:
            status = "needs_review"
        confidence = 0.3
        if source_table is not None and target_table is not None:
            confidence += 0.2
        if source_columns and target_columns:
            confidence += 0.2
        if type_compatible is True:
            confidence += 0.1
        if target_unique is True:
            confidence += 0.1
        if actual_fk:
            confidence += 0.15
        elif value_overlap is not None and value_overlap >= 0.5:
            confidence += 0.1
        confidence = round(min(0.99, confidence), 2)
        relationship_rows.append(
            {
                "id": str(relationship["id"]),
                "label": relationship.get("label"),
                "source_node_id": str(source["id"]),
                "target_node_id": str(target["id"]),
                "source_table": _qualified_name(source_table, source),
                "target_table": _qualified_name(target_table, target),
                "source_columns": source_columns,
                "target_columns": target_columns,
                "cardinality": cardinality,
                "referencing_table": _qualified_name(
                    source_table if referencing_side == "source" else target_table,
                    source if referencing_side == "source" else target,
                ),
                "referenced_table": _qualified_name(
                    target_table if referenced_side == "target" else source_table,
                    target if referenced_side == "target" else source,
                ),
                "referencing_columns": referencing_columns,
                "referenced_columns": referenced_columns,
                "status": status,
                "confidence": confidence,
                "unique": unique,
                "checks": {
                    "catalog_fk": actual_fk,
                    "type_compatible": type_compatible,
                    "target_unique": target_unique,
                    "value_overlap": value_overlap,
                    "type_pairs": type_pairs,
                },
                "existing_semantic_fk": any(
                    (
                        str(semantic_fk.get("source_table_id") or ""),
                        str(semantic_fk.get("target_table_id") or ""),
                        str(semantic_fk.get("target_column") or ""),
                    )
                    == (referencing_table_id, referenced_table_id, referenced_columns[index])
                    for semantic_fk in semantic_fks
                    for index in range(
                        min(len(referencing_columns), len(referenced_columns))
                    )
                ),
                "warnings": warnings,
                "apply": {
                    "can_apply": status
                    in {"validated", "declared", "probable", "needs_review"},
                    "referencing_table_id": referencing_table_id or None,
                    "referenced_table_id": referenced_table_id or None,
                    "referencing_columns": referencing_columns,
                    "referenced_columns": referenced_columns,
                    "unique": unique,
                },
            }
        )

    drawn_catalog_pairs: set[tuple[str, str]] = set()
    for relationship in relationship_rows:
        apply = relationship.get("apply") or {}
        referencing_table_id = apply.get("referencing_table_id")
        referenced_table_id = apply.get("referenced_table_id")
        for index in range(
            min(
                len(apply.get("referencing_columns") or []),
                len(apply.get("referenced_columns") or []),
            )
        ):
            drawn_catalog_pairs.add(
                (
                    str(referencing_table_id),
                    str(referenced_table_id),
                    str(apply["referencing_columns"][index]),
                    str(apply["referenced_columns"][index]),
                )
            )
    catalog_fks_not_drawn = [
        fk
        for fk in catalog_fks
        if (
            str(fk.get("source_table_id") or ""),
            str(fk.get("target_table_id") or ""),
            str(fk.get("source_column") or ""),
            str(fk.get("target_column") or ""),
        )
        not in drawn_catalog_pairs
    ]

    gaps: list[dict[str, Any]] = []
    for entity in entity_rows:
        for warning in entity.get("warnings") or []:
            if warning.get("severity") in {"warning", "error"}:
                gaps.append(
                    {
                        "code": warning["code"],
                        "severity": warning["severity"],
                        "message": warning["message"],
                        "params": warning.get("params") or {},
                        "entity_id": entity["id"],
                    }
                )
    for relationship in relationship_rows:
        for warning in relationship.get("warnings") or []:
            if warning.get("severity") in {"warning", "error"}:
                gaps.append(
                    {
                        "code": warning["code"],
                        "severity": warning["severity"],
                        "message": warning["message"],
                        "params": warning.get("params") or {},
                        "relationship_id": relationship["id"],
                    }
                )
    for fk in catalog_fks_not_drawn:
        gaps.append(
            {
                "code": "catalog_fk_not_in_erd",
                "severity": "info",
                "message": "The catalog declares a foreign key that the ERD does not draw.",
                "params": {
                    "source": f"{fk.get('source_table_id')}.{fk.get('source_column')}",
                    "target": f"{fk.get('target_table_id')}.{fk.get('target_column')}",
                },
            }
        )

    mapped_entities = [entity for entity in entity_rows if entity["table_id"]]
    termed_entities = [entity for entity in mapped_entities if entity.get("term")]
    described_entities = [
        entity for entity in mapped_entities if str(entity.get("description") or "").strip()
    ]
    validated_relationships = [
        relationship
        for relationship in relationship_rows
        if relationship["status"] in {"validated", "declared"}
    ]
    mapped_ratio = len(mapped_entities) / len(entity_rows) if entity_rows else 0.0
    term_ratio = len(termed_entities) / len(mapped_entities) if mapped_entities else 0.0
    description_ratio = (
        len(described_entities) / len(mapped_entities) if mapped_entities else 0.0
    )
    relationship_ratio = (
        len(validated_relationships) / len(relationship_rows)
        if relationship_rows
        else 1.0
    )
    readiness = round(
        (0.25 * mapped_ratio)
        + (0.25 * term_ratio)
        + (0.2 * description_ratio)
        + (0.3 * relationship_ratio),
        2,
    )
    readiness_label = (
        "ready" if readiness >= 0.8 else "review" if readiness >= 0.5 else "early"
    )
    issue_count = sum(
        1
        for gap in gaps
        if gap.get("severity") in {"warning", "error"}
    )
    return {
        "zone_id": canvas.get("zone_id"),
        "canvas_id": canvas.get("id"),
        "zone_name": canvas.get("zone_name"),
        "summary": {
            "node_count": len(entity_rows),
            "mapped_node_count": len(mapped_entities),
            "virtual_node_count": len(entity_rows) - len(mapped_entities),
            "term_count": len(termed_entities),
            "description_count": len(described_entities),
            "relationship_count": len(relationship_rows),
            "validated_relationship_count": len(validated_relationships),
            "existing_semantic_fk_count": sum(
                1
                for relationship in relationship_rows
                if relationship.get("existing_semantic_fk")
            ),
            "issue_count": issue_count,
            "gap_count": len(gaps),
            "readiness": readiness,
            "readiness_label": readiness_label,
        },
        "entities": entity_rows,
        "relationships": relationship_rows,
        "catalog_fks_not_drawn": catalog_fks_not_drawn,
        "gaps": gaps,
    }
