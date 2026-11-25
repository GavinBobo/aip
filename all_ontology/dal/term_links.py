# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shortest term-to-term link paths through the semantic graph."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import bindparam, literal, select

from all_ontology.catalog.constants import Edges, Labels
from all_ontology.dal import schema as s
from all_ontology.dal.datasources import fetch_col_table_contexts
from all_ontology.dal.session import store
from all_ontology.semantic.constants import (
    LABEL_COLUMN_ATTRIBUTE,
    LABEL_TERM,
    REL_HAS_ATTRIBUTE,
    REL_PROPERTY_OF,
    REL_REPRESENTS,
    REL_SEMANTIC_FK,
)

logger = logging.getLogger(__name__)


#: Path length ceiling, in **edges**. The longest chain worth showing is
#: ``Term -REPRESENTS- Table -CONTAINS- Column -SEMANTIC_FK- ColumnAttribute
#: -PROPERTY_OF- Term`` at four; ten leaves room for the join-table shapes
#: without letting a pathological catalog walk the whole graph.
_MAX_LINK_PATH_DEPTH = 10

#: Node kind (as carried through the traversal below) → the label the API reports.
_LINK_PATH_LABELS = {
    "term": LABEL_TERM,
    "table": Labels.TABLE,
    "column": Labels.COLUMN,
    "column_attribute": LABEL_COLUMN_ATTRIBUTE,
}


def _term_link_edges():
    """Every edge a term↔term path may walk, **undirected**, tagged with its type.

    Unlike :data:`~all_ontology.dal.schema.JOIN_PATH_EDGE_VIEW_SQL`, SEMANTIC_FK is
    emitted in *both* directions here. A term↔term edge already means the two
    terms genuinely share a table under :func:`fetch_term_table_pairs`'s rules,
    so tracing some real path between them cannot fabricate a link the way
    ``find_join_path``'s column-to-column search could -- it can only surface a
    chain that already exists. It has to be undirected for the join-table shape:
    when both terms reach their shared table only through SEMANTIC_FK, the path
    must step *against* one of the two stored (column -> attribute) directions
    whichever end it starts from.

    Not a database view, deliberately: one function reads it, and a view would
    have to be kept in step through a migration for no gain.
    """

    def leg(src_kind, src_id, dst_kind, dst_id, rel_type, source):
        return select(
            literal(src_kind).label("src_kind"),
            src_id.label("src_id"),
            literal(dst_kind).label("dst_kind"),
            dst_id.label("dst_id"),
            literal(rel_type).label("rel_type"),
        ).select_from(source)

    tt, ct, ca, cf, ha = (
        s.table__term,
        s.catalog_column,
        s.column_attribute__term,
        s.column__semantic_fk,
        s.column__has_attribute,
    )
    return (
        leg("table", tt.c.table_id, "term", tt.c.term_id, REL_REPRESENTS, tt)
        .union_all(
            leg("term", tt.c.term_id, "table", tt.c.table_id, REL_REPRESENTS, tt),
            leg("table", ct.c.table_id, "column", ct.c.id, Edges.CONTAINS, ct),
            leg("column", ct.c.id, "table", ct.c.table_id, Edges.CONTAINS, ct),
            leg(
                "column",
                ha.c.column_id,
                "column_attribute",
                ha.c.attribute_id,
                REL_HAS_ATTRIBUTE,
                ha,
            ),
            leg(
                "column_attribute",
                ha.c.attribute_id,
                "column",
                ha.c.column_id,
                REL_HAS_ATTRIBUTE,
                ha,
            ),
            leg(
                "column",
                cf.c.column_id,
                "column_attribute",
                cf.c.attribute_id,
                REL_SEMANTIC_FK,
                cf,
            ),
            leg(
                "column_attribute",
                cf.c.attribute_id,
                "column",
                cf.c.column_id,
                REL_SEMANTIC_FK,
                cf,
            ),
            leg(
                "column_attribute",
                ca.c.attribute_id,
                "term",
                ca.c.term_id,
                REL_PROPERTY_OF,
                ca,
            ),
            leg(
                "term",
                ca.c.term_id,
                "column_attribute",
                ca.c.attribute_id,
                REL_PROPERTY_OF,
                ca,
            ),
        )
        .subquery("term_link_edge")
    )


