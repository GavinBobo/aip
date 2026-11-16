# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request bodies for the ER canvas routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ViewportUpdate(BaseModel):
    """Pan/zoom as the browser reports it."""

    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


class NodeUpdate(BaseModel):
    """A move, a collapse, or both. Omitted fields are left alone."""

    x: float | None = None
    y: float | None = None
    collapsed: bool | None = None
    # Only accepted for a diagram-only table; see ``update_node``.
    name: str | None = None
    columns: list[dict[str, Any]] | None = None
    # ``column name -> alias``. Documentation rather than schema, so it is
    # accepted for catalog tables too.
    column_notes: dict[str, str] | None = None
    indexes: list[dict[str, Any]] | None = None
    note: str | None = None


class NodeCreate(BaseModel):
    """A table added by hand — usually a virtual one from a design sketch."""

    canvas_id: str
    name: str
    table_id: str | None = None
    columns: list[dict[str, Any]] | None = None
    indexes: list[dict[str, Any]] | None = None
    note: str | None = None
    x: float = 0.0
    y: float = 0.0


class RelationshipCreate(BaseModel):
    """A new line between two nodes."""

    canvas_id: str
    source_node_id: str
    target_node_id: str
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    cardinality: str = "many-to-one"
    label: str | None = None


class RelationshipUpdate(BaseModel):
    """Edit a line's cardinality, label or column pair."""

    cardinality: str | None = None
    label: str | None = None
    source_columns: list[str] | None = None
    target_columns: list[str] | None = None


class ImportRequest(BaseModel):
    """Import a whole diagram from JSON or DBML text."""

    format: Literal["json", "dbml", "sql"]
    content: str
    replace: bool = True


class NodeSnapshot(BaseModel):
    """One node in a client-side undo/redo snapshot."""

    id: str | None = None
    table_id: str | None = None
    name: str
    x: float = 0.0
    y: float = 0.0
    collapsed: bool = False
    columns: list[dict[str, Any]] | None = None
    indexes: list[dict[str, Any]] | None = None
    note: str | None = None


class RelationshipSnapshot(BaseModel):
    """One relationship in a client-side undo/redo snapshot."""

    id: str | None = None
    source_node_id: str
    target_node_id: str
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    cardinality: str = "many-to-one"
    label: str | None = None


class CanvasState(BaseModel):
    """A whole canvas as the browser held it, used to undo or redo a change."""

    nodes: list[NodeSnapshot] = Field(default_factory=list)
    relationships: list[RelationshipSnapshot] = Field(default_factory=list)
    notes: list[dict[str, Any]] = Field(default_factory=list)
    areas: list[dict[str, Any]] = Field(default_factory=list)


class AreaCreate(BaseModel):
    """A new grouping rectangle."""

    canvas_id: str
    name: str = ""
    color: str | None = None
    x: float = 0.0
    y: float = 0.0
    width: float = 520.0
    height: float = 380.0


class AreaUpdate(BaseModel):
    """Move, resize, rename or recolour a grouping rectangle."""

    name: str | None = None
    color: str | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class VersionCreate(BaseModel):
    """Save the current canvas under a label."""

    label: str = ""


class NoteCreate(BaseModel):
    """A new sticky note."""

    canvas_id: str
    text: str = ""
    x: float = 0.0
    y: float = 0.0
    color: str | None = None


class NoteUpdate(BaseModel):
    """Move, resize or retype a sticky note."""

    text: str | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    color: str | None = None


class AssistantColumn(BaseModel):
    """A column as the assistant sees it: enough to reason, small enough to send."""

    name: str
    data_type: str | None = None
    note: str | None = None


class AssistantNode(BaseModel):
    """One table card, from the browser's copy of the canvas."""

    id: str
    name: str
    #: Null for a diagram-only table.
    table_id: str | None = None
    columns: list[AssistantColumn] = Field(default_factory=list)
    note: str | None = None


class AssistantRelationship(BaseModel):
    """One existing connection, addressed by node id.

    ``source``/``target`` carry the table names too: the model reasons about
    names ("orders 与 customers 的关系"), but acts on ids.
    """

    id: str
    source: str
    target: str
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    cardinality: str = "many-to-one"
    label: str | None = None


class AssistantCanvas(BaseModel):
    """The canvas the model is asked to change."""

    nodes: list[AssistantNode] = Field(default_factory=list)
    relationships: list[AssistantRelationship] = Field(default_factory=list)


class AssistantTurn(BaseModel):
    """One earlier message in the panel, for follow-ups like "再给它加个时间戳"."""

    role: Literal["user", "assistant"]
    content: str


class AssistantRequest(BaseModel):
    """A question or instruction from the canvas chat bubble."""

    zone_id: str
    message: str = Field(min_length=1, max_length=4000)
    canvas: AssistantCanvas = Field(default_factory=AssistantCanvas)
    history: list[AssistantTurn] = Field(default_factory=list, max_length=20)
