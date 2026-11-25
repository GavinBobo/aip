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
    zone_id: str | None = None
    status: str | None = None
    version: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    created_by: str | None = None
    modified_by: str | None = None
    concept_count: int = 0
    relation_count: int = 0
    fact_count: int = 0
    action_count: int = 0
    risk_count: int = 0
    metric_count: int = 0
    group_count: int = 0
    capability_count: int = 0
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


class KnowledgeActionItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    description: str | None = None
    action_intent: str | None = None
    bound_concept_id: str | None = None
    bound_concept_name: str | None = None
    bound_concept_key: str | None = None
    parameters: list[dict] | None = None
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None
    evidence: list[dict] | None = None


class KnowledgeRiskItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    description: str | None = None
    severity: str | None = None
    mitigation: str | None = None
    related_concept_id: str | None = None
    related_concept_name: str | None = None
    related_concept_key: str | None = None
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None
    evidence: list[dict] | None = None


class KnowledgeMetricItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    description: str | None = None
    expression: str | None = None
    unit: str | None = None
    concept_id: str | None = None
    concept_name: str | None = None
    concept_key: str | None = None
    sql_attribute_id: str | None = None
    sql_attribute_name: str | None = None
    sql_attribute_expression: str | None = None
    status: str | None = None
    confidence: float | None = None
    source_document_id: str | None = None


class KnowledgeConceptGroupItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    description: str | None = None
    concepts: list[dict] | None = None
    created: datetime | None = None
    modified: datetime | None = None


class KnowledgeCapabilityItem(ApiModel):
    id: str
    network_id: str
    key: str
    name: str
    kind: str
    description: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    created: datetime | None = None
    modified: datetime | None = None


class KnowledgeNetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    domain: str | None = None
    zone_id: str | None = None


class KnowledgeNetworkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    domain: str | None = None
    zone_id: str | None = None
    status: Literal["draft", "published", "archived"] | None = None
    version: str | None = None


class KnowledgeGrantUpdate(BaseModel):
    grants: list[dict] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    dept_ids: list[str] = Field(default_factory=list)


class KnowledgeGrantResponse(ApiModel):
    data: dict


class KnowledgeGrantAuditList(ApiModel):
    data: list[dict]
    count: int


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


class KnowledgeActionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    action_intent: Literal["add", "modify", "delete", "execute"] | None = None
    bound_concept_id: str | None = None
    parameters: list[dict] | None = None
    status: Status | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeActionCapabilityLink(BaseModel):
    capability_id: str = Field(min_length=1)


class KnowledgeActionExecute(BaseModel):
    parameters: dict = Field(default_factory=dict)
    dry_run: bool = True


class KnowledgeRiskPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    mitigation: str | None = None
    related_concept_id: str | None = None
    status: Status | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeMetricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    expression: str | None = None
    unit: str | None = None
    concept_id: str | None = None
    sql_attribute_id: str | None = None


class KnowledgeMetricPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    expression: str | None = None
    unit: str | None = None
    concept_id: str | None = None
    sql_attribute_id: str | None = None
    status: Status | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeConceptGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    concept_ids: list[str] = Field(default_factory=list)


class KnowledgeConceptGroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class KnowledgeCapabilityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["skill", "function", "mcp_tool", "knowledge_base"]
    description: str | None = None
    config: dict = Field(default_factory=dict)


class KnowledgeCapabilityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    config: dict | None = None
    enabled: bool | None = None


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


class KnowledgeGraphQuery(BaseModel):
    start_concept_ids: list[str] = Field(default_factory=list)
    depth: int = Field(default=2, ge=0, le=4)
    direction: Literal["out", "in", "both"] = "both"
    relation_kinds: list[str] = Field(default_factory=list)
    include_data_links: bool = False


class KnowledgeGraphQueryResponse(ApiModel):
    data: dict


class KnowledgeDataTargetList(ApiModel):
    data: list[KnowledgeDataTarget]
    count: int


class KnowledgeActionList(ApiModel):
    data: list[KnowledgeActionItem]
    count: int


class KnowledgeActionResponse(ApiModel):
    data: KnowledgeActionItem


class KnowledgeRiskList(ApiModel):
    data: list[KnowledgeRiskItem]
    count: int


class KnowledgeRiskResponse(ApiModel):
    data: KnowledgeRiskItem


class KnowledgeMetricList(ApiModel):
    data: list[KnowledgeMetricItem]
    count: int


class KnowledgeMetricResponse(ApiModel):
    data: KnowledgeMetricItem


class KnowledgeMetricValidateResponse(ApiModel):
    data: dict


class KnowledgeMetricPreviewResponse(ApiModel):
    data: dict


class KnowledgeConceptGroupList(ApiModel):
    data: list[KnowledgeConceptGroupItem]
    count: int


class KnowledgeConceptGroupResponse(ApiModel):
    data: KnowledgeConceptGroupItem


class KnowledgeCapabilityList(ApiModel):
    data: list[KnowledgeCapabilityItem]
    count: int


class KnowledgeCapabilityResponse(ApiModel):
    data: KnowledgeCapabilityItem


class KnowledgeVersionItem(ApiModel):
    id: str
    network_id: str
    version: int
    label: str | None = None
    created: datetime | None = None
    created_by: str | None = None


class KnowledgeVersionCreate(BaseModel):
    label: str | None = None


class KnowledgeVersionList(ApiModel):
    data: list[KnowledgeVersionItem]
    count: int


class KnowledgeVersionResponse(ApiModel):
    data: KnowledgeVersionItem


class KnowledgeVersionRestoreResponse(ApiModel):
    data: dict


class KnowledgeVersionDiffResponse(ApiModel):
    data: dict


class KnowledgeEvalCaseItem(ApiModel):
    id: str
    network_id: str
    question: str
    expected_concepts: list[str] | None = None
    expected_facts: list[str] | None = None
    notes: str | None = None
    created: datetime | None = None
    modified: datetime | None = None


class KnowledgeEvalCaseCreate(BaseModel):
    question: str = Field(min_length=1)
    expected_concepts: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    notes: str | None = None


class KnowledgeEvalCaseList(ApiModel):
    data: list[KnowledgeEvalCaseItem]
    count: int


class KnowledgeEvalCaseResponse(ApiModel):
    data: KnowledgeEvalCaseItem


class KnowledgeEvalRunItem(ApiModel):
    id: str
    network_id: str
    total: int
    passed: int
    details: list[dict] | None = None
    created: datetime | None = None
    created_by: str | None = None


class KnowledgeEvalRunList(ApiModel):
    data: list[KnowledgeEvalRunItem]
    count: int


class KnowledgeEvalRunResponse(ApiModel):
    data: KnowledgeEvalRunItem


class KnowledgeExecutionItem(ApiModel):
    id: str
    network_id: str
    action_id: str
    status: str
    parameters: dict | None = None
    plan: dict | None = None
    result: dict | None = None
    error_message: str | None = None
    created: datetime | None = None
    created_by: str | None = None
    finished: datetime | None = None


class KnowledgeExecutionList(ApiModel):
    data: list[KnowledgeExecutionItem]
    count: int


class KnowledgeExecutionResponse(ApiModel):
    data: KnowledgeExecutionItem


class KnowledgeDataLinkResponse(ApiModel):
    data: dict


class KnowledgeDeleteResponse(ApiModel):
    data: dict


class KnowledgeImportResponse(ApiModel):
    data: dict