def _link_path_bfs(anchor_id: str, dest_id: str) -> list[dict[str, Any]] | None:
    """Shortest term-to-term path as a node list, or ``None`` when there is none.

    Level-at-a-time BFS with the visited set held in Python rather than as a
    recursive CTE: a CTE tracks visited nodes per *path*, so a hub attribute
    shared by hundreds of columns fans out exponentially. A shared visited set
    bounds the work by the size of the reachable component instead.

    Each entry of the returned list is ``{id, kind, relationship}``, where
    ``relationship`` is the edge type walked to *reach* that node -- ``None`` on
    the anchor, which nothing was walked to reach.
    """
    edges = _term_link_edges()
    expand = (
        select(edges.c.src_id, edges.c.dst_kind, edges.c.dst_id, edges.c.rel_type)
        .where(
            edges.c.src_id.in_(bindparam("frontier", expanding=True)),
            edges.c.dst_id.notin_(bindparam("visited", expanding=True)),
        )
        .distinct()
    )

    #: node id -> (kind, parent id, relationship walked from that parent)
    visited: dict[str, tuple[str, str | None, str | None]] = {
        anchor_id: ("term", None, None)
    }
    frontier = [anchor_id]

    for _ in range(_MAX_LINK_PATH_DEPTH):
        if not frontier:
            return None
        rows = store().query_read(
            expand, {"frontier": frontier, "visited": list(visited)}
        )
        next_frontier: list[str] = []
        for row in rows:
            node = row["dst_id"]
            if node in visited:
                # Two edges into the same node within one level: the first wins,
                # which is what BFS means. Without this the parent pointer could
                # be overwritten by a longer route found in the same batch.
                continue
            visited[node] = (row["dst_kind"], row["src_id"], row["rel_type"])
            next_frontier.append(node)
            if node == dest_id:
                path: list[dict[str, Any]] = []
                current: str | None = node
                while current is not None:
                    kind, parent, relationship = visited[current]
                    path.append(
                        {"id": current, "kind": kind, "relationship": relationship}
                    )
                    current = parent
                path.reverse()
                return path
        frontier = next_frontier

    logger.warning(
        "find_term_link_path: gave up after %s levels for %s -> %s",
        _MAX_LINK_PATH_DEPTH,
        anchor_id,
        dest_id,
    )
    return None


def _name_link_path_nodes(path: list[dict[str, Any]]) -> dict[str, str]:
    """``node id -> name`` for every node on the path, one query per kind."""
    by_kind = {
        "term": (s.term.c.id, s.term.c.name),
        "table": (s.catalog_table.c.id, s.catalog_table.c.name),
        "column": (s.catalog_column.c.id, s.catalog_column.c.name),
        "column_attribute": (s.column_attribute.c.id, s.column_attribute.c.name),
    }
    names: dict[str, str] = {}
    for kind, (id_column, name_column) in by_kind.items():
        ids = [node["id"] for node in path if node["kind"] == kind]
        if not ids:
            continue
        names.update(
            {
                row["id"]: row["name"]
                for row in store().query_read(
                    select(id_column.label("id"), name_column.label("name")).where(
                        id_column.in_(ids)
                    )
                )
            }
        )
    return names


