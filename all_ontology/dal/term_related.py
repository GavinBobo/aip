# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Term-to-term relationships: the shared table links and their paging."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, literal, select

from all_ontology.dal import schema as s
from all_ontology.dal.session import store
from all_ontology.dal.term_scope import _in_scope, _scope_table_ids
from all_ontology.dal.users import resolve_accessible_catalog_ids
from all_ontology.semantic.constants import (
    REL_HAS_ATTRIBUTE,
    REL_REPRESENTS,
    REL_SEMANTIC_FK,
    SEMANTIC_SOURCE,
)


def fetch_term_table_pairs(
    zone_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
    database_name: str | None = None,
    *,
    term_ids: list[str] | None = None,
    table_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """``{term_id, table_id}`` — the one definition of "related".

    A term is linked to a table by REPRESENTS, or through a ColumnAttribute
    reached by HAS_ATTRIBUTE **or** SEMANTIC_FK. That third path is what links,
    say, ``Request`` to ``User`` when ``requests.creator_id`` references
    ``users.id``.

    Shared by the related list, the per-term count and the Exploration graph, so
    a term's badge, the "Relationships" column, and the length of the list
    behind them cannot report three different numbers.

    Both branches require ``source = 'semantic'`` on the Term, matching
    ``fetch_all_terms``: a non-semantic Term never appears in the semantic
    graph, so counting it as a neighbour would put a number on a card no list
    can reach.

    ``path`` names which of those three links actually connected this
    particular pair (``REPRESENTS``, ``HAS_ATTRIBUTE`` or ``SEMANTIC_FK``), so a
    caller that cares *why* a term and a table are linked -- not just *that*
    they are -- does not have to re-run the match itself;
    :func:`all_ontology.dal.exploration.fetch_semantic_exploration_graph` uses it to
    label term↔term edges with the real relationship type(s) behind them.

    *database_name*, when given, additionally restricts results to tables in
    that database only — same idiom as ``fetch_terms_with_sqls``'s scoping.
    This matters because Term nodes are global (no ``database_name`` of their
    own, and not scoped by *zone_ids* either, since a zone can span multiple
    databases): the same Term can legitimately be REPRESENTS-linked to tables
    in two unrelated databases that happen to model a similar concept under
    the same term name (e.g. "Case" in both a reverse-logistics and a
    labor-certification schema). Without this filter, a caller resolving
    "which tables does this term touch" for one specific live database can
    silently get tables back from a *different* database too.

    *term_ids* and *table_ids* narrow the scan; neither widens access, both
    being intersected with what *zone_ids* already allows.
    """
    scope_ids = _scope_table_ids(zone_ids, data_ids_by_zone)
    database_table_ids = (
        select(s.catalog_table.c.id)
        .select_from(
            s.catalog_table.join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            ).join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.catalog_database.c.name == database_name)
        if database_name is not None
        else None
    )

    def restrict(statement, table_column):
        conditions: list[Any] = [s.term.c.source == SEMANTIC_SOURCE]
        if scope_ids is not None:
            conditions.append(table_column.in_(scope_ids))
            conditions.append(_in_scope(scope_ids))
        if term_ids is not None:
            conditions.append(s.term.c.id.in_(list(term_ids)))
        if table_ids is not None:
            conditions.append(table_column.in_(list(table_ids)))
        if database_table_ids is not None:
            conditions.append(table_column.in_(database_table_ids))
        return statement.where(*conditions)

    represents = restrict(
        select(
            s.term.c.id.label("term_id"),
            s.table__term.c.table_id.label("table_id"),
            literal(REL_REPRESENTS).label("path"),
        ).select_from(
            s.table__term.join(s.term, s.term.c.id == s.table__term.c.term_id)
        ),
        s.table__term.c.table_id,
    )

    # The link's own type is carried along so ``path`` can name it below -- the
    # two legs are otherwise identical, and unioning them first would lose which
    # one matched.
    link = (
        select(
            s.column__has_attribute.c.column_id,
            s.column__has_attribute.c.attribute_id,
            literal(REL_HAS_ATTRIBUTE).label("rel_type"),
        )
        .union(
            select(
                s.column__semantic_fk.c.column_id,
                s.column__semantic_fk.c.attribute_id,
                literal(REL_SEMANTIC_FK).label("rel_type"),
            )
        )
        .subquery("attribute_link")
    )
    via_attribute = restrict(
        select(
            s.term.c.id.label("term_id"),
            s.catalog_column.c.table_id.label("table_id"),
            link.c.rel_type.label("path"),
        ).select_from(
            s.catalog_column.join(link, link.c.column_id == s.catalog_column.c.id)
            .join(
                s.column_attribute,
                and_(
                    s.column_attribute.c.id == link.c.attribute_id,
                    s.column_attribute.c.source == SEMANTIC_SOURCE,
                ),
            )
            .join(
                s.column_attribute__term,
                s.column_attribute__term.c.attribute_id == s.column_attribute.c.id,
            )
            .join(s.term, s.term.c.id == s.column_attribute__term.c.term_id)
        ),
        s.catalog_column.c.table_id,
    )

    return [dict(r) for r in store().query_read(represents.union(via_attribute))]


