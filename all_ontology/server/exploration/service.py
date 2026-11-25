# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exploration service layer.

Keeps the HTTP router independent from the DAL and provides the
domain boundary for future Exploration-specific orchestration.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from itertools import combinations
from typing import Any

from all_ontology.connectors.registry import get_connectors
from all_ontology.dal.datasources import fetch_table_location
from all_ontology.dal.users import resolve_accessible_catalog_ids
from all_ontology.dal.zones import get_zone_by_id
from all_ontology.retrieval.text_to_sql.chat_sql import execute_chat_sql
from all_ontology.utils.sql_limits import with_row_limit
from all_ontology.dal.exploration import (
    MAX_EXPLORATION_GRAPH_NODES,
    fetch_column_attribute_exploration_details,
    fetch_column_exploration_details,
    fetch_data_exploration_edges,
    fetch_data_exploration_graph,
    fetch_exploration_related_nodes,
    fetch_pair_mode_columns,
    fetch_semantic_exploration_graph,
    fetch_semantic_link_path,
    fetch_sql_attribute_exploration_details,
    fetch_sql_exploration_details,
    fetch_table_exploration_details,
    fetch_table_zones_map,
    fetch_term_exploration_details,
)

logger = logging.getLogger(__name__)

#: How long a preview query may run. The page waits on it, and a table that
#: cannot produce a sample in this long is a source problem, not a UI one.
PREVIEW_TIMEOUT_SECONDS = 15.0

#: Column-name cues that make a pair look like a join key rather than a measure.
_KEY_HINTS = (
    "日期",
    "时间",
    "渠道",
    "客户",
    "商品",
    "门店",
    "地区",
    "城市",
    "分类",
    "类目",
    "状态",
    "编号",
    "代码",
    "订单号",
    "date",
    "time",
    "channel",
    "customer",
    "product",
    "store",
    "region",
    "city",
    "category",
    "status",
    "code",
    "id",
)

_MEASURE_HINTS = (
    "数量",
    "金额",
    "单价",
    "成本",
    "折扣",
    "访客",
    "浏览",
    "加购",
    "支付",
    "销售",
    "广告",
    "利润",
    "amount",
    "price",
    "cost",
    "quantity",
    "qty",
    "count",
    "total",
    "sum",
    "rate",
    "revenue",
    "spend",
)


def _normalize_column(name: str) -> str:
    return re.sub(r"[\s_\-()（）\[\]]+", "", str(name or "").lower())


def _has_hint(name: str, hints: tuple[str, ...]) -> bool:
    normalized = _normalize_column(name)
    return any(hint in normalized for hint in hints)


def _type_family(data_type: str | None) -> str:
    raw = str(data_type or "").upper()
    if any(
        token in raw
        for token in ("INT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL")
    ):
        return "number"
    if any(token in raw for token in ("DATE", "TIME")):
        return "temporal"
    if any(token in raw for token in ("BOOL",)):
        return "boolean"
    return "text"


def _column_candidate(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any] | None:
    """Score two columns as a possible join key, or return ``None``."""
    left_name = str(left.get("name") or "")
    right_name = str(right.get("name") or "")
    left_norm = _normalize_column(left_name)
    right_norm = _normalize_column(right_name)
    if left_norm == "" or right_norm == "":
        return None

    exact = left_norm == right_norm
    contained = (
        not exact
        and min(len(left_norm), len(right_norm)) >= 2
        and (left_norm in right_norm or right_norm in left_norm)
    )
    if not exact and not contained:
        return None

    left_measure = _has_hint(left_name, _MEASURE_HINTS)
    right_measure = _has_hint(right_name, _MEASURE_HINTS)
    left_key = _has_hint(left_name, _KEY_HINTS)
    right_key = _has_hint(right_name, _KEY_HINTS)
    if left_measure and right_measure:
        return None
    if not (left_key or right_key or exact):
        return None

    left_family = _type_family(left.get("data_type"))
    right_family = _type_family(right.get("data_type"))
    if left_family == right_family == "boolean":
        return None
    if left_family == right_family == "number" and not (left_key or right_key):
        return None

    confidence = 0.86 if exact else 0.68
    if left_key and right_key:
        confidence += 0.04
    if contained:
        confidence -= 0.03
    if left_family != right_family:
        confidence -= 0.08
    confidence = max(0.5, min(0.92, confidence))
    if confidence < 0.55:
        return None

    return {
        "source_column": left_name,
        "target_column": right_name,
        "confidence": round(confidence, 2),
        "match": "exact" if exact else "contains",
    }


def _candidate_suggestions(
    nodes: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    existing_pairs: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    by_table: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        by_table.setdefault(str(column["table_id"]), []).append(column)

    node_ids = sorted(node["id"] for node in nodes)
    suggestions: list[dict[str, Any]] = []
    for source_id, target_id in combinations(node_ids, 2):
        key = (
            (source_id, target_id) if source_id < target_id else (target_id, source_id)
        )
        if key in existing_pairs:
            continue
        best: dict[str, Any] | None = None
        for left in by_table.get(source_id, []):
            for right in by_table.get(target_id, []):
                candidate = _column_candidate(left, right)
                if candidate is None:
                    continue
                if best is None or candidate["confidence"] > best["confidence"]:
                    best = candidate
        if best is not None:
            suggestions.append({"source": source_id, "target": target_id, **best})
    return suggestions


def _preview_value(value: Any) -> Any:
    """JSON-safe rendering of one cell."""
    import pandas as pd

    if value is None:
        return None
    if pd.api.types.is_scalar(value):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    # numpy scalars (and pandas' own) carry .item(); JSON cannot encode them.
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes)):
        try:
            value = item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, bool) or isinstance(value, str) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        as_float = float(value)
        return as_float if math.isfinite(as_float) else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value[:64]).hex()
    return str(value)


