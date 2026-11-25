# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prediction-frame shaping: ranking, forecast order, and group-by aggregation."""

from __future__ import annotations

import re
from typing import Any

from all_ontology.connectors.base import SQLDatabase
from all_ontology.retrieval.kumo.pql_syntax import (
    _FOR_EACH_KW,
    _IDENT,
    _sql_table,
    quote_ident,
)


class PqlGroupByError(ValueError):
    """A grouped-prediction request that cannot be served (bad group-by column, or wrong target type)."""


def _is_forecast(pql: str) -> bool:
    """A ``FORECAST n TIMEFRAMES`` query: predicts a time series for a SINGLE entity (SDK constraint)."""
    return re.search(r"\bFORECAST\b", pql, re.IGNORECASE) is not None


_EXISTENCE_COUNT = re.compile(
    rf"PREDICT\s+COUNT\s*\(\s*{_IDENT}\s*\.\s*\*", re.IGNORECASE
)


def _is_existence_count_pql(pql: str) -> bool:
    """True for the degenerate ``COUNT(<child>.*)`` parent→immediate-child existence shape with no
    discriminating filter — KumoRFM device-side-asserts on it DETERMINISTICALLY, so an assert there is the
    shape and must fail fast. Any other shape that asserts (e.g. a large SUM aggregation) is hitting an
    INTERMITTENT CUDA fault and should be retried instead. A filter on the aggregation makes the count a
    real outcome (e.g. late/slip), so a WHERE before FOR EACH means it is not the degenerate shape."""
    match = _EXISTENCE_COUNT.search(pql)
    if not match:
        return False
    for_each = _FOR_EACH_KW.search(pql)
    head = pql[: for_each.start()] if for_each else pql
    return "where" not in head.lower()


def _order_forecast(df: Any) -> Any:
    """Order a forecast result chronologically by its ``TIME`` column (timeframes in sequence)."""
    for col in df.columns:
        if col.upper() == "TIME":
            try:
                return df.sort_values(col)
            except Exception:  # noqa: BLE001 - odd column; keep original order
                return df
    return df


def _rank_prediction(df: Any) -> Any:
    """Sort a prediction descending by its score column (``True_PROB``/``*_PROB``/``*_PRED``) so the agent
    sees the top entities first; leaves order untouched if there is no such column (e.g. pre-ranked
    RANK/link-prediction output)."""
    cols = list(df.columns)
    lowered = {c.lower(): c for c in cols}
    sort_col = None
    for key in ("true_prob", "probability"):
        if key in lowered:
            sort_col = lowered[key]
            break
    if sort_col is None:
        for c in cols:
            cl = c.lower()
            if cl.endswith("_prob") and cl != "false_prob":
                sort_col = c
                break
    if sort_col is None:
        for c in cols:
            if c.lower().endswith("_pred") or c.upper() == "TARGET_PRED":
                sort_col = c
                break
    if sort_col is not None:
        try:
            return df.sort_values(sort_col, ascending=False)
        except Exception:  # noqa: BLE001 - non-numeric/odd column; fall back to original order
            return df
    return df


# Prediction-frame columns that are never the predicted value (KumoRFM metadata columns).
_NON_VALUE_COLS = frozenset({"entity", "anchor_timestamp", "time"})


def _entity_id_column(df: Any, pk: str) -> str:
    """The column in a prediction frame that holds the entity primary-key values (KumoRFM uses ``ENTITY``)."""
    lowered = {c.lower(): c for c in df.columns}
    if "entity" in lowered:
        return lowered["entity"]
    if pk.lower() in lowered:
        return lowered[pk.lower()]
    return list(df.columns)[0]


def _prediction_value_column(df: Any, *, id_col: str) -> str:
    """The single numeric column holding the predicted value/probability to aggregate.

    Handles regression (one predicted-value column) and binary classification (the positive-class
    probability, ``*_True`` / ``True_PROB`` / ``*_PROB``). Raises for shapes that can't be aggregated by a
    scalar (multi-class, link prediction)."""
    import pandas.api.types as pat

    candidates = [
        c for c in df.columns if c != id_col and c.lower() not in _NON_VALUE_COLS
    ]
    lowered = {c.lower(): c for c in candidates}
    for key in ("true_prob", "probability"):
        if key in lowered:
            return lowered[key]
    positive = [
        c
        for c in candidates
        if (c.lower().endswith("_true") or c.lower().endswith("_prob"))
        and "false" not in c.lower()
    ]
    if len(positive) == 1:
        return positive[0]
    numeric = [c for c in candidates if pat.is_numeric_dtype(df[c])]
    if len(numeric) == 1:
        return numeric[0]
    for c in candidates:
        if c.lower().endswith("_pred") or c.upper() == "TARGET_PRED":
            return c
    raise PqlGroupByError(
        "This prediction's output cannot be aggregated by a group (it is multi-class or link prediction, which "
        "has no single value to sum/average). Group-by is supported for regression and binary predictions."
    )


def aggregate_prediction_by(
    prediction: Any,
    *,
    table: str,
    pk: str,
    group_by: str,
    connector: SQLDatabase,
    table_names: dict[str, str] | None = None,
) -> Any:
    """Roll a per-entity prediction up to per-group totals — the post-hoc aggregation PQL cannot do itself.

    Joins each scored entity to its ``group_by`` attribute (a read-only lookup on the entity table), then
    groups and aggregates the predicted value: ``total`` (sum, for additive targets like revenue/counts),
    ``average`` (mean, for rates/probabilities) and ``n_entities`` (group size). Returns a small DataFrame
    sorted by total descending. Raises :class:`PqlGroupByError` if ``group_by`` is not a column of the
    entity table or the prediction has no scalar value to aggregate.
    """
    id_col = _entity_id_column(prediction, pk)
    value_col = _prediction_value_column(prediction, id_col=id_col)
    try:
        dim = connector.execute(
            f"SELECT {quote_ident(pk)}, {quote_ident(group_by)} "
            f"FROM {_sql_table(table, table_names)} "
            f"WHERE {quote_ident(pk)} IS NOT NULL"
        )
    except Exception as exc:  # noqa: BLE001 - turn an opaque warehouse error into an actionable group-by error
        try:
            valid = list(
                connector.execute(
                    f"SELECT * FROM {_sql_table(table, table_names)} LIMIT 1"
                ).columns
            )
        except Exception:  # noqa: BLE001 - best-effort column listing for the message
            valid = []
        raise PqlGroupByError(
            f"Cannot group by '{group_by}': it is not a column of '{table}'."
            + (f" Valid columns: {valid}." if valid else "")
        ) from exc

    left = prediction[[id_col, value_col]].copy()
    left["__key"] = left[id_col].astype(str)
    right = dim.copy()
    right["__key"] = right[pk].astype(str)
    merged = left.merge(right[["__key", group_by]], on="__key", how="left")
    grouped = (
        merged.dropna(subset=[group_by])
        .groupby(group_by)[value_col]
        .agg(total="sum", average="mean", n_entities="count")
        .reset_index()
    )
    return grouped.sort_values("total", ascending=False)
