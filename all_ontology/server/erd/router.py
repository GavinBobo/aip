# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for the per-zone ER canvas."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from all_ontology.dal import erd as dal
from all_ontology.dal import schema as s
from all_ontology.dal.session import store
from all_ontology.server.erd import assistant
from all_ontology.server.erd.schemas import (
    AreaCreate,
    AreaUpdate,
    AssistantRequest,
    CanvasState,
    NodeCreate,
    NodeUpdate,
    NoteCreate,
    NoteUpdate,
    RelationshipCreate,
    RelationshipUpdate,
    VersionCreate,
    ViewportUpdate,
)
from all_ontology.server.responses import (
    ErdAreaResponse,
    ErdAssistantResponse,
    ErdCanvasResponse,
    ErdCanvasVersionListResponse,
    ErdCanvasVersionResponse,
    ErdNodeResponse,
    ErdNoteResponse,
    ErdRelationshipResponse,
    IdResponse,
)

router = APIRouter()


def canvas_or_404(zone_id: str) -> dict[str, Any]:
    """The zone's canvas, or a 404. Shared with the import/export routes."""
    canvas = dal.get_or_create_canvas(zone_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return canvas


@router.post("/erd/assistant", response_model=ErdAssistantResponse)
def erd_assistant(body: AssistantRequest) -> dict:
    """Turn one sentence into canvas edits, for the canvas chat bubble.

    Stateless by design: the browser sends the canvas it is showing plus a short
    conversation, and gets back a reply with a list of edits to apply through
    the ordinary node/relationship routes. Nothing is written here, so a request
    that arrives from a stale tab cannot clobber a canvas someone else moved on
    from — the edits land as normal API calls from the tab that asked.

    ``zone_id`` is only used to confirm the zone exists: a canvas for a zone the
    caller cannot see should fail before spending an LLM call on it.
    """
    canvas_or_404(body.zone_id)
    reply = assistant.ask(body)
    return {"data": reply.model_dump()}


@router.get("/erd/canvases/{zone_id}", response_model=ErdCanvasResponse)
def get_canvas(zone_id: str) -> dict:
    """Return the zone's ER canvas, creating it and its table nodes on first open.

    Catalog nodes track the zone: a table the zone gained appears here, and a
    table it no longer covers loses its node. Diagram-only nodes imported from a
    document are left untouched.
    """
    return {"data": canvas_or_404(zone_id)}


@router.patch("/erd/canvases/{zone_id}", response_model=ErdCanvasResponse)
def patch_canvas(zone_id: str, body: ViewportUpdate) -> dict:
    """Persist the canvas pan/zoom so the next visit opens at the same view."""
    updated = dal.update_viewport(zone_id, body.model_dump())
    if updated is None:
        raise HTTPException(
            status_code=404, detail=f"Canvas for zone {zone_id!r} not found"
        )
    canvas = dal.get_canvas(zone_id)
    if canvas is None:  # pragma: no cover - the viewport write just proved it exists
        raise HTTPException(
            status_code=404, detail=f"Canvas for zone {zone_id!r} not found"
        )
    return {"data": canvas}


@router.put("/erd/canvases/{zone_id}/state", response_model=ErdCanvasResponse)
def put_canvas_state(zone_id: str, body: CanvasState) -> dict:
    """Replace the canvas with a snapshot, for undo and redo.

    Node and relationship ids are preserved so the browser's history stack
    keeps pointing at the same rows after the round trip.
    """
    canvas = canvas_or_404(zone_id)
    payload = dal.restore_canvas_state(
        canvas["id"],
        [node.model_dump() for node in body.nodes],
        [rel.model_dump() for rel in body.relationships],
        body.notes,
        body.areas,
    )
    if payload is None:  # pragma: no cover - canvas_or_404 just proved it exists
        raise HTTPException(
            status_code=404, detail=f"Canvas for zone {zone_id!r} not found"
        )
    return {"data": payload}


@router.patch("/erd/nodes/{node_id}", response_model=ErdNodeResponse)
def patch_node(node_id: str, body: NodeUpdate) -> dict:
    """Move or collapse one table card, or annotate its columns.

    Column aliases (``column_notes``) and the table note are accepted for
    catalog tables as well; renaming or rewriting columns is not.
    """
    try:
        node = dal.update_node(
            node_id,
            x=body.x,
            y=body.y,
            collapsed=body.collapsed,
            name=body.name,
            columns=body.columns,
            column_notes=body.column_notes,
            indexes=body.indexes,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id!r} not found")
    return {"data": node}


@router.post("/erd/nodes", status_code=201, response_model=ErdNodeResponse)
def post_node(body: NodeCreate) -> dict:
    """Add a table card by hand, typically a virtual table that is not catalogued."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A node needs a name")
    if body.table_id is not None:
        exists = store().query_read(
            select(s.catalog_table.c.id).where(s.catalog_table.c.id == body.table_id)
        )
        if not exists:
            raise HTTPException(
                status_code=400, detail=f"Table {body.table_id!r} not found"
            )
    node = dal.create_node(
        canvas_id=body.canvas_id,
        name=name,
        table_id=body.table_id,
        columns=body.columns,
        indexes=body.indexes,
        note=body.note,
        x=body.x,
        y=body.y,
    )
    return {"data": node}


@router.delete("/erd/nodes/{node_id}", response_model=IdResponse)
def remove_node(node_id: str) -> dict:
    """Take a table card off the canvas.

    A catalog-backed card is hidden rather than deleted, so the zone's next
    reconciliation does not put it back; it can be restored later. A
    canvas-only card is deleted outright.
    """
    if not dal.delete_node(node_id):
        raise HTTPException(status_code=404, detail=f"Node {node_id!r} not found")
    return {"data": {"id": node_id}}


@router.post("/erd/nodes/{node_id}/restore", response_model=ErdNodeResponse)
def restore_hidden_node(node_id: str) -> dict:
    """Put a hidden catalog table back on the canvas, where it was before."""
    node = dal.restore_node(node_id)
    if node is None:
        raise HTTPException(
            status_code=404, detail=f"No hidden node {node_id!r} to restore"
        )
    return {"data": node}


@router.post(
    "/erd/relationships", status_code=201, response_model=ErdRelationshipResponse
)
def post_relationship(body: RelationshipCreate) -> dict:
    """Draw a relationship between two table cards.

    Both endpoints must already be on the canvas and must differ. The two column
    lists describe the same number of columns; empty lists mean a table-level
    relationship.
    """
    try:
        relationship = dal.create_relationship(
            canvas_id=body.canvas_id,
            source_node_id=body.source_node_id,
            target_node_id=body.target_node_id,
            source_columns=body.source_columns,
            target_columns=body.target_columns,
            cardinality=body.cardinality,
            label=body.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": relationship}


@router.patch("/erd/relationships/{rel_id}", response_model=ErdRelationshipResponse)
def patch_relationship(rel_id: str, body: RelationshipUpdate) -> dict:
    """Change a relationship's cardinality, label or column pair."""
    try:
        relationship = dal.update_relationship(
            rel_id,
            cardinality=body.cardinality,
            label=body.label,
            source_columns=body.source_columns,
            target_columns=body.target_columns,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if relationship is None:
        raise HTTPException(
            status_code=404, detail=f"Relationship {rel_id!r} not found"
        )
    return {"data": relationship}


@router.delete("/erd/relationships/{rel_id}", response_model=IdResponse)
def remove_relationship(rel_id: str) -> dict:
    """Delete one relationship line."""
    if not dal.delete_relationship(rel_id):
        raise HTTPException(
            status_code=404, detail=f"Relationship {rel_id!r} not found"
        )
    return {"data": {"id": rel_id}}


@router.post("/erd/notes", status_code=201, response_model=ErdNoteResponse)
def post_note(body: NoteCreate) -> dict:
    """Add a sticky note to the canvas."""
    return {
        "data": dal.create_note(
            canvas_id=body.canvas_id,
            text=body.text,
            x=body.x,
            y=body.y,
            color=body.color,
        )
    }


@router.patch("/erd/notes/{note_id}", response_model=ErdNoteResponse)
def patch_note(note_id: str, body: NoteUpdate) -> dict:
    """Move, resize or retype a sticky note."""
    note = dal.update_note(
        note_id,
        text=body.text,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        color=body.color,
    )
    if note is None:
        raise HTTPException(status_code=404, detail=f"Note {note_id!r} not found")
    return {"data": note}


@router.delete("/erd/notes/{note_id}", response_model=IdResponse)
def remove_note(note_id: str) -> dict:
    """Delete a sticky note."""
    if not dal.delete_note(note_id):
        raise HTTPException(status_code=404, detail=f"Note {note_id!r} not found")
    return {"data": {"id": note_id}}


@router.post("/erd/areas", status_code=201, response_model=ErdAreaResponse)
def post_area(body: AreaCreate) -> dict:
    """Add a grouping rectangle to the canvas."""
    return {
        "data": dal.create_area(
            canvas_id=body.canvas_id,
            name=body.name,
            color=body.color,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
        )
    }


@router.patch("/erd/areas/{area_id}", response_model=ErdAreaResponse)
def patch_area(area_id: str, body: AreaUpdate) -> dict:
    """Move, resize, rename or recolour a grouping rectangle."""
    area = dal.update_area(
        area_id,
        name=body.name,
        color=body.color,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
    )
    if area is None:
        raise HTTPException(status_code=404, detail=f"Area {area_id!r} not found")
    return {"data": area}


@router.delete("/erd/areas/{area_id}", response_model=IdResponse)
def remove_area(area_id: str) -> dict:
    """Delete a grouping rectangle. Its tables stay on the canvas."""
    if not dal.delete_area(area_id):
        raise HTTPException(status_code=404, detail=f"Area {area_id!r} not found")
    return {"data": {"id": area_id}}


@router.get(
    "/erd/canvases/{zone_id}/versions", response_model=ErdCanvasVersionListResponse
)
def list_versions(zone_id: str) -> dict:
    """Saved versions of the canvas, newest first."""
    rows = dal.list_versions(zone_id)
    return {"data": rows, "count": len(rows)}


@router.post(
    "/erd/canvases/{zone_id}/versions",
    status_code=201,
    response_model=ErdCanvasVersionResponse,
)
def create_version(
    zone_id: str,
    body: VersionCreate,
    uid: str | None = Query(None, description="User saving the version"),
) -> dict:
    """Snapshot the canvas as it stands, under a user-provided label."""
    row = dal.create_version(zone_id, body.label, uid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": row}


@router.post("/erd/versions/{version_id}/restore", response_model=ErdCanvasResponse)
def restore_version(version_id: str) -> dict:
    """Put a saved version back on the canvas."""
    canvas = dal.restore_version(version_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail=f"Version {version_id!r} not found")
    return {"data": canvas}


@router.delete("/erd/versions/{version_id}", response_model=IdResponse)
def remove_version(version_id: str) -> dict:
    """Delete a saved version. The canvas is untouched."""
    if not dal.delete_version(version_id):
        raise HTTPException(status_code=404, detail=f"Version {version_id!r} not found")
    return {"data": {"id": version_id}}
