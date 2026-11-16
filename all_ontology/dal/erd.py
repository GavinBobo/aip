# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-zone entity-relationship canvas.

Three things are deliberate here:

**A canvas is created lazily, on first read.** Zones are cheap and most of them
will never be drawn; creating an empty canvas in ``create_zone`` would leave a
row behind for every zone somebody made in Settings.

**Catalog nodes follow the zone, virtual nodes follow the drawing.** On every
read the canvas is reconciled with the zone: tables the zone no longer covers
lose their node (and its relationships), tables it gained get one. A node with
``table_id`` null came from an imported document and is left alone, because
nothing outside the drawing knows whether it should exist.

**Column names, not ids, on relationships.** An imported ``Ref`` names columns
by name, and a virtual table has no catalog columns to point at. Both endpoints
carry names, and the service layer checks that the two lists line up.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import aliased

from all_ontology.dal import schema as s
from all_ontology.dal.session import store, write_transaction
from all_ontology.dal.zones import zone_covers_table

#: Spacing of a freshly placed node. Wide enough for a long table name and tall
#: enough for a header plus a handful of columns without overlapping the node
#: below; the UI's own "auto arrange" refines this.
GRID_X = 360.0
GRID_Y = 300.0


def _canvas_row(zone_id: str) -> dict[str, Any] | None:
    rows = store().query_read(
        select(
            s.erd_canvas.c.id,
            s.erd_canvas.c.zone_id,
            s.erd_canvas.c.viewport,
            s.zone.c.name.label("zone_name"),
        )
        .select_from(s.erd_canvas.join(s.zone, s.zone.c.id == s.erd_canvas.c.zone_id))
        .where(s.erd_canvas.c.zone_id == zone_id)
    )
    return rows[0] if rows else None


def _create_canvas(zone_id: str) -> dict[str, Any]:
    rows = store().query_write(
        s.erd_canvas.insert()
        .values(zone_id=zone_id)
        .returning(s.erd_canvas.c.id, s.erd_canvas.c.zone_id, s.erd_canvas.c.viewport)
    )
    row = rows[0]
    zone = store().query_read(select(s.zone.c.name).where(s.zone.c.id == zone_id))
    row["zone_name"] = zone[0]["name"]
    return row


def _zone_covered_tables(zone_id: str) -> list[dict[str, Any]]:
    """Every catalog table the zone grants, at whichever grain it names it.

    The same rule the semantic layer and Exploration use — see
    :func:`all_ontology.dal.zones.zone_covers_table`.
    """
    rows = store().query_read(
        select(
            s.catalog_table.c.id.label("table_id"),
            s.catalog_table.c.name.label("table_name"),
            s.catalog_schema.c.name.label("schema_name"),
        )
        .select_from(
            s.catalog_table.join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            ).join(s.zone_target, zone_covers_table())
        )
        .where(s.zone_target.c.zone_id == zone_id)
        .distinct()
        .order_by(s.catalog_schema.c.name, s.catalog_table.c.name)
    )
    return [
        {
            "table_id": row["table_id"],
            "name": f"{row['schema_name']}.{row['table_name']}",
        }
        for row in rows
    ]