def _enrich_catalog_path_nodes(path_nodes: list[dict[str, Any]]) -> None:
    """Attach catalog ids/names onto each Table/Column node, in place.

    The traversal never walks through a Schema or Database, so a Table/Column
    hop otherwise carries nothing beyond a bare id and name -- not enough for a
    client to expand it any further the way every other Table/Column expansion
    does (``expandTableNode``/``expandColumnNode`` in ``ExplorationView.tsx``
    need a Table's own database/schema ids, and a Column's own owning Table id).
    Best-effort: a failed lookup leaves those nodes without the extra fields,
    the same as if this were never called.
    """
    table_ids = list(
        {n["id"] for n in path_nodes if n.get("label") == Labels.TABLE and n.get("id")}
    )
    if table_ids:
        try:
            rows = store().query_read(
                select(
                    s.catalog_table.c.id.label("table_id"),
                    s.catalog_database.c.id.label("database_id"),
                    s.catalog_database.c.name.label("database_name"),
                    s.catalog_schema.c.id.label("schema_id"),
                    s.catalog_schema.c.name.label("schema_name"),
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
                .where(s.catalog_table.c.id.in_(table_ids))
            )
        except Exception:
            logger.warning(
                "find_term_link_path: table catalog lookup failed for %s",
                table_ids,
                exc_info=True,
            )
            rows = []
        by_table_id = {row["table_id"]: row for row in rows}
        for node in path_nodes:
            if node.get("label") != Labels.TABLE:
                continue
            info = by_table_id.get(node["id"])
            if info is not None:
                node["database_id"] = info["database_id"]
                node["database_name"] = info["database_name"]
                node["schema_id"] = info["schema_id"]
                node["schema_name"] = info["schema_name"]

    column_ids = list(
        {n["id"] for n in path_nodes if n.get("label") == Labels.COLUMN and n.get("id")}
    )
    if column_ids:
        contexts = fetch_col_table_contexts(column_ids)
        for node in path_nodes:
            if node.get("label") != Labels.COLUMN:
                continue
            info = contexts.get(node["id"])
            if info is not None:
                node.update(
                    {
                        key: info.get(key)
                        for key in (
                            "table_id",
                            "table_name",
                            "database_id",
                            "database_name",
                            "schema_id",
                            "schema_name",
                        )
                    }
                )


def find_term_link_path(term_a_id: str, term_b_id: str) -> list[dict[str, Any]]:
    """The shortest semantic path connecting two Terms, as ordered hop dicts.

    One level up from :func:`all_ontology.dal.attributes.find_join_path`'s
    column-to-column traversal: this walks term to term across whichever of
    REPRESENTS, CONTAINS, HAS_ATTRIBUTE, SEMANTIC_FK and PROPERTY_OF actually
    connects them -- the same links ``fetch_semantic_exploration_graph`` folds
    into one term↔term edge's collapsed ``relationship_types`` label, but
    returned here as the real ordered chain a client can graft and highlight,
    e.g. ``Term1 <-REPRESENTS- Table -CONTAINS-> Column -SEMANTIC_FK->
    ColumnAttribute -PROPERTY_OF-> Term2``.

    Returns, ordered from *term_a_id* to *term_b_id*::

        [{relationship, source: {id, name, label, ...},
                        target: {id, name, label, ...}}, ...]

    ``[]`` when the two ids are equal, either Term is missing, or nothing
    connects them -- which should not happen for a real Exploration graph edge,
    but guards a stale or hand-crafted request.
    """
    if not term_a_id or not term_b_id or term_a_id == term_b_id:
        return []

    try:
        path = _link_path_bfs(term_a_id, term_b_id)
    except Exception:
        logger.warning(
            "find_term_link_path: query failed for %s -> %s",
            term_a_id,
            term_b_id,
            exc_info=True,
        )
        return []
    if not path or len(path) < 2:
        return []

    names = _name_link_path_nodes(path)
    nodes = [
        {
            "id": node["id"],
            "name": names.get(node["id"], ""),
            "label": _LINK_PATH_LABELS[node["kind"]],
        }
        for node in path
    ]
    _enrich_catalog_path_nodes(nodes)
    return [
        {
            "relationship": path[index + 1]["relationship"],
            "source": nodes[index],
            "target": nodes[index + 1],
        }
        for index in range(len(nodes) - 1)
    ]