def build_term_table_maps(
    pairs: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Split ``{term_id, table_id}`` rows into term→tables and table→terms."""
    term_tables: dict[str, set[str]] = {}
    table_terms: dict[str, set[str]] = {}
    for row in pairs:
        term_id, table_id = row.get("term_id"), row.get("table_id")
        if term_id and table_id:
            term_tables.setdefault(term_id, set()).add(table_id)
            table_terms.setdefault(table_id, set()).add(term_id)
    return term_tables, table_terms


def fetch_related_term_ids(
    term_id: str,
    zone_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> list[str]:
    """Ids of every Term sharing a table with *term_id*.

    Split from :func:`fetch_related_terms` because the two steps page
    differently: which terms are related is a property of the whole accessible
    graph, and is what a pager's total counts, while one page of rows is a
    bounded read. The sort is only for stability — the order a reader sees is
    the name order :func:`fetch_terms_by_ids` imposes.
    """
    resolved = resolve_accessible_catalog_ids(zone_ids, data_ids_by_zone)
    own_pairs = fetch_term_table_pairs(zone_ids, resolved, term_ids=[term_id])
    shared = sorted({r["table_id"] for r in own_pairs if r.get("table_id")})
    if not shared:
        return []

    _, table_terms = build_term_table_maps(
        fetch_term_table_pairs(zone_ids, resolved, table_ids=shared)
    )
    related: set[str] = set()
    for table_id in shared:
        related.update(table_terms.get(table_id, set()))
    related.discard(term_id)
    return sorted(related)


def fetch_terms_by_ids(
    term_ids: list[str],
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """``{id, name, description}`` for *term_ids*, ordered and paged in SQL.

    *term_ids* is a plain id list — whatever produced it owns the zone scoping.
    """
    if not term_ids:
        return []
    statement = (
        select(s.term.c.id, s.term.c.name, s.term.c.description)
        .where(s.term.c.id.in_(list(term_ids)))
        .order_by(func.lower(s.term.c.name), s.term.c.id)
        .offset(skip)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return [dict(r) for r in store().query_read(statement)]


def fetch_related_terms(
    term_id: str,
    zone_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Terms related to *term_id* by sharing a table, paged by name.

    Related means co-located: both terms connect to the same table, by any of
    the three paths :func:`fetch_term_table_pairs` defines.

    When *zone_ids* is supplied both steps apply the all-or-nothing rule, so a
    related term the caller could not actually open — it would 404 through
    ``get_full_term_by_id`` — is never shown as a chip.
    """
    related_ids = fetch_related_term_ids(term_id, zone_ids, data_ids_by_zone)
    return fetch_terms_by_ids(related_ids, skip=skip, limit=limit)


def fetch_related_terms_counts(
    zone_ids: list[str] | None = None,
    term_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """``[{term_id, count}]`` — how many terms each one shares a table with.

    *term_ids* restricts which terms get an **entry**, not what counts as
    related: neighbours are resolved across the whole accessible graph, so a
    term's count does not shrink because the terms it relates to landed on
    another page.
    """
    resolved = resolve_accessible_catalog_ids(zone_ids, data_ids_by_zone)
    if term_ids is None:
        term_tables, table_terms = build_term_table_maps(
            fetch_term_table_pairs(zone_ids, resolved)
        )
        wanted = list(term_tables)
    else:
        if not term_ids:
            return []
        own_pairs = fetch_term_table_pairs(zone_ids, resolved, term_ids=term_ids)
        term_tables, _ = build_term_table_maps(own_pairs)
        touched = sorted({r["table_id"] for r in own_pairs})
        _, table_terms = build_term_table_maps(
            fetch_term_table_pairs(zone_ids, resolved, table_ids=touched)
            if touched
            else []
        )
        wanted = term_ids

    result: list[dict[str, Any]] = []
    for term_id in wanted:
        related: set[str] = set()
        for table_id in term_tables.get(term_id, set()):
            related.update(table_terms.get(table_id, set()))
        related.discard(term_id)
        result.append({"term_id": term_id, "count": len(related)})
    return result