def _columns_by_table(
    table_ids: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """Catalog columns and primary keys for *table_ids*, keyed by table id."""
    if not table_ids:
        return {}, {}

    pk_rows = store().query_read(
        select(s.catalog_table.c.id, s.catalog_table.c.pk).where(
            s.catalog_table.c.id.in_(table_ids)
        )
    )
    primary_keys = {row["id"]: list(row["pk"] or []) for row in pk_rows}

    rows = store().query_read(
        select(
            s.catalog_column.c.table_id,
            s.catalog_column.c.name,
            s.catalog_column.c.data_type,
            s.catalog_column.c.is_unique,
            s.catalog_column.c.is_nullable,
        )
        .where(s.catalog_column.c.table_id.in_(table_ids))
        .order_by(
            s.catalog_column.c.table_id,
            s.catalog_column.c.ordinal_position.nulls_last(),
            s.catalog_column.c.name,
        )
    )
    columns: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        columns.setdefault(row["table_id"], []).append(
            {
                "name": row["name"],
                "data_type": row["data_type"],
                "is_unique": row["is_unique"],
                "is_nullable": row["is_nullable"],
            }
        )
    return columns, primary_keys


def _sync_nodes(canvas_id: str, zone_id: str) -> None:
    """Add a node for every newly covered table; drop nodes for lost tables."""
    covered = _zone_covered_tables(zone_id)
    covered_ids = {row["table_id"] for row in covered}

    existing = store().query_read(
        select(
            s.erd_node.c.id,
            s.erd_node.c.table_id,
            s.erd_node.c.x,
            s.erd_node.c.y,
            s.erd_node.c.hidden,
        ).where(s.erd_node.c.canvas_id == canvas_id)
    )
    # A hidden row is a tombstone: the table is still covered by the zone but
    # the drawing said no, so reconciliation must neither recreate nor delete it.
    existing_table_ids = {row["table_id"] for row in existing if row["table_id"]}

    missing = [row for row in covered if row["table_id"] not in existing_table_ids]
    stale = [
        row["id"]
        for row in existing
        if row["table_id"] is not None and row["table_id"] not in covered_ids
    ]

    with write_transaction():
        if stale:
            store().query_write(s.erd_node.delete().where(s.erd_node.c.id.in_(stale)))
        if missing:
            # Place new nodes under whatever is already drawn rather than at the
            # origin, so adding a table to a zone never lands it on top of a
            # diagram somebody arranged by hand.
            start_y = 0.0
            visible = [row for row in existing if not row["hidden"]]
            if visible:
                start_y = max(float(row["y"]) for row in visible) + GRID_Y
            cols = max(1, math.ceil(math.sqrt(len(missing))))
            for index, row in enumerate(missing):
                x = (index % cols) * GRID_X
                y = start_y + (index // cols) * GRID_Y
                store().query_write(
                    s.erd_node.insert().values(
                        canvas_id=canvas_id,
                        table_id=row["table_id"],
                        name=row["name"],
                        x=x,
                        y=y,
                    )
                )


def _node_rows(canvas_id: str) -> list[dict[str, Any]]:
    return store().query_read(
        select(
            s.erd_node.c.id,
            s.erd_node.c.table_id,
            s.erd_node.c.name,
            s.erd_node.c.x,
            s.erd_node.c.y,
            s.erd_node.c.collapsed,
            s.erd_node.c.columns,
            s.erd_node.c.indexes,
            s.erd_node.c.note,
        )
        .where(s.erd_node.c.canvas_id == canvas_id, s.erd_node.c.hidden.is_(False))
        .order_by(s.erd_node.c.name, s.erd_node.c.id)
    )


def _hidden_rows(canvas_id: str) -> list[dict[str, Any]]:
    return store().query_read(
        select(s.erd_node.c.id, s.erd_node.c.table_id, s.erd_node.c.name)
        .where(s.erd_node.c.canvas_id == canvas_id, s.erd_node.c.hidden.is_(True))
        .order_by(s.erd_node.c.name)
    )


def _relationship_rows(canvas_id: str) -> list[dict[str, Any]]:
    source = aliased(s.erd_node, name="source_node")
    target = aliased(s.erd_node, name="target_node")
    return store().query_read(
        select(
            s.erd_relationship.c.id,
            s.erd_relationship.c.source_node_id,
            s.erd_relationship.c.target_node_id,
            s.erd_relationship.c.source_columns,
            s.erd_relationship.c.target_columns,
            s.erd_relationship.c.cardinality,
            s.erd_relationship.c.label,
        )
        .select_from(
            s.erd_relationship.join(
                source, source.c.id == s.erd_relationship.c.source_node_id
            ).join(target, target.c.id == s.erd_relationship.c.target_node_id)
        )
        .where(
            s.erd_relationship.c.canvas_id == canvas_id,
            source.c.hidden.is_(False),
            target.c.hidden.is_(False),
        )
        .order_by(s.erd_relationship.c.created, s.erd_relationship.c.id)
    )


def _normalize_virtual_columns(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    columns: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        columns.append(
            {
                "name": str(item["name"]),
                "data_type": item.get("data_type"),
                "is_primary_key": bool(item.get("is_primary_key", False)),
                "is_unique": item.get("is_unique"),
                "is_nullable": item.get("is_nullable"),
                "note": _clean_note(item.get("note")),
            }
        )
    return columns


def _clean_note(raw: Any) -> str | None:
    """A column alias/description, or ``None`` when it says nothing."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _column_note_map(raw: Any) -> dict[str, str]:
    """``column name -> alias`` from a node's stored ``columns`` blob.

    Catalog-backed nodes keep only the modeller's per-column annotations in
    that blob: the column list itself comes from ``catalog_column``, so
    anything except ``note`` here is decoration left over from an import or a
    restore and is ignored on read.
    """
    if not isinstance(raw, list):
        return {}
    notes: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        note = _clean_note(item.get("note"))
        if note:
            notes[str(item["name"])] = note
    return notes


def _apply_column_notes(raw: Any, notes: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge ``name -> alias`` into a stored column list, keeping the order.

    An empty alias removes the note; a name that is not in the list yet is
    appended so a note can be written before the column exists (the catalog
    may still be ingesting).
    """
    columns = [
        dict(item)
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict) and item.get("name")
    ]
    by_name = {str(column["name"]): column for column in columns}
    for name, value in notes.items():
        key = str(name).strip()
        if not key:
            continue
        note = _clean_note(value)
        column = by_name.get(key)
        if column is None:
            if note is None:
                continue
            column = {"name": key}
            columns.append(column)
            by_name[key] = column
        if note is None:
            column.pop("note", None)
        else:
            column["note"] = note
    return columns


def _catalog_columns(
    table_id: str,
    catalog: dict[str, list[dict[str, Any]]],
    primary_keys: dict[str, list[str]],
    notes: dict[str, str],
) -> list[dict[str, Any]]:
    """The catalog's columns for one table, with the modeller's aliases on top."""
    pk = primary_keys.get(table_id, [])
    columns: list[dict[str, Any]] = []
    for column in catalog.get(table_id, []):
        item = {
            **column,
            "is_primary_key": column["name"] in pk,
            "note": notes.get(column["name"]) or None,
        }
        columns.append(item)
    return columns


def _normalize_indexes(raw: Any) -> list[dict[str, Any]]:
    """Keep only indexes that actually name a column."""
    if not isinstance(raw, list):
        return []
    indexes: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        columns = [
            str(column) for column in (item.get("columns") or []) if str(column).strip()
        ]
        if not columns:
            continue
        name = item.get("name")
        indexes.append(
            {
                "name": str(name) if name else None,
                "columns": columns,
                "unique": bool(item.get("unique", False)),
            }
        )
    return indexes


def _node_payload(
    row: dict[str, Any],
    *,
    catalog: dict[str, list[dict[str, Any]]] | None = None,
    primary_keys: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """One node as the API returns it.

    A catalog-backed node draws its columns from ``catalog_column`` and takes
    only the per-column aliases from the node's own ``columns`` blob; a
    diagram-only node keeps the whole column list it declared.
    """
    table_id = row["table_id"]
    if table_id:
        if catalog is None or primary_keys is None:
            catalog, primary_keys = _columns_by_table([table_id])
        columns = _catalog_columns(
            table_id,
            catalog,
            primary_keys,
            _column_note_map(row.get("columns")),
        )
    else:
        columns = _normalize_virtual_columns(row.get("columns"))
    return {
        "id": row["id"],
        "table_id": table_id,
        "name": row["name"],
        "x": float(row["x"]),
        "y": float(row["y"]),
        "collapsed": bool(row["collapsed"]),
        "columns": columns,
        "indexes": _normalize_indexes(row.get("indexes")),
        "note": row.get("note"),
    }


def _relationship_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_node_id": row["source_node_id"],
        "target_node_id": row["target_node_id"],
        "source_columns": list(row["source_columns"] or []),
        "target_columns": list(row["target_columns"] or []),
        "cardinality": row["cardinality"],
        "label": row["label"],
    }


def _note_rows(canvas_id: str) -> list[dict[str, Any]]:
    return store().query_read(
        select(
            s.erd_note.c.id,
            s.erd_note.c.text,
            s.erd_note.c.x,
            s.erd_note.c.y,
            s.erd_note.c.width,
            s.erd_note.c.height,
            s.erd_note.c.color,
        )
        .where(s.erd_note.c.canvas_id == canvas_id)
        .order_by(s.erd_note.c.created, s.erd_note.c.id)
    )


def _note_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "x": float(row["x"]),
        "y": float(row["y"]),
        "width": float(row["width"]),
        "height": float(row["height"]),
        "color": row["color"],
    }


def _area_rows(canvas_id: str) -> list[dict[str, Any]]:
    return store().query_read(
        select(
            s.erd_area.c.id,
            s.erd_area.c.name,
            s.erd_area.c.color,
            s.erd_area.c.x,
            s.erd_area.c.y,
            s.erd_area.c.width,
            s.erd_area.c.height,
        )
        .where(s.erd_area.c.canvas_id == canvas_id)
        .order_by(s.erd_area.c.created, s.erd_area.c.id)
    )


def _area_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "color": row["color"],
        "x": float(row["x"]),
        "y": float(row["y"]),
        "width": float(row["width"]),
        "height": float(row["height"]),
    }


