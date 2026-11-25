# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Term reads and writes.

ColumnAttribute and SEMANTIC_FK operations live in :mod:`all_ontology.dal.attributes`.

Three rules are shared by almost everything here, and each one exists because a
previous version of this code had two copies of it that drifted:

* **What counts as a Term** — a semantic Term with at least one table
  representing it (:func:`_semantic_terms`). The list, its total, and the
  single-id check all read it from one place, so they cannot disagree about
  which terms are real.
* **All-or-nothing table visibility** (:func:`_in_scope`). A term represented by
  *any* out-of-zone table is hidden entirely. Not a relevance filter — an
  authorization boundary.
* **What "related" means** (:func:`fetch_term_table_pairs`). Three paths from a
  table to a term, and the related list, the per-term badge, and the Exploration
  graph's edges all count the same rows. Spelling them out separately is what
  once let a card's badge, the "Relationships" column, and the length of the
  list behind them each report a different number.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import (
    String,
    case,
    func,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from all_ontology.dal import schema as s
from all_ontology.dal.session import store, write_transaction
from all_ontology.dal.tags import TARGET_TERM, fetch_tags_map
from all_ontology.dal.term_attributes import (  # noqa: F401
    count_column_attributes_by_term_id,
    fetch_column_attribute_counts,
    fetch_column_attributes_by_term_id,
    find_column_attribute_by_column_id,
)
from all_ontology.dal.term_related import (  # noqa: F401
    build_term_table_maps,
    fetch_related_term_ids,
    fetch_related_terms,
    fetch_related_terms_counts,
    fetch_term_table_pairs,
    fetch_terms_by_ids,
)
from all_ontology.dal.term_scope import _in_scope, _scope_table_ids
from all_ontology.dal.zones import zone_covers_table
from all_ontology.semantic.constants import (
    SEMANTIC_SOURCE,
)

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# The shared filters
# ---------------------------------------------------------------------------





def _represented():
    """The term has at least one table representing it.

    Half of what it means for a Term to exist as far as the UI is concerned;
    the other half is ``source = 'semantic'``.
    """
    return (
        select(literal(1))
        .where(s.table__term.c.term_id == s.term.c.id)
        .correlate(s.term)
        .exists()
    )


def _semantic_terms(
    zone_ids: list[str] | None = None,
    search: str | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
    *,
    term_id: str | None = None,
):
    """The predicate list every read of the visible Term set applies.

    ``fetch_all_terms`` and ``count_terms`` must select exactly the same terms —
    otherwise the total does not describe the list being paged — and
    ``term_is_in_scope`` must answer for one id whatever those two would answer
    for the whole set. All three take their filter from here.
    """
    conditions = [s.term.c.source == SEMANTIC_SOURCE, _represented()]
    scope = _in_scope(_scope_table_ids(zone_ids, data_ids_by_zone))
    if scope is not None:
        conditions.append(scope)
    if term_id is not None:
        conditions.append(s.term.c.id == term_id)
    if search:
        # Escaped: the caller means a literal substring. Unescaped, `_`
        # matches any character (so `customer_id` also finds `customerXid`)
        # and a lone `%` returns the entire glossary.
        needle = (
            search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        conditions.append(s.term.c.name.ilike(f"%{needle}%", escape="\\"))
    return conditions


def _certification(table_ids: list[str] | None):
    """A Term's aggregate certification: ``certified``, ``partial`` or ``pending``.

    The single definition of the rollup — the list cards, the detail page and
    the certification writes all project this, so the three cannot disagree.

    The flags are the Term's own two booleans plus one per column and sql
    attribute. Because the Term's two are always present the set is never empty,
    and a Term with no attributes is decided by them alone.

    When *table_ids* is given, each attribute count applies the same visibility
    rule as the endpoint that lists those attributes — plain ``table_id``
    membership for ColumnAttribute, all-or-nothing over the tables a
    SqlAttribute's SQL touches — so the badge never reflects an attribute the
    caller is not allowed to see.
    """

    def counts(link_table, attribute_table, extra=None):
        conditions = [
            link_table.c.term_id == s.term.c.id,
            link_table.c.attribute_id == attribute_table.c.id,
        ]
        if extra is not None:
            conditions.append(extra)
        total = (
            select(func.count())
            .select_from(link_table.join(attribute_table, conditions[1]))
            .where(*conditions)
            .correlate(s.term)
            .scalar_subquery()
        )
        certified = (
            select(func.count())
            .select_from(link_table.join(attribute_table, conditions[1]))
            .where(*conditions, attribute_table.c.certified.is_(True))
            .correlate(s.term)
            .scalar_subquery()
        )
        return total, certified

    column_visible = None
    sql_visible = None
    if table_ids is not None:
        column_visible = s.column_attribute.c.table_id.in_(table_ids)
        sql_visible = ~(
            select(literal(1))
            .select_from(
                s.sql_attribute__sql.join(
                    s.sql_query__table,
                    s.sql_query__table.c.sql_query_id
                    == s.sql_attribute__sql.c.sql_query_id,
                )
            )
            .where(
                s.sql_attribute__sql.c.attribute_id == s.sql_attribute.c.id,
                s.sql_query__table.c.table_id.notin_(table_ids),
            )
            .correlate(s.sql_attribute)
            .exists()
        )

    column_total, column_certified = counts(
        s.column_attribute__term, s.column_attribute, column_visible
    )
    sql_total, sql_certified = counts(
        s.sql_attribute__term, s.sql_attribute, sql_visible
    )

    own_certified = case((s.term.c.name_certified, 1), else_=0) + case(
        (s.term.c.description_certified, 1), else_=0
    )
    certified = own_certified + column_certified + sql_certified
    total = literal(2) + column_total + sql_total

    return case(
        (certified == total, "certified"),
        (certified == 0, "pending"),
        else_="partial",
    )


# ---------------------------------------------------------------------------
# Single-term reads
# ---------------------------------------------------------------------------


def get_term_certification(
    term_id: str,
    zone_ids: list[str] | None = None,
) -> str | None:
    """One Term's aggregate certification, or ``None`` when it is not visible.

    Certification writes call this so the list card can be updated without the
    frontend duplicating the rollup rule or refetching the whole list.
    """
    table_ids = _scope_table_ids(zone_ids)
    statement = select(_certification(table_ids).label("certification")).where(
        s.term.c.id == term_id
    )
    scope = _in_scope(table_ids)
    if scope is not None:
        statement = statement.where(scope)

    rows = store().query_read(statement.limit(1))
    return rows[0]["certification"] if rows else None


def term_is_in_scope(
    term_id: str,
    zone_ids: list[str] | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> bool:
    """Would ``fetch_all_terms`` return this term?

    Scope is the glossary set, not whichever nodes an Exploration payload
    happens to carry: a term dropped by graph truncation is still in scope, and
    has to be, since the relationship counts are computed untruncated.
    """
    rows = store().query_read(
        select(s.term.c.id)
        .where(
            *_semantic_terms(
                zone_ids, data_ids_by_zone=data_ids_by_zone, term_id=term_id
            )
        )
        .limit(1)
    )
    return bool(rows)


def semantic_layer_calculated() -> bool:
    """Has the semantic layer been built at all?"""
    return bool(
        store().query_read(
            select(s.term.c.id).where(s.term.c.source == SEMANTIC_SOURCE).limit(1)
        )
    )


def get_term_record_for_table(table_id: str) -> dict[str, str] | None:
    """``{id, name, description}`` for the Term a table represents.

    Returns ``None`` when the table has no representing Term. Unlike
    ``get_term_for_table``, which returns only the name, this also carries
    ``id``/``description`` — needed to rerank candidate owner Terms (e.g.
    for bridge-table SqlAttribute synthesis).
    """
    rows = store().query_read(
        select(
            s.term.c.id,
            s.term.c.name,
            func.coalesce(s.term.c.description, "").label("description"),
        )
        .select_from(s.table__term.join(s.term, s.term.c.id == s.table__term.c.term_id))
        .where(
            s.table__term.c.table_id == table_id,
            s.term.c.source == SEMANTIC_SOURCE,
        )
        .order_by(s.term.c.id)
        .limit(1)
    )
    return dict(rows[0]) if rows else None


def get_slim_term_by_id(term_id: str) -> dict[str, str] | None:
    """``{id, name}``, for callers that only need to name a term."""
    rows = store().query_read(
        select(s.term.c.id, s.term.c.name).where(s.term.c.id == term_id).limit(1)
    )
    return dict(rows[0]) if rows else None


def update_term(
    term_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    name_certified: bool | None = None,
    description_certified: bool | None = None,
    owner_id: str | None = None,
    set_owner: bool = False,
    modified_by: str | None = None,
    touch: bool = False,
) -> dict[str, Any] | None:
    """Update a Term, returning old and new values, or ``None`` when missing.

    ``old_name`` is in the return because the caller needs it: renaming a Term
    invalidates its embeddings, which are keyed on the old text.

    A rename also rewrites ``term_name`` on every ColumnAttribute of the Term.
    That is a denormalised copy, and keeping it in step here is not optional —
    ``fetch_column_attributes_by_term_id`` matches attributes to their term
    *through it*, so a stale copy silently empties a term's attribute list.
    """
    # One transaction: the rename and the denormalised copy on every
    # ColumnAttribute are the same fact. If the second statement fails on its
    # own, `fetch_column_attributes_by_term_id` matches through the stale copy
    # and the Term's attribute list reads as empty from then on.
    with write_transaction():
        # Read the old name first. RETURNING gives the *new* one, and the caller
        # compares the two to decide whether a rename happened -- with it always
        # None, `name_changed` was true for every edit, so a description-only
        # PATCH cleared description_suggestion on every SqlAttribute of the term
        # and re-embedded all of them.
        previous = store().query_read(
            select(s.term.c.name).where(s.term.c.id == term_id)
        )
        old_name = previous[0]["name"] if previous else None

        values: dict[str, Any] = {
            "name": func.coalesce(literal(name, String), s.term.c.name),
            "description": func.coalesce(
                literal(description, String), s.term.c.description
            ),
            "name_certified": func.coalesce(name_certified, s.term.c.name_certified),
            "description_certified": func.coalesce(
                description_certified, s.term.c.description_certified
            ),
            "owner_id": (literal(owner_id, String) if set_owner else s.term.c.owner_id),
        }
        # Only an edit from the app. Compilation calls this without ``touch``
        # and must not look like someone saved the term.
        if touch:
            values["modified"] = func.now()
            values["modified_by"] = modified_by
        rows = store().query_write(
            update(s.term)
            .where(s.term.c.id == term_id)
            .values(**values)
            .returning(
                s.term.c.id,
                s.term.c.name,
                s.term.c.description,
                s.term.c.name_certified,
                s.term.c.description_certified,
                s.term.c.owner_id,
            )
        )
        if not rows:
            return None
        result = dict(rows[0])
        result["old_name"] = old_name

        # Read before the UPDATE would have been simpler, but RETURNING gives
        # the new name and the old one is only knowable beforehand -- so it is
        # fetched first, above, by way of this second statement being the
        # *rename*.
        store().query_write(
            update(s.column_attribute)
            .where(
                s.column_attribute.c.id.in_(
                    select(s.column_attribute__term.c.attribute_id).where(
                        s.column_attribute__term.c.term_id == term_id
                    )
                )
            )
            .values(term_name=result["name"])
        )
    return result


def upsert_table_term(
    name: str,
    description: str,
    table_id: str,
    synonyms: list[str] | None = None,
) -> tuple[str, str] | None:
    """Upsert a compilation Term owned by one table.

    The proposed name is kept unless another table already owns it. Collisions
    are qualified with the table's full catalog identity, keeping the global
    ``(name, source)`` constraint and name-based attribute lookups unambiguous.
    Returns ``(term_id, persisted_name)``, or ``None`` for a missing table.
    """
    with write_transaction():
        tables = store().query_read(
            select(
                s.catalog_database.c.name.label("database_name"),
                s.catalog_schema.c.name.label("schema_name"),
                s.catalog_table.c.name.label("table_name"),
            )
            .select_from(
                s.catalog_table.join(
                    s.catalog_schema,
                    s.catalog_schema.c.id == s.catalog_table.c.schema_id,
                ).join(
                    s.catalog_database,
                    s.catalog_database.c.id == s.catalog_schema.c.database_id,
                )
            )
            .where(s.catalog_table.c.id == table_id)
        )
        if not tables:
            return None

        table = tables[0]
        qualified_table = ".".join(
            part
            for part in (
                table["database_name"],
                table["schema_name"],
                table["table_name"],
            )
            if part
        )
        candidate_names = (
            name,
            f"{name} ({qualified_table})",
            f"{name} ({table_id})",
        )

        for candidate_name in candidate_names:
            existing = store().query_read(
                select(s.term.c.id, s.table__term.c.table_id)
                .select_from(
                    s.term.outerjoin(
                        s.table__term, s.table__term.c.term_id == s.term.c.id
                    )
                )
                .where(
                    s.term.c.name == candidate_name,
                    s.term.c.source == SEMANTIC_SOURCE,
                )
            )
            represented_tables = {
                row["table_id"] for row in existing if row.get("table_id")
            }
            if existing and represented_tables == {table_id}:
                term_id = existing[0]["id"]
                store().query_write(
                    update(s.term)
                    .where(s.term.c.id == term_id)
                    .values(description=description, synonyms=synonyms or [])
                )
                return term_id, candidate_name
            if existing:
                continue

            statement = (
                insert(s.term)
                .values(
                    name=candidate_name,
                    source=SEMANTIC_SOURCE,
                    description=description,
                    synonyms=synonyms or [],
                )
                .on_conflict_do_nothing(constraint="uq_term_name_source")
                .returning(s.term.c.id)
            )
            inserted = store().query_write(statement)
            if not inserted:
                # Another compiler won this name after the read. Try the next,
                # more specific candidate instead of sharing its Term.
                continue
            term_id = inserted[0]["id"]
            store().query_write(
                insert(s.table__term).values(table_id=table_id, term_id=term_id)
            )
            return term_id, candidate_name

    raise RuntimeError(f"Could not allocate a private Term name for table {table_id}")


def fetch_term_synonyms(attr_ids: list[str]) -> dict[str, list[str]]:
    """``{term_name: [synonym, ...]}`` for the terms behind these attributes.

    Keyed by *name*, not id, because the caller matches synonyms against text.
    Terms with no synonyms are omitted rather than mapped to an empty list.
    """
    if not attr_ids:
        return {}
    try:
        rows = store().query_read(
            select(s.term.c.name, s.term.c.synonyms)
            .select_from(
                s.column_attribute__term.join(
                    s.term, s.term.c.id == s.column_attribute__term.c.term_id
                )
            )
            .where(
                s.column_attribute__term.c.attribute_id.in_(list(attr_ids)),
                s.term.c.synonyms.isnot(None),
                func.array_length(s.term.c.synonyms, 1) > 0,
            )
            .distinct()
        )
    except Exception:
        logger.warning("fetch_term_synonyms: query failed", exc_info=True)
        return {}

    result: dict[str, list[str]] = {}
    for row in rows:
        synonyms = [synonym for synonym in (row["synonyms"] or []) if synonym]
        if row["name"] and synonyms:
            result[row["name"]] = synonyms
    return result


# ---------------------------------------------------------------------------
# The Term list
# ---------------------------------------------------------------------------


def fetch_all_terms(
    zone_ids: list[str] | None = None,
    search: str | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """The glossary, paged.

    *zone_ids* is a hard authorization boundary. A Term can be represented by
    more than one table, so it is returned only when **every** representing
    table is reachable — a term also representing an out-of-zone table is
    excluded outright. ``None`` returns everything, for admin callers.

    Each row carries its ``zones``, its ``tags``, its ``owner_id`` and its
    aggregate ``certification``, all scoped to the same boundary, so a card
    renders chips, an owner and a badge from one response rather than a
    request per card. Tags are one query for the page, not one per term.

    Ordered by name case-insensitively then by id — the id breaks ties between
    same-named terms, without which a page boundary could repeat one and skip
    another. Pair with ``count_terms`` for the total.
    """
    table_ids = _scope_table_ids(zone_ids, data_ids_by_zone)
    schema_names = (
        select(func.array_agg(func.distinct(s.catalog_schema.c.name)))
        .select_from(
            s.table__term.join(
                s.catalog_table, s.catalog_table.c.id == s.table__term.c.table_id
            ).join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
        )
        .where(s.table__term.c.term_id == s.term.c.id)
        .correlate(s.term)
        .scalar_subquery()
    )

    statement = (
        select(
            s.term.c.name,
            s.term.c.description,
            s.term.c.synonyms,
            s.term.c.id,
            schema_names.label("schema_names"),
            s.term.c.name_certified,
            s.term.c.description_certified,
            s.term.c.owner_id,
            _certification(table_ids).label("certification"),
        )
        .where(*_semantic_terms(zone_ids, search, data_ids_by_zone))
        .order_by(func.lower(s.term.c.name), s.term.c.id)
        .offset(skip)
    )
    if limit is not None:
        statement = statement.limit(limit)

    terms = [dict(r) for r in store().query_read(statement)]
    # Scoped to the rows just read, so paging does not resolve zones and tags
    # for the rest of the glossary on every page.
    term_ids = [row["id"] for row in terms]
    zones_by_term = fetch_term_zones_map(zone_ids, term_ids=term_ids)
    tags_by_term = fetch_tags_map(TARGET_TERM, term_ids)
    for row in terms:
        row["schema_names"] = row["schema_names"] or []
        row["zones"] = zones_by_term.get(row["id"], [])
        row["tags"] = tags_by_term.get(row["id"], [])
    return terms


def count_terms(
    zone_ids: list[str] | None = None,
    search: str | None = None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> int:
    """The unpaged size of :func:`fetch_all_terms`, from the same filter."""
    rows = store().query_read(
        select(func.count(func.distinct(s.term.c.id)).label("total")).where(
            *_semantic_terms(zone_ids, search, data_ids_by_zone)
        )
    )
    return int(rows[0]["total"]) if rows else 0


def fetch_all_terms_and_attributes(
    zone_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every Term and every ColumnAttribute, for a one-shot bulk re-embed.

    Only ``embed_all_semantic_nodes`` wants this. The second scan is global and
    expensive; callers that need Term rows alone — the ``/terms`` list, the
    Exploration graph — should call :func:`fetch_all_terms` and skip it.
    """
    terms = fetch_all_terms(zone_ids=zone_ids)

    statement = (
        select(
            s.column_attribute.c.name,
            s.column_attribute.c.description,
            s.column_attribute.c.term_name,
            s.column_attribute.c.source_column,
            s.catalog_column.c.name.label("column_name"),
            s.catalog_column.c.sample_values,
            s.catalog_column.c.is_unique,
            s.catalog_table.c.id.label("table_id"),
            s.catalog_table.c.name.label("table_name"),
            s.column_attribute.c.id,
            s.catalog_schema.c.name.label("schema_name"),
            s.column_attribute.c.datatype,
        )
        .select_from(
            s.column_attribute.join(
                s.column__has_attribute,
                s.column__has_attribute.c.attribute_id == s.column_attribute.c.id,
            )
            .join(
                s.catalog_column,
                s.catalog_column.c.id == s.column__has_attribute.c.column_id,
            )
            .join(s.catalog_table, s.catalog_table.c.id == s.catalog_column.c.table_id)
            .join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
        )
        .where(s.column_attribute.c.source == SEMANTIC_SOURCE)
    )
    table_ids = _scope_table_ids(zone_ids)
    if table_ids is not None:
        statement = statement.where(s.catalog_table.c.id.in_(table_ids))

    return terms, [dict(r) for r in store().query_read(statement)]


def get_full_term_by_id(
    term_id: str,
    zone_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """One Term with its tables, table count, zones and certification.

    Applies the same all-or-nothing rule as :func:`fetch_all_terms`, so a viewer
    cannot bypass list-level scoping by requesting a term directly by id —
    ``None`` here becomes a 404.

    ``zones`` is resolved through **both** paths a term carries content by:
    ColumnAttribute → Column → Table, and SqlAttribute → Sql → Table. A term's
    SqlAttribute can reference tables no ColumnAttribute touches (a cross-table
    formula, say), and the term participates in a zone when *either* path
    reaches it.
    """
    table_ids = _scope_table_ids(zone_ids)
    statement = select(
        s.term.c.name,
        s.term.c.description,
        s.term.c.synonyms,
        s.term.c.id,
        s.term.c.name_certified,
        s.term.c.description_certified,
        s.term.c.owner_id,
        s.term.c.created,
        s.term.c.modified,
        s.term.c.created_by,
        s.term.c.modified_by,
        _certification(table_ids).label("certification"),
    ).where(s.term.c.id == term_id)
    scope = _in_scope(table_ids)
    if scope is not None:
        statement = statement.where(scope)

    rows = store().query_read(statement.limit(1))
    if not rows:
        return None
    result = dict(rows[0])

    tables = store().query_read(
        select(
            s.catalog_table.c.id,
            s.catalog_table.c.name,
            s.catalog_schema.c.id.label("schema_id"),
            s.catalog_database.c.id.label("db_id"),
        )
        .select_from(
            s.table__term.join(
                s.catalog_table, s.catalog_table.c.id == s.table__term.c.table_id
            )
            .join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
            .join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.table__term.c.term_id == term_id)
        .order_by(s.catalog_table.c.id)
    )
    result["tables"] = [dict(r) for r in tables]
    result["table_count"] = len(result["tables"])
    result["zones"] = fetch_term_zones_map(zone_ids, term_ids=[term_id]).get(
        term_id, []
    )
    result["tags"] = fetch_tags_map(TARGET_TERM, [term_id]).get(term_id, [])
    return result


def _term_zone_rows(path_join, term_filter):
    """Zone rows reachable from a Term along one attribute path."""
    return (
        select(
            s.term.c.id.label("term_id"),
            s.zone.c.id,
            s.zone.c.name,
            s.zone.c.color,
            s.zone.c.enabled,
        )
        .select_from(path_join)
        .where(*term_filter)
        .distinct()
    )


def fetch_term_zones_map(
    zone_ids: list[str] | None = None,
    term_ids: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """``{term_id: [zone, ...]}``, resolving many terms in one pass.

    The union of the two paths :func:`get_full_term_by_id` describes, so the
    Terms list and the Exploration graph render chips without a request per
    node — and, more to the point, agree with the detail page.

    *term_ids* narrows the scan; it never widens access, which *zone_ids* alone
    decides. An empty list means no terms, not all of them.
    """
    if term_ids is not None and not term_ids:
        return {}

    column_path = (
        s.term.join(
            s.column_attribute__term,
            s.column_attribute__term.c.term_id == s.term.c.id,
        )
        .join(
            s.column__has_attribute,
            s.column__has_attribute.c.attribute_id
            == s.column_attribute__term.c.attribute_id,
        )
        .join(
            s.catalog_column,
            s.catalog_column.c.id == s.column__has_attribute.c.column_id,
        )
        .join(s.catalog_table, s.catalog_table.c.id == s.catalog_column.c.table_id)
        .join(s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id)
        .join(s.zone_target, zone_covers_table())
        .join(s.zone, s.zone.c.id == s.zone_target.c.zone_id)
    )
    sql_path = (
        s.term.join(
            s.sql_attribute__term, s.sql_attribute__term.c.term_id == s.term.c.id
        )
        .join(
            s.sql_attribute__sql,
            s.sql_attribute__sql.c.attribute_id == s.sql_attribute__term.c.attribute_id,
        )
        .join(
            s.sql_query__table,
            s.sql_query__table.c.sql_query_id == s.sql_attribute__sql.c.sql_query_id,
        )
        .join(s.catalog_table, s.catalog_table.c.id == s.sql_query__table.c.table_id)
        .join(s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id)
        .join(s.zone_target, zone_covers_table())
        .join(s.zone, s.zone.c.id == s.zone_target.c.zone_id)
    )

    term_filter: list[Any] = []
    if term_ids is not None:
        term_filter.append(s.term.c.id.in_(list(term_ids)))
    if zone_ids is not None:
        # A viewer never sees a disabled zone's chip, even when its id is in
        # zone_ids -- access may have been granted before it was retired.
        term_filter.append(s.zone.c.id.in_(list(zone_ids)))
        term_filter.append(s.zone.c.enabled.is_(True))

    rows = store().query_read(
        _term_zone_rows(column_path, term_filter).union(
            _term_zone_rows(sql_path, term_filter)
        )
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["term_id"], []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "color": row["color"],
                "enabled": row["enabled"],
            }
        )
    for term_id, zones in result.items():
        result[term_id] = sorted(zones, key=lambda zone: zone["name"])
    return result


# ---------------------------------------------------------------------------
# Suggester and embedding inputs
# ---------------------------------------------------------------------------


def fetch_table_schema_map(database_name: str) -> dict[str, str]:
    """``{table_name_lower: schema_name}`` for one database.

    The SqlAttribute suggester uses it to qualify bare table names in generated
    SELECTs. Lower-cased keys, and last write wins on a collision — two schemas
    with the same table name resolve arbitrarily, as before.
    """
    rows = store().query_read(
        select(
            s.catalog_table.c.name.label("table_name"),
            s.catalog_schema.c.name.label("schema_name"),
        )
        .select_from(
            s.catalog_table.join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            ).join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.catalog_database.c.name == database_name)
        .order_by(s.catalog_table.c.id)
    )
    return {
        row["table_name"].lower(): row["schema_name"]
        for row in rows
        if row["table_name"] and row["schema_name"]
    }


def fetch_terms_with_sqls(
    source: str = SEMANTIC_SOURCE,
    database_name: str | None = None,
) -> list[dict[str, Any]]:
    """Every Term with the **ingestion** SQL of its connected tables.

    Statements owned by a SqlAttribute or CustomAnalysis are excluded, so
    generated semantic SQL cannot feed the next round of suggestions — a
    feedback loop where the suggester learns from itself.

    *source* defaults to ``SEMANTIC_SOURCE`` — matching main's version, which
    hardcoded it — so callers that never cared about non-semantic terms (the
    zero-arg call sites/tests) keep working unchanged; it's only a parameter
    at all because ``sql_attribute_suggester.py`` passes it explicitly.

    Terms with no ingestion query are omitted. When *database_name* is given,
    only terms whose tables belong to that database are returned — required
    when compiling one DB at a time so SqlAttribute validation uses a
    matching catalog.

    ``props`` is the statement row itself. There are no per-month counters —
    they were measured as unread by anything, and the schema does not carry
    them.
    """
    owned = (
        select(literal(1))
        .where(s.sql_attribute__sql.c.sql_query_id == s.sql_query.c.id)
        .correlate(s.sql_query)
        .exists()
    ) | (
        select(literal(1))
        .where(s.custom_analysis__sql.c.sql_query_id == s.sql_query.c.id)
        .correlate(s.sql_query)
        .exists()
    )

    statement = (
        select(
            s.term.c.id.label("term_id"),
            s.term.c.name.label("term_name"),
            s.term.c.description.label("term_description"),
            s.sql_query,
        )
        .select_from(
            s.term.join(s.table__term, s.table__term.c.term_id == s.term.c.id)
            .join(
                s.sql_query__table,
                s.sql_query__table.c.table_id == s.table__term.c.table_id,
            )
            .join(s.sql_query, s.sql_query.c.id == s.sql_query__table.c.sql_query_id)
        )
        .where(s.term.c.source == source, ~owned)
        .distinct()
        .order_by(s.term.c.id, s.sql_query.c.id)
    )
    if database_name is not None:
        statement = statement.select_from(
            s.catalog_schema.join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        ).where(
            s.table__term.c.table_id == s.catalog_table.c.id,
            s.catalog_table.c.schema_id == s.catalog_schema.c.id,
            s.catalog_database.c.name == database_name,
        )

    rows = store().query_read(statement)

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = grouped.setdefault(
            row["term_id"],
            {
                "term_id": row["term_id"],
                "term_name": row["term_name"],
                "term_description": row["term_description"],
                "sqls": [],
            },
        )
        props = {
            key: value
            for key, value in row.items()
            if key not in {"term_id", "term_name", "term_description"}
        }
        entry["sqls"].append(
            {
                "sql_text": props.get("sql_full_query"),
                "sql_id": props.get("id"),
                "props": props,
            }
        )
    return list(grouped.values())


def _embedding_attrs_for_table(table_id: str):
    return (
        select(
            s.column_attribute.c.name,
            s.column_attribute.c.description,
            s.column_attribute.c.term_name,
            s.column_attribute.c.source_column,
            s.catalog_column.c.sample_values,
            s.catalog_column.c.is_unique,
            s.catalog_table.c.id.label("table_id"),
            s.catalog_table.c.name.label("table_name"),
            s.column_attribute.c.id,
            s.catalog_schema.c.name.label("schema_name"),
        )
        .select_from(
            s.column_attribute.join(
                s.column__has_attribute,
                s.column__has_attribute.c.attribute_id == s.column_attribute.c.id,
            )
            .join(
                s.catalog_column,
                s.catalog_column.c.id == s.column__has_attribute.c.column_id,
            )
            .join(s.catalog_table, s.catalog_table.c.id == s.catalog_column.c.table_id)
            .join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
        )
        .where(
            s.catalog_table.c.id == table_id,
            s.column_attribute.c.source == SEMANTIC_SOURCE,
        )
    )


def fetch_terms_and_attributes_for_table(
    table_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(terms, attrs)`` written for one table — the inline embedding input."""
    terms = store().query_read(
        select(
            s.term.c.name,
            s.term.c.description,
            s.term.c.synonyms,
            s.term.c.id,
            func.array_agg(func.distinct(s.catalog_schema.c.name)).label(
                "schema_names"
            ),
        )
        .select_from(
            s.table__term.join(s.term, s.term.c.id == s.table__term.c.term_id)
            .join(s.catalog_table, s.catalog_table.c.id == s.table__term.c.table_id)
            .join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
        )
        .where(
            s.table__term.c.table_id == table_id,
            s.term.c.source == SEMANTIC_SOURCE,
        )
        .group_by(s.term.c.id)
    )
    attrs = store().query_read(_embedding_attrs_for_table(table_id))
    return [dict(r) for r in terms], [dict(r) for r in attrs]


def fetch_term_and_column_attributes_for_embedding(
    term_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """One Term and its ColumnAttributes, for a semantic VDB re-embed."""
    terms = store().query_read(
        select(
            s.term.c.name,
            s.term.c.description,
            s.term.c.synonyms,
            s.term.c.id,
            s.catalog_database.c.name.label("database_name"),
        )
        .select_from(
            s.term.outerjoin(s.table__term, s.table__term.c.term_id == s.term.c.id)
            .outerjoin(
                s.catalog_table, s.catalog_table.c.id == s.table__term.c.table_id
            )
            .outerjoin(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
            .outerjoin(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.term.c.id == term_id)
        # Ordered so a term spanning two databases reports the same one on
        # every call.
        .order_by(s.catalog_database.c.id)
        .limit(1)
    )
    if not terms:
        return None, []

    attrs = store().query_read(
        select(
            s.column_attribute.c.name,
            s.column_attribute.c.description,
            s.column_attribute.c.term_name,
            s.column_attribute.c.source_column,
            s.catalog_column.c.sample_values,
            s.catalog_column.c.is_unique,
            s.catalog_table.c.id.label("table_id"),
            s.catalog_table.c.name.label("table_name"),
            s.column_attribute.c.id,
        )
        .select_from(
            s.column_attribute__term.join(
                s.column_attribute,
                s.column_attribute.c.id == s.column_attribute__term.c.attribute_id,
            )
            .outerjoin(
                s.column__has_attribute,
                s.column__has_attribute.c.attribute_id == s.column_attribute.c.id,
            )
            .outerjoin(
                s.catalog_column,
                s.catalog_column.c.id == s.column__has_attribute.c.column_id,
            )
            # Outer, like the join above it: an attribute need not reach a
            # column, and an inner join here would drop those attributes
            # entirely rather than leaving their table fields null.
            .outerjoin(
                s.catalog_table,
                s.catalog_table.c.id == s.catalog_column.c.table_id,
            )
        )
        .where(s.column_attribute__term.c.term_id == term_id)
        .order_by(s.column_attribute.c.id)
    )
    return dict(terms[0]), [dict(r) for r in attrs]


def fetch_column_attribute_embedding_contexts_by_column_id(
    column_id: str,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """The Term contexts a column's sample-value update invalidates.

    Sample values are part of a ColumnAttribute's embedding text, so profiling a
    column stales every attribute on it and every term behind those.
    """
    rows = store().query_read(
        select(
            s.term.c.name.label("term_name"),
            s.term.c.description.label("term_description"),
            s.term.c.synonyms.label("term_synonyms"),
            s.term.c.id.label("term_id"),
            s.catalog_database.c.name.label("database_name"),
            s.column_attribute.c.name,
            s.column_attribute.c.description,
            s.column_attribute.c.term_name,
            s.column_attribute.c.source_column,
            s.catalog_column.c.sample_values,
            s.catalog_column.c.is_unique,
            s.catalog_table.c.id.label("table_id"),
            s.catalog_table.c.name.label("table_name"),
            s.column_attribute.c.id,
        )
        .select_from(
            s.catalog_column.join(
                s.column__has_attribute,
                s.column__has_attribute.c.column_id == s.catalog_column.c.id,
            )
            .join(
                s.column_attribute,
                s.column_attribute.c.id == s.column__has_attribute.c.attribute_id,
            )
            .join(
                s.column_attribute__term,
                s.column_attribute__term.c.attribute_id == s.column_attribute.c.id,
            )
            .join(s.term, s.term.c.id == s.column_attribute__term.c.term_id)
            .outerjoin(
                s.catalog_table, s.catalog_table.c.id == s.catalog_column.c.table_id
            )
            .outerjoin(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
            .outerjoin(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.catalog_column.c.id == column_id)
        .order_by(s.term.c.id, s.column_attribute.c.id)
    )

    contexts: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for row in rows:
        term_id = row["term_id"]
        if not term_id:
            continue
        if term_id not in contexts:
            contexts[term_id] = (
                {
                    "name": row["term_name"] or "",
                    "description": row["term_description"] or "",
                    "synonyms": row["term_synonyms"] or [],
                    "id": term_id,
                    "database_name": row["database_name"] or "",
                },
                [],
            )
        contexts[term_id][1].append(
            {
                "name": row["name"],
                "description": row["description"],
                "term_name": row["term_name"],
                "source_column": row["source_column"],
                "sample_values": row["sample_values"],
                "id": row["id"],
            }
        )
    return list(contexts.values())
