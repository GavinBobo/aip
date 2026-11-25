# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validation for knowledge object metrics.

A metric expression has two legitimate shapes:

* SQL / a SQL attribute backed by the data ontology — validate it with the
  existing SqlAttribute validator, which knows the catalog and connector;
* a documented formula with no data binding yet — parse it best-effort and
  report ``mode="formula"`` rather than pretending a text formula is executable.
"""

from __future__ import annotations

import json
from typing import Any

from all_ontology.dal import knowledge as knowledge_dal


def validate_metric(metric_id: str) -> dict[str, Any]:
    metric = knowledge_dal.get_metric_context(metric_id)
    if metric is None:
        raise ValueError("Knowledge metric not found.")
    expression = str(metric.get("expression") or "").strip()
    attribute_id = metric.get("sql_attribute_id")
    term_id = metric.get("term_id")

    if attribute_id:
        expression = str(metric.get("sql_attribute_expression") or expression)
    if not expression:
        return {
            "valid": False,
            "mode": "empty",
            "message": "The metric has no expression or formula.",
            "expression": None,
        }

    if attribute_id or term_id:
        from all_ontology.domain import sql_attributes as sql_attribute_service

        try:
            result = sql_attribute_service.validate_sql_attribute(
                expression=expression,
                term_id=term_id,
                attribute_id=attribute_id,
            )
        except Exception as exc:  # noqa: BLE001 — public validation result
            return {
                "valid": False,
                "mode": "sql",
                "message": str(exc),
                "expression": expression,
            }
        return {
            "valid": True,
            "mode": "sql",
            "message": "SQL validated against the catalog and connector.",
            "expression": expression,
            "details": result,
        }

    try:
        import sqlglot

        sqlglot.parse_one(f"SELECT ({expression}) AS metric_value", read="postgres")
    except Exception:
        return {
            "valid": None,
            "mode": "formula",
            "message": "No data object is bound; stored as a documented formula.",
            "expression": expression,
        }
    return {
        "valid": True,
        "mode": "sql_syntax",
        "message": "Expression parses as SQL; it has not been executed against data.",
        "expression": expression,
    }


def preview_metric(metric_id: str, *, limit: int = 5) -> dict[str, Any]:
    """Execute a data-bound metric against its source table."""
    metric = knowledge_dal.get_metric_context(metric_id)
    if metric is None:
        raise ValueError("Knowledge metric not found.")
    expression = str(metric.get("expression") or "").strip()
    if not expression:
        raise ValueError("The metric has no expression or formula.")
    if not metric.get("table_id"):
        raise ValueError(
            "The metric is not bound to a data table. Link its concept to a catalog table before previewing."
        )

    import sqlglot

    statement = f"SELECT ({expression}) AS metric_value"
    sqlglot.parse_one(statement, read="postgres")

    from all_ontology.connectors.registry import get_connectors

    connector = next(
        (
            item
            for item in get_connectors()
            if item.database_name == metric.get("database_name")
        ),
        None,
    )
    if connector is None:
        raise ValueError(
            f"No live connection is configured for database {metric.get('database_name')!r}."
        )
    reference = connector.qualify(metric.get("schema_name"), str(metric["table_name"]))
    sql = f"{statement} FROM {reference} LIMIT {max(1, min(int(limit), 50))}"
    frame = connector.execute(sql)
    rows = json.loads(frame.head(limit).to_json(orient="records", date_format="iso"))
    return {
        "expression": expression,
        "sql": sql,
        "columns": list(frame.columns),
        "rows": rows,
        "row_count": len(rows),
    }