def _build_payload(canvas: dict[str, Any]) -> dict[str, Any]:
    canvas_id = canvas["id"]
    node_rows = _node_rows(canvas_id)
    catalog_ids = [row["table_id"] for row in node_rows if row["table_id"]]
    catalog_columns, primary_keys = _columns_by_table(catalog_ids)

    nodes: list[dict[str, Any]] = []
    for row in node_rows:
        nodes.append(
            _node_payload(row, catalog=catalog_columns, primary_keys=primary_keys)
        )

    return {
        "id": canvas_id,
        "zone_id": canvas["zone_id"],
        "zone_name": canvas.get("zone_name"),
        "viewport": canvas.get("viewport") or {"x": 0.0, "y": 0.0, "zoom": 1.0},
        "nodes": nodes,
        "relationships": [
            _relationship_payload(row) for row in _relationship_rows(canvas_id)
        ],
        "hidden_nodes": [
            {"id": row["id"], "table_id": row["table_id"], "name": row["name"]}
            for row in _hidden_rows(canvas_id)
        ],
        "notes": [_note_payload(row) for row in _note_rows(canvas_id)],
        "areas": [_area_payload(row) for row in _area_rows(canvas_id)],
    }


def get_or_create_canvas(zone_id: str) -> dict[str, Any] | None:
    """The zone's canvas, creating it and its table nodes on first open.

    Returns ``None`` when no zone has that id — the route answers 404 rather
    than inventing a canvas for a scope that does not exist.
    """
    canvas = _canvas_row(zone_id)
    if canvas is None:
        zone_exists = store().query_read(
            select(s.zone.c.id).where(s.zone.c.id == zone_id)
        )
        if not zone_exists:
            return None
        canvas = _create_canvas(zone_id)

    _sync_nodes(canvas["id"], zone_id)
    return _build_payload(canvas)


