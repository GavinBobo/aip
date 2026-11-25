# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ColumnAttribute reads scoped to one Term."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from all_ontology.dal import schema as s
from all_ontology.dal.attributes import fetch_column_attribute_columns_map
from all_ontology.dal.session import store
from all_ontology.dal.tags import TARGET_COLUMN_ATTRIBUTE, fetch_tags_map
from all_ontology.dal.term_scope import _scope_table_ids, _with_parsed_sample_values
from all_ontology.dal.zones import fetch_table_zones_map
from all_ontology.semantic.constants import SEMANTIC_SOURCE


def _column_attribute_scope(term_id: str, zone_ids: list[str] | None):
    """A ColumnAttribute is owned by exactly one table, via ``attr.table_id``.

    So a plain membership filter is enough here — no all-or-nothing check, which
    is a genuine difference from the Term rule and not an oversight.
    """
    conditions = [
        s.column_attribute.c.source == SEMANTIC_SOURCE,
        s.column_attribute.c.term_name
        == select(s.term.c.name).where(s.term.c.id == term_id).scalar_subquery(),
    ]
    table_ids = _scope_table_ids(zone_ids)
    if table_ids is not None:
        conditions.append(s.column_attribute.c.table_id.in_(table_ids))
    return conditions


def fetch_column_attribute_counts(
    zone_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
    term_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """``[{term_id, count}]`` per Term. Terms with none are omitted."""
    statement = (
        select(
            s.column_attribute__term.c.term_id,
            func.count(func.distinct(s.column_attribute.c.id)).label("count"),
        )
        .select_from(
            s.column_attribute.join(
                s.column_attribute__term,
                s.column_attribute__term.c.attribute_id == s.column_attribute.c.id,
            )
        )
        .where(s.column_attribute.c.source == SEMANTIC_SOURCE)
        .group_by(s.column_attribute__term.c.term_id)
    )
    table_ids = _scope_table_ids(zone_ids, data_ids_by_zone)
    if table_ids is not None:
        statement = statement.where(s.column_attribute.c.table_id.in_(table_ids))
    if term_ids is not None:
        statement = statement.where(
            s.column_attribute__term.c.term_id.in_(list(term_ids))
        )

    return [
        {"term_id": r["term_id"], "count": int(r["count"])}
        for r in store().query_read(statement)
    ]


def fetch_column_attributes_by_term_id(
    term_id: str,
    zone_ids: list[str] | None = None,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """One Term's ColumnAttributes, with their columns and zones.

    One row per attribute even when several columns declare it: the sample
    values come from the lowest-id one. Without that collapse the rows outnumber
    the total the pager was handed, and the last attributes become unreachable.

    Ordered by name then id, so *skip* and *limit* page it stably; pair with
    ``count_column_attributes_by_term_id``.
    """
    sample_values = (
        select(s.catalog_column.c.sample_values)
        .select_from(
            s.column__has_attribute.join(
                s.catalog_column,
                s.catalog_column.c.id == s.column__has_attribute.c.column_id,
            )
        )
        .where(s.column__has_attribute.c.attribute_id == s.column_attribute.c.id)
        .order_by(s.catalog_column.c.id)
        .limit(1)
        .correlate(s.column_attribute)
        .scalar_subquery()
    )
    statement = (
        select(
            s.column_attribute.c.id,
            s.column_attribute.c.name,
            s.column_attribute.c.description,
            s.column_attribute.c.term_name,
            s.column_attribute.c.source_column,
            s.column_attribute.c.datatype,
            s.column_attribute.c.table_id,
            sample_values.label("sample_values"),
            s.column_attribute.c.certified,
            s.column_attribute.c.created,
            s.column_attribute.c.modified,
            s.column_attribute.c.created_by,
            s.column_attribute.c.modified_by,
        )
        .where(*_column_attribute_scope(term_id, zone_ids))
        .order_by(s.column_attribute.c.name, s.column_attribute.c.id)
        .offset(skip)
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = [dict(r) for r in store().query_read(statement)]
    table_ids = [row["table_id"] for row in rows if row["table_id"]]
    zones_by_table = (
        fetch_table_zones_map(zone_ids=zone_ids, table_ids=list(set(table_ids)))
        if table_ids
        else {}
    )
    columns_by_attr = fetch_column_attribute_columns_map([row["id"] for row in rows])
    tags_by_attr = fetch_tags_map(TARGET_COLUMN_ATTRIBUTE, [row["id"] for row in rows])
    empty = {"primary_column": None, "referenced_columns": []}
    return [
        {
            **row,
            "zones": zones_by_table.get(row["table_id"], []),
            "tags": tags_by_attr.get(row["id"], []),
            **columns_by_attr.get(row["id"], empty),
        }
        for row in _with_parsed_sample_values(rows)
    ]


def count_column_attributes_by_term_id(
    term_id: str,
    zone_ids: list[str] | None = None,
) -> int:
    """The unpaged size of :func:`fetch_column_attributes_by_term_id`."""
    rows = store().query_read(
        select(func.count(func.distinct(s.column_attribute.c.id)).label("total")).where(
            *_column_attribute_scope(term_id, zone_ids)
        )
    )
    return int(rows[0]["total"]) if rows else 0


def find_column_attribute_by_column_id(column_id: str) -> str | None:
    """The semantic ColumnAttribute a column carries.

    Re-exported from :mod:`all_ontology.dal.attributes`: callers import it from both
    modules, so both keep it.
    """
    from all_ontology.dal.attributes import (
        find_column_attribute_by_column_id as delegate,
    )

    return delegate(column_id)
