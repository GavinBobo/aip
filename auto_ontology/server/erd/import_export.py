# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Import and export for the ER canvas.
The two formats answer different questions. JSON is the canvas itself - nodes
with positions, diagram-only tables, cardinalities - so a restore is exact.
DBML is the exchange format every modelling tool speaks: it carries tables,
columns and references, and nothing about where they were drawn.
"""

from __future__ import annotations
import json
import math
import re
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from auto_ontology.dal import erd as dal
from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store
from auto_ontology.server.erd.dbml import DbmlParseError, export_dbml, parse_dbml
from auto_ontology.server.erd.ddl import export_sql, parse_sql
from auto_ontology.server.erd.router import canvas_or_404
from auto_ontology.server.erd.schemas import ImportRequest
from auto_ontology.server.responses import ErdExportResponse, ErdImportResponse

router = APIRouter()
#: Spacing used when a DBML document carries no positions (it never does).
_GRID_X = 360.0
_GRID_Y = 300.0


def _existing_nodes_by_name(canvas: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"].lower(): node for node in canvas["nodes"]}


def _catalog_table_ids(table_ids: list[str]) -> set[str]:
    if not table_ids:
        return set()
    rows = store().query_read(
        select(s.catalog_table.c.id).where(s.catalog_table.c.id.in_(table_ids))
    )
    return {row["id"] for row in rows}


def _coordinate(
    value: Any, field: str, name: str, warnings: list[str]
) -> float:
    """A node's *field* position, or 0 when the document's value is unusable.

    The document is user-supplied, so ``"x": "left"`` has to become a warning
    rather than a ``ValueError`` out of ``float()`` — that reached the client as
    a 500 and made the import look like a server fault.
    """
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        warnings.append(f"table {name!r}: {field} {value!r} is not a number; using 0")
        return 0.0
    if not math.isfinite(number):
        warnings.append(f"table {name!r}: {field} {value!r} is not finite; using 0")
        return 0.0
    return number


def _normalise_import_nodes(
    raw_nodes: list[dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Attach catalog ids where a name matches, and validate the rest."""
    known_ids = _catalog_table_ids(
        [node["table_id"] for node in raw_nodes if node.get("table_id")]
    )
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            warnings.append("a node without a name was skipped")
            continue
        key = name.lower()
        if key in seen:
            warnings.append(f"duplicate table {name!r} was skipped")
            continue
        seen.add(key)
        table_id = raw.get("table_id")
        if table_id and table_id not in known_ids:
            warnings.append(
                f"table id {table_id!r} is not in the catalog; imported as a virtual table"
            )
            table_id = None
        if not table_id and key in existing and existing[key].get("table_id"):
            table_id = existing[key]["table_id"]
        columns = raw.get("columns")
        if columns is not None and not isinstance(columns, list):
            warnings.append(
                f"table {name!r}: columns must be a list, the value was ignored"
            )
            columns = None
        indexes = raw.get("indexes")
        if indexes is not None and not isinstance(indexes, list):
            warnings.append(
                f"table {name!r}: indexes must be a list, the value was ignored"
            )
            indexes = None
        nodes.append(
            {
                "name": name,
                "table_id": table_id,
                "x": _coordinate(raw.get("x"), "x", name, warnings),
                "y": _coordinate(raw.get("y"), "y", name, warnings),
                "collapsed": bool(raw.get("collapsed", False)),
                "columns": columns or None,
                "indexes": indexes or None,
                "note": raw.get("note"),
            }
        )
    return nodes