def get_canvas(zone_id: str) -> dict[str, Any] | None:
    """The canvas as it stands, without reconciling it against the zone."""
    canvas = _canvas_row(zone_id)
    return _build_payload(canvas) if canvas is not None else None


def update_viewport(zone_id: str, viewport: dict[str, Any]) -> dict[str, Any] | None:
    """Persist pan/zoom for a canvas. ``None`` when the canvas does not exist."""
    rows = store().query_write(
        s.erd_canvas.update()
        .where(s.erd_canvas.c.zone_id == zone_id)
        .values(viewport=viewport)
        .returning(s.erd_canvas.c.zone_id, s.erd_canvas.c.viewport)
    )
    if not rows:
        return None
    return {"zone_id": rows[0]["zone_id"], "viewport": rows[0]["viewport"]}


def update_node(
    node_id: str,
    *,
    x: float | None,
    y: float | None,
    collapsed: bool | None,
    name: str | None = None,
    columns: list[dict[str, Any]] | None = None,
    column_notes: dict[str, Any] | None = None,
    indexes: list[dict[str, Any]] | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    """Move, collapse, or edit one node. Unspecified fields are left alone.

    Only diagram-only tables may be renamed or have their columns rewritten:
    a catalog-backed node mirrors the source database, and editing it here
    would show a schema the database does not have. Raises ``ValueError`` in
    that case.

    ``column_notes`` is the exception: a per-column alias is documentation
    rather than schema, so it is accepted on either kind of node. On a
    catalog-backed node it is the only way to attach a note to a column.
    """
    values: dict[str, Any] = {}
    if x is not None:
        values["x"] = float(x)
    if y is not None:
        values["y"] = float(y)
    if collapsed is not None:
        values["collapsed"] = collapsed
    # A note is documentation, not schema, so it is allowed on either kind of
    # node — unlike a rename or a column rewrite.
    if note is not None:
        values["note"] = note.strip() or None
    if (
        name is not None
        or columns is not None
        or column_notes is not None
        or indexes is not None
    ):
        owner = store().query_read(
            select(s.erd_node.c.table_id, s.erd_node.c.columns).where(
                s.erd_node.c.id == node_id
            )
        )
        if not owner:
            return None
        if owner[0]["table_id"] is not None and (
            columns is not None or name is not None or indexes is not None
        ):
            raise ValueError(
                "Only tables that exist just on the canvas can be edited; "
                "catalog tables mirror the source database"
            )
        if name is not None:
            trimmed = name.strip()
            if not trimmed:
                raise ValueError("A table needs a name")
            values["name"] = trimmed
        if columns is not None:
            values["columns"] = columns
        if column_notes is not None:
            # Aliases land in the same JSONB blob the virtual columns use; on a
            # catalog node only the `note` key of each entry is ever read.
            base = columns if columns is not None else owner[0].get("columns")
            values["columns"] = _apply_column_notes(base, column_notes)
        if indexes is not None:
            values["indexes"] = _normalize_indexes(indexes)

    columns = (
        s.erd_node.c.id,
        s.erd_node.c.table_id,
        s.erd_node.c.name,
        s.erd_node.c.x,
        s.erd_node.c.y,
        s.erd_node.c.collapsed,
        s.erd_node.c.columns,
        s.erd_node.c.indexes,
        s.erd_node.c.note,
    )
    if not values:
        rows = store().query_read(select(*columns).where(s.erd_node.c.id == node_id))
    else:
        rows = store().query_write(
            s.erd_node.update()
            .where(s.erd_node.c.id == node_id)
            .values(**values)
            .returning(*columns)
        )
    return _node_payload(rows[0]) if rows else None


def create_node(
    *,
    canvas_id: str,
    name: str,
    table_id: str | None,
    columns: list[dict[str, Any]] | None,
    x: float,
    y: float,
    indexes: list[dict[str, Any]] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Add a node by hand — a virtual table, or a table the zone does not cover."""
    rows = store().query_write(
        s.erd_node.insert()
        .values(
            canvas_id=canvas_id,
            table_id=table_id,
            name=name,
            x=float(x),
            y=float(y),
            columns=columns or None,
            indexes=_normalize_indexes(indexes) or None,
            note=note,
        )
        .returning(
            s.erd_node.c.id,
            s.erd_node.c.table_id,
            s.erd_node.c.name,
            s.erd_node.c.x,
            s.erd_node.c.y,
            s.erd_node.c.collapsed,
            s.erd_node.c.columns,
            s.erd_node.c.indexes,
            s.erd_node.c.note,
        )
    )
    return _node_payload(rows[0])


def delete_node(node_id: str) -> bool:
    """Remove a node from the canvas.

    A catalog-backed node is *hidden*, not deleted: its zone still covers the
    table, so a delete would be undone by the next reconciliation. A virtual
    node has no such owner and is deleted outright.
    """
    rows = store().query_read(
        select(s.erd_node.c.table_id).where(s.erd_node.c.id == node_id)
    )
    if not rows:
        return False
    if rows[0]["table_id"] is not None:
        store().query_write(
            s.erd_node.update().where(s.erd_node.c.id == node_id).values(hidden=True)
        )
        return True
    store().query_write(s.erd_node.delete().where(s.erd_node.c.id == node_id))
    return True


def restore_node(node_id: str) -> dict[str, Any] | None:
    """Put a hidden catalog table back on the canvas."""
    rows = store().query_write(
        s.erd_node.update()
        .where(s.erd_node.c.id == node_id, s.erd_node.c.hidden.is_(True))
        .values(hidden=False)
        .returning(
            s.erd_node.c.id,
            s.erd_node.c.table_id,
            s.erd_node.c.name,
            s.erd_node.c.x,
            s.erd_node.c.y,
            s.erd_node.c.collapsed,
            s.erd_node.c.columns,
            s.erd_node.c.note,
        )
    )
    return _node_payload(rows[0]) if rows else None


def _validate_relationship(
    *,
    canvas_id: str,
    source_node_id: str,
    target_node_id: str,
    source_columns: list[str],
    target_columns: list[str],
    cardinality: str,
) -> None:
    if source_node_id == target_node_id:
        raise ValueError("A relationship needs two different tables")
    if cardinality not in s.ERD_CARDINALITIES:
        raise ValueError(f"Unknown cardinality {cardinality!r}")
    if len(source_columns) != len(target_columns):
        raise ValueError("source_columns and target_columns must have the same length")

    rows = store().query_read(
        select(s.erd_node.c.id, s.erd_node.c.canvas_id).where(
            s.erd_node.c.id.in_([source_node_id, target_node_id])
        )
    )
    by_id = {row["id"]: row["canvas_id"] for row in rows}
    if source_node_id not in by_id or target_node_id not in by_id:
        raise ValueError("Both nodes must exist")
    if by_id[source_node_id] != canvas_id or by_id[target_node_id] != canvas_id:
        raise ValueError("Both nodes must belong to this canvas")


def create_relationship(
    *,
    canvas_id: str,
    source_node_id: str,
    target_node_id: str,
    source_columns: list[str],
    target_columns: list[str],
    cardinality: str,
    label: str | None,
) -> dict[str, Any]:
    """Draw one relationship. Raises ``ValueError`` on an invalid pair."""
    _validate_relationship(
        canvas_id=canvas_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        source_columns=source_columns,
        target_columns=target_columns,
        cardinality=cardinality,
    )
    rows = store().query_write(
        s.erd_relationship.insert()
        .values(
            canvas_id=canvas_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_columns=source_columns,
            target_columns=target_columns,
            cardinality=cardinality,
            label=label,
        )
        .returning(
            s.erd_relationship.c.id,
            s.erd_relationship.c.source_node_id,
            s.erd_relationship.c.target_node_id,
            s.erd_relationship.c.source_columns,
            s.erd_relationship.c.target_columns,
            s.erd_relationship.c.cardinality,
            s.erd_relationship.c.label,
        )
    )
    return _relationship_payload(rows[0])


def update_relationship(
    rel_id: str,
    *,
    cardinality: str | None,
    label: str | None,
    source_columns: list[str] | None,
    target_columns: list[str] | None,
) -> dict[str, Any] | None:
    """Edit a relationship's cardinality, label or column pair."""
    existing = store().query_read(
        select(
            s.erd_relationship.c.canvas_id,
            s.erd_relationship.c.source_node_id,
            s.erd_relationship.c.target_node_id,
            s.erd_relationship.c.source_columns,
            s.erd_relationship.c.target_columns,
            s.erd_relationship.c.cardinality,
        ).where(s.erd_relationship.c.id == rel_id)
    )
    if not existing:
        return None
    row = existing[0]

    next_source = (
        list(source_columns)
        if source_columns is not None
        else list(row["source_columns"] or [])
    )
    next_target = (
        list(target_columns)
        if target_columns is not None
        else list(row["target_columns"] or [])
    )
    next_cardinality = cardinality or row["cardinality"]

    _validate_relationship(
        canvas_id=row["canvas_id"],
        source_node_id=row["source_node_id"],
        target_node_id=row["target_node_id"],
        source_columns=next_source,
        target_columns=next_target,
        cardinality=next_cardinality,
    )

    values: dict[str, Any] = {
        "source_columns": next_source,
        "target_columns": next_target,
        "cardinality": next_cardinality,
    }
    if label is not None:
        values["label"] = label
    rows = store().query_write(
        s.erd_relationship.update()
        .where(s.erd_relationship.c.id == rel_id)
        .values(**values)
        .returning(
            s.erd_relationship.c.id,
            s.erd_relationship.c.source_node_id,
            s.erd_relationship.c.target_node_id,
            s.erd_relationship.c.source_columns,
            s.erd_relationship.c.target_columns,
            s.erd_relationship.c.cardinality,
            s.erd_relationship.c.label,
        )
    )
    return _relationship_payload(rows[0])


def delete_relationship(rel_id: str) -> bool:
    rows = store().query_write(
        s.erd_relationship.delete()
        .where(s.erd_relationship.c.id == rel_id)
        .returning(s.erd_relationship.c.id)
    )
    return bool(rows)


def create_note(
    *,
    canvas_id: str,
    text: str = "",
    x: float = 0,
    y: float = 0,
    color: str | None = None,
) -> dict[str, Any]:
    """Add a sticky note to a canvas."""
    rows = store().query_write(
        s.erd_note.insert()
        .values(canvas_id=canvas_id, text=text, x=float(x), y=float(y), color=color)
        .returning(
            s.erd_note.c.id,
            s.erd_note.c.text,
            s.erd_note.c.x,
            s.erd_note.c.y,
            s.erd_note.c.width,
            s.erd_note.c.height,
            s.erd_note.c.color,
        )
    )
    return _note_payload(rows[0])


def update_note(
    note_id: str,
    *,
    text: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
) -> dict[str, Any] | None:
    """Move or edit a sticky note. Omitted fields are left alone."""
    values: dict[str, Any] = {}
    if text is not None:
        values["text"] = text
    if x is not None:
        values["x"] = float(x)
    if y is not None:
        values["y"] = float(y)
    if width is not None:
        values["width"] = max(120.0, float(width))
    if height is not None:
        values["height"] = max(80.0, float(height))
    if color is not None:
        values["color"] = color or None

    columns = (
        s.erd_note.c.id,
        s.erd_note.c.text,
        s.erd_note.c.x,
        s.erd_note.c.y,
        s.erd_note.c.width,
        s.erd_note.c.height,
        s.erd_note.c.color,
    )
    if not values:
        rows = store().query_read(select(*columns).where(s.erd_note.c.id == note_id))
    else:
        rows = store().query_write(
            s.erd_note.update()
            .where(s.erd_note.c.id == note_id)
            .values(**values)
            .returning(*columns)
        )
    return _note_payload(rows[0]) if rows else None


def delete_note(note_id: str) -> bool:
    rows = store().query_write(
        s.erd_note.delete().where(s.erd_note.c.id == note_id).returning(s.erd_note.c.id)
    )
    return bool(rows)


def replace_notes(canvas_id: str, notes: list[dict[str, Any]]) -> None:
    """Replace every note on a canvas, used by a JSON import."""
    with write_transaction():
        store().query_write(
            s.erd_note.delete().where(s.erd_note.c.canvas_id == canvas_id)
        )
        for note in notes:
            store().query_write(
                s.erd_note.insert().values(
                    canvas_id=canvas_id,
                    text=note.get("text") or "",
                    x=float(note.get("x", 0)),
                    y=float(note.get("y", 0)),
                    width=max(120.0, float(note.get("width", 240))),
                    height=max(80.0, float(note.get("height", 140))),
                    color=note.get("color"),
                )
            )


def create_area(
    *,
    canvas_id: str,
    name: str = "",
    color: str | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 520,
    height: float = 380,
) -> dict[str, Any]:
    """Add a grouping rectangle to a canvas."""
    rows = store().query_write(
        s.erd_area.insert()
        .values(
            canvas_id=canvas_id,
            name=name,
            color=color,
            x=float(x),
            y=float(y),
            width=max(200.0, float(width)),
            height=max(140.0, float(height)),
        )
        .returning(
            s.erd_area.c.id,
            s.erd_area.c.name,
            s.erd_area.c.color,
            s.erd_area.c.x,
            s.erd_area.c.y,
            s.erd_area.c.width,
            s.erd_area.c.height,
        )
    )
    return _area_payload(rows[0])


def update_area(
    area_id: str,
    *,
    name: str | None = None,
    color: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any] | None:
    """Move, resize, rename or recolour a grouping rectangle."""
    values: dict[str, Any] = {}
    if name is not None:
        values["name"] = name
    if color is not None:
        values["color"] = color or None
    if x is not None:
        values["x"] = float(x)
    if y is not None:
        values["y"] = float(y)
    if width is not None:
        values["width"] = max(200.0, float(width))
    if height is not None:
        values["height"] = max(140.0, float(height))

    columns = (
        s.erd_area.c.id,
        s.erd_area.c.name,
        s.erd_area.c.color,
        s.erd_area.c.x,
        s.erd_area.c.y,
        s.erd_area.c.width,
        s.erd_area.c.height,
    )
    if not values:
        rows = store().query_read(select(*columns).where(s.erd_area.c.id == area_id))
    else:
        rows = store().query_write(
            s.erd_area.update()
            .where(s.erd_area.c.id == area_id)
            .values(**values)
            .returning(*columns)
        )
    return _area_payload(rows[0]) if rows else None


def delete_area(area_id: str) -> bool:
    rows = store().query_write(
        s.erd_area.delete().where(s.erd_area.c.id == area_id).returning(s.erd_area.c.id)
    )
    return bool(rows)


def replace_areas(canvas_id: str, areas: list[dict[str, Any]]) -> None:
    """Replace every grouping rectangle, used by a JSON import."""
    with write_transaction():
        store().query_write(
            s.erd_area.delete().where(s.erd_area.c.canvas_id == canvas_id)
        )
        for area in areas:
            store().query_write(
                s.erd_area.insert().values(
                    canvas_id=canvas_id,
                    name=area.get("name") or "",
                    color=area.get("color"),
                    x=float(area.get("x", 0)),
                    y=float(area.get("y", 0)),
                    width=max(200.0, float(area.get("width", 520))),
                    height=max(140.0, float(area.get("height", 380))),
                )
            )


def _version_summary(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = row["snapshot"] or {}
    created = row["created"]
    return {
        "id": row["id"],
        "label": row["label"],
        "created": created.isoformat() if created is not None else None,
        "created_by": row["created_by"],
        "node_count": len(snapshot.get("nodes") or []),
        "relationship_count": len(snapshot.get("relationships") or []),
    }


def create_version(
    zone_id: str, label: str, created_by: str | None = None
) -> dict[str, Any] | None:
    """Snapshot the canvas as it stands. ``None`` when the zone has no canvas."""
    canvas = _canvas_row(zone_id)
    if canvas is None:
        return None
    payload = _build_payload(canvas)
    snapshot = {
        "nodes": payload["nodes"],
        "relationships": payload["relationships"],
        "notes": payload["notes"],
        "areas": payload["areas"],
    }
    rows = store().query_write(
        s.erd_canvas_version.insert()
        .values(
            canvas_id=canvas["id"],
            label=label.strip(),
            snapshot=snapshot,
            created_by=created_by,
        )
        .returning(
            s.erd_canvas_version.c.id,
            s.erd_canvas_version.c.label,
            s.erd_canvas_version.c.created,
            s.erd_canvas_version.c.created_by,
            s.erd_canvas_version.c.snapshot,
        )
    )
    return _version_summary(rows[0])


def list_versions(zone_id: str) -> list[dict[str, Any]]:
    """Saved versions of a zone's canvas, newest first."""
    canvas = _canvas_row(zone_id)
    if canvas is None:
        return []
    rows = store().query_read(
        select(
            s.erd_canvas_version.c.id,
            s.erd_canvas_version.c.label,
            s.erd_canvas_version.c.created,
            s.erd_canvas_version.c.created_by,
            s.erd_canvas_version.c.snapshot,
        )
        .where(s.erd_canvas_version.c.canvas_id == canvas["id"])
        .order_by(s.erd_canvas_version.c.created.desc())
    )
    return [_version_summary(row) for row in rows]


def restore_version(version_id: str) -> dict[str, Any] | None:
    """Put a saved version back on the canvas, ids and all."""
    rows = store().query_read(
        select(
            s.erd_canvas_version.c.canvas_id,
            s.erd_canvas_version.c.snapshot,
        ).where(s.erd_canvas_version.c.id == version_id)
    )
    if not rows:
        return None
    snapshot = rows[0]["snapshot"] or {}
    return restore_canvas_state(
        rows[0]["canvas_id"],
        snapshot.get("nodes") or [],
        snapshot.get("relationships") or [],
        snapshot.get("notes") or [],
        snapshot.get("areas") or [],
    )


def delete_version(version_id: str) -> bool:
    rows = store().query_write(
        s.erd_canvas_version.delete()
        .where(s.erd_canvas_version.c.id == version_id)
        .returning(s.erd_canvas_version.c.id)
    )
    return bool(rows)


def replace_canvas_contents(
    canvas_id: str,
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace every node and relationship with an imported document.

    Relationships address nodes by name because that is all an exchanged
    document carries; a relationship naming a node that is not in *nodes* is
    dropped, and the caller reports it.
    """
    with write_transaction():
        store().query_write(
            s.erd_relationship.delete().where(
                s.erd_relationship.c.canvas_id == canvas_id
            )
        )
        store().query_write(
            s.erd_node.delete().where(s.erd_node.c.canvas_id == canvas_id)
        )

        node_ids: dict[str, str] = {}
        for node in nodes:
            rows = store().query_write(
                s.erd_node.insert()
                .values(
                    canvas_id=canvas_id,
                    table_id=node.get("table_id"),
                    name=node["name"],
                    x=float(node.get("x", 0)),
                    y=float(node.get("y", 0)),
                    collapsed=bool(node.get("collapsed", False)),
                    columns=node.get("columns") or None,
                    indexes=_normalize_indexes(node.get("indexes")) or None,
                    note=node.get("note"),
                )
                .returning(s.erd_node.c.id)
            )
            node_ids[node["name"]] = rows[0]["id"]

        for rel in relationships:
            source_id = node_ids.get(rel["source"])
            target_id = node_ids.get(rel["target"])
            if source_id is None or target_id is None or source_id == target_id:
                continue
            store().query_write(
                s.erd_relationship.insert().values(
                    canvas_id=canvas_id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    source_columns=rel.get("source_columns") or [],
                    target_columns=rel.get("target_columns") or [],
                    cardinality=rel.get("cardinality", "many-to-one"),
                    label=rel.get("label"),
                )
            )

    canvas = store().query_read(
        select(
            s.erd_canvas.c.id, s.erd_canvas.c.zone_id, s.erd_canvas.c.viewport
        ).where(s.erd_canvas.c.id == canvas_id)
    )
    return _build_payload(canvas[0])


def restore_canvas_state(
    canvas_id: str,
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None = None,
    areas: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Replace the canvas with a client-side snapshot for undo/redo.

    Ids are preserved exactly as sent, which is what makes the browser's
    history stack refer to the same nodes after a round trip. ``None`` when the
    canvas does not exist.
    """
    exists = store().query_read(
        select(s.erd_canvas.c.id).where(s.erd_canvas.c.id == canvas_id)
    )
    if not exists:
        return None

    # Snapshots only carry what the browser can see, so hidden tombstones have
    # to survive the rebuild or undoing anything would resurrect tables the
    # user removed from the canvas.
    hidden = store().query_read(
        select(
            s.erd_node.c.id,
            s.erd_node.c.table_id,
            s.erd_node.c.name,
            s.erd_node.c.x,
            s.erd_node.c.y,
            s.erd_node.c.collapsed,
            s.erd_node.c.columns,
            s.erd_node.c.indexes,
            s.erd_node.c.note,
        ).where(s.erd_node.c.canvas_id == canvas_id, s.erd_node.c.hidden.is_(True))
    )
    # A snapshot that still contains a hidden node is an undo of the removal
    # itself: the snapshot wins, so the tombstone is not re-inserted beside it.
    snapshot_ids = {node["id"] for node in nodes if node.get("id")}
    hidden = [row for row in hidden if row["id"] not in snapshot_ids]

    with write_transaction():
        store().query_write(
            s.erd_relationship.delete().where(
                s.erd_relationship.c.canvas_id == canvas_id
            )
        )
        store().query_write(
            s.erd_node.delete().where(s.erd_node.c.canvas_id == canvas_id)
        )

        node_ids: set[str] = set()
        for node in nodes:
            values = {
                "canvas_id": canvas_id,
                "table_id": node.get("table_id"),
                "name": node["name"],
                "x": float(node.get("x", 0)),
                "y": float(node.get("y", 0)),
                "collapsed": bool(node.get("collapsed", False)),
                "columns": node.get("columns") or None,
                "indexes": _normalize_indexes(node.get("indexes")) or None,
                "note": node.get("note"),
            }
            if node.get("id"):
                values["id"] = node["id"]
            rows = store().query_write(
                s.erd_node.insert().values(**values).returning(s.erd_node.c.id)
            )
            node_ids.add(rows[0]["id"])

        for rel in relationships:
            if (
                rel["source_node_id"] not in node_ids
                or rel["target_node_id"] not in node_ids
            ):
                continue
            values = {
                "canvas_id": canvas_id,
                "source_node_id": rel["source_node_id"],
                "target_node_id": rel["target_node_id"],
                "source_columns": rel.get("source_columns") or [],
                "target_columns": rel.get("target_columns") or [],
                "cardinality": rel.get("cardinality", "many-to-one"),
                "label": rel.get("label"),
            }
            if rel.get("id"):
                values["id"] = rel["id"]
            store().query_write(s.erd_relationship.insert().values(**values))

        for row in hidden:
            store().query_write(
                s.erd_node.insert().values(
                    id=row["id"],
                    canvas_id=canvas_id,
                    table_id=row["table_id"],
                    name=row["name"],
                    x=row["x"],
                    y=row["y"],
                    collapsed=row["collapsed"],
                    columns=row["columns"],
                    indexes=row["indexes"],
                    note=row["note"],
                    hidden=True,
                )
            )

        store().query_write(
            s.erd_note.delete().where(s.erd_note.c.canvas_id == canvas_id)
        )
        for note in notes or []:
            values = {
                "canvas_id": canvas_id,
                "text": note.get("text") or "",
                "x": float(note.get("x", 0)),
                "y": float(note.get("y", 0)),
                "width": max(120.0, float(note.get("width", 240))),
                "height": max(80.0, float(note.get("height", 140))),
                "color": note.get("color"),
            }
            if note.get("id"):
                values["id"] = note["id"]
            store().query_write(s.erd_note.insert().values(**values))

        store().query_write(
            s.erd_area.delete().where(s.erd_area.c.canvas_id == canvas_id)
        )
        for area in areas or []:
            values = {
                "canvas_id": canvas_id,
                "name": area.get("name") or "",
                "color": area.get("color"),
                "x": float(area.get("x", 0)),
                "y": float(area.get("y", 0)),
                "width": max(200.0, float(area.get("width", 520))),
                "height": max(140.0, float(area.get("height", 380))),
            }
            if area.get("id"):
                values["id"] = area["id"]
            store().query_write(s.erd_area.insert().values(**values))

    canvas = store().query_read(
        select(
            s.erd_canvas.c.id, s.erd_canvas.c.zone_id, s.erd_canvas.c.viewport
        ).where(s.erd_canvas.c.id == canvas_id)
    )
    return _build_payload(canvas[0])