def fetch_table_preview(
    table_id: str,
    *,
    limit: int = 20,
    zone_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run a bounded ``SELECT *`` against the table's live source.

    Raises ``LookupError`` when the table is unknown or its database has no
    live connector, and ``StatementTimeout`` when the source is too slow.
    """
    scoped = resolve_accessible_catalog_ids(zone_ids)
    if scoped is not None and table_id not in scoped["table_ids"]:
        raise LookupError(f"No table found for id {table_id!r}")

    location = fetch_table_location(table_id)
    if location is None:
        raise LookupError(f"No table found for id {table_id!r}")

    database_name = str(location["database_name"])
    connector = next(
        (
            candidate
            for candidate in get_connectors()
            if candidate.database_name == database_name
        ),
        None,
    )
    if connector is None:
        raise LookupError(
            f"No live connection is configured for database {database_name!r}"
        )

    reference = connector.qualify(location["schema_name"], location["name"])
    # One extra row answers "is there more?" without a second query.
    sql = with_row_limit(f"SELECT * FROM {reference}", limit + 1, connector.dialect)
    frame = execute_chat_sql(
        connector, sql, kind="table preview", timeout_s=PREVIEW_TIMEOUT_SECONDS
    )

    truncated = len(frame) > limit
    if truncated:
        frame = frame.head(limit)

    return {
        "table_id": table_id,
        "columns": [str(column) for column in frame.columns],
        "rows": [
            [_preview_value(value) for value in row]
            for row in frame.itertuples(index=False)
        ],
        "row_count": int(len(frame)),
        "truncated": truncated,
    }


def fetch_pair_mode_analysis(zone_id: str) -> dict[str, Any]:
    """Build the relationship graph for exactly one Zone.

    The agent-facing pass is deliberately Zone-scoped: ``resolve_accessible_catalog_ids``
    receives only *zone_id*, every table query is filtered to that scope, and
    semantic-FK edges are restricted to columns on those same tables. Nothing
    outside the Zone can enter the graph or the summary.
    """
    zone = get_zone_by_id(zone_id)
    if zone is None:
        raise LookupError(f"No zone found for id {zone_id!r}")
    if zone.get("enabled") is False:
        raise ValueError(f"Zone {zone_id!r} is disabled")

    graph = fetch_data_exploration_graph(zone_ids=[zone_id])
    edges = fetch_data_exploration_edges(zone_ids=[zone_id], include_semantic_fks=True)
    node_ids = {node["id"] for node in graph["nodes"]}
    confirmed_links = [
        edge
        for edge in edges
        if edge["source"] in node_ids and edge["target"] in node_ids
    ]
    existing_pairs = {
        (min(edge["source"], edge["target"]), max(edge["source"], edge["target"]))
        for edge in confirmed_links
    }
    suggestions = _candidate_suggestions(
        graph["nodes"],
        fetch_pair_mode_columns(sorted(node_ids)),
        existing_pairs,
    )
    candidate_links = [
        {
            "source": suggestion["source"],
            "target": suggestion["target"],
            "queries": [],
            "via_foreign_key": False,
            "foreign_keys": [],
            "semantic_fks": [],
            "relationship_types": ["CANDIDATE"],
        }
        for suggestion in suggestions
    ]
    links = [*confirmed_links, *candidate_links]
    links.sort(key=lambda edge: (edge["source"], edge["target"]))

    degree: Counter[str] = Counter()
    relationship_counts: Counter[str] = Counter()
    for edge in links:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
        relationship_counts.update(edge.get("relationship_types") or [])

    nodes = [
        {**node, "relationship_count": degree[node["id"]]} for node in graph["nodes"]
    ]
    isolated = [node for node in nodes if degree[node["id"]] == 0]
    related = len(nodes) - len(isolated)

    return {
        "zone": zone,
        "graph": {"nodes": nodes, "links": links},
        "summary": {
            "table_count": len(nodes),
            "relationship_count": len(links),
            "confirmed_relationship_count": len(confirmed_links),
            "suggested_relationship_count": len(suggestions),
            "related_table_count": related,
            "isolated_table_count": len(isolated),
            "relationship_counts": dict(sorted(relationship_counts.items())),
        },
        "suggestions": suggestions,
        "isolated_tables": isolated,
    }


__all__ = [
    "MAX_EXPLORATION_GRAPH_NODES",
    "PREVIEW_TIMEOUT_SECONDS",
    "fetch_column_attribute_exploration_details",
    "fetch_column_exploration_details",
    "fetch_data_exploration_edges",
    "fetch_data_exploration_graph",
    "fetch_exploration_related_nodes",
    "fetch_pair_mode_analysis",
    "fetch_semantic_exploration_graph",
    "fetch_semantic_link_path",
    "fetch_sql_attribute_exploration_details",
    "fetch_sql_exploration_details",
    "fetch_table_exploration_details",
    "fetch_table_preview",
    "fetch_table_zones_map",
    "fetch_term_exploration_details",
]