def _import_json(
    canvas: dict[str, Any], content: str, warnings: list[str]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    try:
        document = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON at line {exc.lineno}: {exc.msg}"
        ) from exc
    if not isinstance(document, dict):
        raise HTTPException(
            status_code=400, detail="The document must be a JSON object"
        )
    raw_nodes = document.get("nodes") or []
    raw_relationships = document.get("relationships") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_relationships, list):
        raise HTTPException(
            status_code=400, detail="'nodes' and 'relationships' must be lists"
        )
    nodes = _normalise_import_nodes(
        raw_nodes, _existing_nodes_by_name(canvas), warnings
    )
    relationships: list[dict[str, Any]] = []
    for raw in raw_relationships:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        cardinality = raw.get("cardinality") or "many-to-one"
        if cardinality not in s.ERD_CARDINALITIES:
            warnings.append(
                f"relationship {source} -> {target}: unknown cardinality "
                f"{cardinality!r}, using many-to-one"
            )
            cardinality = "many-to-one"
        relationships.append(
            {
                "source": source,
                "target": target,
                "source_columns": list(raw.get("source_columns") or []),
                "target_columns": list(raw.get("target_columns") or []),
                "cardinality": cardinality,
                "label": raw.get("label"),
            }
        )
    raw_notes = document.get("notes") or []
    notes = (
        [note for note in raw_notes if isinstance(note, dict)]
        if isinstance(raw_notes, list)
        else []
    )
    raw_areas = document.get("areas") or []
    areas = (
        [area for area in raw_areas if isinstance(area, dict)]
        if isinstance(raw_areas, list)
        else []
    )
    return nodes, relationships, notes, areas


