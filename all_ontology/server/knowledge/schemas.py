# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Item and envelope models for the knowledge-ontology API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from all_ontology.server.models import ApiModel


Status = Literal["draft", "reviewed", "certified"]
RelationKind = Literal[
    "association", "part_of", "causal", "depends_on", "controls", "flows_to", "related"
]
ConceptKind = Literal[
    "entity", "event", "process", "rule", "metric", "role", "document"
]


class KnowledgeNetworkItem(ApiModel):
    id: str
    name: str
    description: str | None = None
    domain: str | None = None
    status: str | None = None
    version: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    created_by: str | None = None
    modified_by: str | None = None
    concept_count: int = 0
    relation_count: int = 0
    fact_count: int = 0
    document_count: int = 0
    data_link_count: int = 0


class KnowledgeDocumentItem(ApiModel):
    id: str
    network_id: str
    run_id: str | None = None
    title: str | None = None
    source_name: str | None = None
    status: str | None = None
    summary: str | None = None
    error_message: str | None = None
    chunk_count: int | None = None
    created: datetime | None = None
    created_by: str | None = None
    extracted_at: datetime | None = None
    run_status: str | None = None


class KnowledgeConceptItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    description: str | None = None
    kind: str | None = None
    aliases: list[str] | None = None
    attributes: list[dict] | None = None
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    evidence_count: int | None = None
    evidence: list[dict] | None = None
    data_links: list[dict] | None = None


class KnowledgeRelationItem(ApiModel):
    id: str
    network_id: str
    key: str
    source_concept_id: str
    target_concept_id: str
    name: str
    description: str | None = None
    kind: str | None = None
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None
    source_key: str | None = None
    source_name: str | None = None
    target_key: str | None = None
    target_name: str | None = None
    evidence_count: int | None = None
    evidence: list[dict] | None = None


class KnowledgeFactItem(ApiModel):
    id: str
    network_id: str
    subject_concept_id: str
    relation_id: str | None = None
    object_concept_id: str | None = None
    object_text: str | None = None
    predicate: str
    statement: str
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None
    subject_name: str | None = None
    subject_key: str | None = None
    object_name: str | None = None
    object_key: str | None = None
    evidence: list[dict] | None = None


class KnowledgeGraphNode(ApiModel):
    id: str
    kind: str
    label: str
    detail: str | None = None
    concept_kind: str | None = None
    status: str | None = None
    confidence: float | None = None


class KnowledgeGraphEdge(ApiModel):
    id: str
    source: str
    target: str
    kind: str
    label: str | None = None
    confidence: float | None = None


class KnowledgeGraph(ApiModel):
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]


class KnowledgeDataTarget(ApiModel):
    kind: str
    id: str
    name: str
    detail: str | None = None


class KnowledgeNetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    domain: str | None = None


class KnowledgeNetworkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    domain: str | None = None
    status: Literal["draft", "published", "archived"] | None = None
    version: str | None = None


class KnowledgeDocumentCreate(BaseModel):
    run_id: str = Field(min_length=1)


class KnowledgeConceptPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    kind: ConceptKind | None = None
    status: Status | None = None
    aliases: list[str] | None = None
    attributes: list[dict] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeRelationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    kind: RelationKind | None = None
    status: Status | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeFactPatch(BaseModel):
    predicate: str | None = Field(default=None, min_length=1, max_length=200)
    statement: str | None = Field(default=None, min_length=1)
    object_text: str | None = None
    status: Status | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeDataLinkCreate(BaseModel):
    target_kind: Literal["term", "table"]
    target_id: str = Field(min_length=1)
    note: str | None = None


class KnowledgeNetworkList(ApiModel):
    data: list[KnowledgeNetworkItem]
    count: int


class KnowledgeNetworkResponse(ApiModel):
    data: KnowledgeNetworkItem


class KnowledgeDocumentList(ApiModel):
    data: list[KnowledgeDocumentItem]
    count: int


class KnowledgeDocumentResponse(ApiModel):
    data: KnowledgeDocumentItem


class KnowledgeConceptList(ApiModel):
    data: list[KnowledgeConceptItem]
    count: int


class KnowledgeConceptResponse(ApiModel):
    data: KnowledgeConceptItem


class KnowledgeRelationList(ApiModel):
    data: list[KnowledgeRelationItem]
    count: int


class KnowledgeRelationResponse(ApiModel):
    data: KnowledgeRelationItem


class KnowledgeFactList(ApiModel):
    data: list[KnowledgeFactItem]
    count: int


class KnowledgeFactResponse(ApiModel):
    data: KnowledgeFactItem


class KnowledgeGraphResponse(ApiModel):
    data: KnowledgeGraph


class KnowledgeDataTargetList(ApiModel):
    data: list[KnowledgeDataTarget]
    count: int


class KnowledgeDataLinkResponse(ApiModel):
    data: dict


class KnowledgeDeleteResponse(ApiModel):
    data: dict
