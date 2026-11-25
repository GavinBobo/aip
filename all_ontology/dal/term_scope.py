# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared Term scope helpers: sample rendering and accessible table ids."""

from __future__ import annotations

from typing import Any

from sqlalchemy import literal, select

from all_ontology.dal import schema as s
from all_ontology.dal.users import resolve_accessible_catalog_ids
from all_ontology.utils.sample_values import stringify_sample_values


def _with_parsed_sample_values(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render ``sample_values`` on each row as the string list callers expect.

    These rows serve both the terms API and semantic embedding text, so the
    typed values stored as JSON are rendered once here rather than at each use.
    """
    for row in rows:
        row["sample_values"] = stringify_sample_values(row.get("sample_values"))
    return rows

def _scope_table_ids(
    zone_ids: list[str] | None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> list[str] | None:
    resolved = resolve_accessible_catalog_ids(zone_ids, data_ids_by_zone)
    return None if resolved is None else list(resolved["table_ids"])


def _in_scope(table_ids: list[str] | None):
    """All-or-nothing table visibility, or ``None`` when unscoped.

    A term represented by any table outside *table_ids* is hidden entirely,
    matching the rule ``list_custom_analyses`` applies. Phrased in the negative
    — "no representing table is out of scope" — because the positive form would
    show a term that also represents something the caller cannot see.
    """
    if table_ids is None:
        return None
    return ~(
        select(literal(1))
        .select_from(s.table__term)
        .where(
            s.table__term.c.term_id == s.term.c.id,
            s.table__term.c.table_id.notin_(table_ids),
        )
        .correlate(s.term)
        .exists()
    )