def _import_dbml(
    canvas: dict[str, Any], content: str, warnings: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        parsed_nodes, parsed_relationships, dbml_warnings = parse_dbml(content)
    except DbmlParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    warnings.extend(dbml_warnings)
    raw_nodes = [
        {
            "name": node["name"],
            "columns": node["columns"],
            "indexes": node.get("indexes"),
            "note": node.get("note"),
        }
        for node in parsed_nodes
    ]
    nodes = _normalise_import_nodes(
        raw_nodes, _existing_nodes_by_name(canvas), warnings
    )
    # DBML carries no layout; `_place_nodes` keeps an existing node where the
    # user put it and grids the rest.
    return _place_nodes(nodes, canvas), parsed_relationships


def _place_nodes(
    nodes: list[dict[str, Any]], canvas: dict[str, Any]
) -> list[dict[str, Any]]:
    """Give a parsed document positions: keep existing ones, grid the rest."""
    existing = _existing_nodes_by_name(canvas)
    columns = max(1, int(len(nodes) ** 0.5))
    for index, node in enumerate(nodes):
        previous = existing.get(node["name"].lower())
        if previous:
            node["x"] = previous["x"]
            node["y"] = previous["y"]
        else:
            node["x"] = (index % columns) * _GRID_X
            node["y"] = (index // columns) * _GRID_Y
    return nodes


def _import_sql(
    canvas: dict[str, Any], content: str, warnings: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        parsed_nodes, parsed_relationships, sql_warnings = parse_sql(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    warnings.extend(sql_warnings)
    raw_nodes = [
        {
            "name": node["name"],
            "columns": node["columns"],
            "indexes": node.get("indexes"),
        }
        for node in parsed_nodes
    ]
    nodes = _normalise_import_nodes(
        raw_nodes, _existing_nodes_by_name(canvas), warnings
    )
    return _place_nodes(nodes, canvas), parsed_relationships


def _merge_into_canvas(
    canvas: dict[str, Any],
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    """Add what is missing, keeping nodes and lines already on the canvas."""
    created: dict[str, str] = {
        name: node["id"] for name, node in _existing_nodes_by_name(canvas).items()
    }
    for node in nodes:
        if node["name"].lower() in created:
            continue
        created_node = dal.create_node(
            canvas_id=canvas["id"],
            name=node["name"],
            table_id=node["table_id"],
            columns=node["columns"],
            x=node["x"],
            y=node["y"],
        )
        created[node["name"].lower()] = created_node["id"]
    for rel in relationships:
        source_id = created.get(rel["source"].lower())
        target_id = created.get(rel["target"].lower())
        if source_id is None or target_id is None or source_id == target_id:
            warnings.append(
                f"relationship {rel['source']} -> {rel['target']} references a "
                "table that is not on the canvas"
            )
            continue
        try:
            dal.create_relationship(
                canvas_id=canvas["id"],
                source_node_id=source_id,
                target_node_id=target_id,
                source_columns=rel["source_columns"],
                target_columns=rel["target_columns"],
                cardinality=rel["cardinality"],
                label=rel["label"],
            )
        except ValueError as exc:
            warnings.append(str(exc))


@router.post("/erd/canvases/{zone_id}/import", response_model=ErdImportResponse)
def import_canvas(zone_id: str, body: ImportRequest) -> dict:
    """Replace (or merge) a canvas from JSON or DBML text.
    A replace is total: every node and relationship on the canvas is discarded
    first. A merge keeps existing nodes by name and appends what is missing.
    Syntax the canvas does not model is reported in ``warnings`` instead of
    failing the whole document.
    """
    canvas = canvas_or_404(zone_id)
    warnings: list[str] = []
    if body.format == "json":
        nodes, relationships, notes, areas = _import_json(
            canvas, body.content, warnings
        )
    elif body.format == "sql":
        nodes, relationships = _import_sql(canvas, body.content, warnings)
        notes = []
        areas = []
    else:
        nodes, relationships = _import_dbml(canvas, body.content, warnings)
        notes = []
        areas = []
    if body.replace:
        payload = dal.replace_canvas_contents(canvas["id"], nodes, relationships)
        if notes:
            dal.replace_notes(canvas["id"], notes)
        if areas:
            dal.replace_areas(canvas["id"], areas)
        if notes or areas:
            payload = dal.get_canvas(zone_id) or payload
    else:
        _merge_into_canvas(canvas, nodes, relationships, warnings)
        payload = dal.get_canvas(zone_id) or canvas
    return {
        "data": {
            "canvas": payload,
            "imported_nodes": len(payload["nodes"]),
            "imported_relationships": len(payload["relationships"]),
            "warnings": warnings,
        }
    }


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "canvas"


@router.get("/erd/canvases/{zone_id}/export", response_model=ErdExportResponse)
def export_canvas(
    zone_id: str,
    format: str = Query("json", pattern="^(json|dbml|sql)$"),
    dialect: str = Query("postgres", pattern="^(postgres|mysql|sqlite)$"),
) -> dict:
    """Serialise the canvas as JSON (lossless), DBML, or SQL DDL.
    JSON keeps positions, virtual tables and cardinalities. DBML is the
    exchange format: positions are intentionally absent, and a relationship
    without columns cannot be expressed there, so it is omitted. SQL emits
    ``CREATE TABLE`` plus foreign keys for the chosen dialect; types are copied
    verbatim rather than translated.
    """
    canvas = canvas_or_404(zone_id)
    names = {node["id"]: node["name"] for node in canvas["nodes"]}
    relationships = [
        {
            "source": names.get(rel["source_node_id"], ""),
            "target": names.get(rel["target_node_id"], ""),
            "source_columns": rel["source_columns"],
            "target_columns": rel["target_columns"],
            "cardinality": rel["cardinality"],
            "label": rel["label"],
        }
        for rel in canvas["relationships"]
    ]
    if format == "dbml":
        content = export_dbml(canvas["nodes"], relationships)
        extension = "dbml"
    elif format == "sql":
        # The DDL writer keys relationships by node id, unlike the name-based
        # shape DBML and JSON use.
        content = export_sql(canvas["nodes"], canvas["relationships"], dialect)
        extension = "sql"
    else:
        content = json.dumps(
            {
                "format": "auto-ontology-erd",
                "version": 1,
                "zone_id": canvas["zone_id"],
                "viewport": canvas["viewport"],
                "nodes": [
                    {
                        "name": node["name"],
                        "table_id": node["table_id"],
                        "x": node["x"],
                        "y": node["y"],
                        "collapsed": node["collapsed"],
                        "columns": node["columns"],
                        "indexes": node["indexes"],
                        "note": node["note"],
                    }
                    for node in canvas["nodes"]
                ],
                "relationships": relationships,
                "notes": canvas["notes"],
                "areas": canvas["areas"],
            },
            indent=2,
            ensure_ascii=False,
        )
        extension = "json"
    return {
        "data": {
            "format": format,
            "filename": f"{_slug(canvas.get('zone_name') or 'canvas')}.{extension}",
            "content": content,
        }
    }
