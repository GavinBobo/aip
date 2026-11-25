# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for knowledge networks, extraction and BKN export."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile

from all_ontology.dal import knowledge as dal
from all_ontology.knowledge.bkn import build_bkn_package
from all_ontology.knowledge.bkn_import import import_bkn_package
from all_ontology.knowledge.metrics import preview_metric, validate_metric
from all_ontology.knowledge.evals import run_evals
from all_ontology.knowledge.execution import prepare_action_execution
from all_ontology.knowledge.query import query_graph
from all_ontology.knowledge.snapshot import (
    create_version,
    diff_version,
    get_version,
    list_versions,
    restore_version,
)
from all_ontology.knowledge.extractor import definition_key, extract_document
from all_ontology.parsing.store import get_run
from all_ontology.server.identity import resolve_internal_user
from all_ontology.server.access import (
    current_access,
    current_zone_ids,
    current_zone_permissions,
    zone_is_visible,
)
from all_ontology.dal.schema import (
    ZONE_PERMISSION_EDIT,
    ZONE_PERMISSION_MANAGE,
    ZONE_PERMISSION_RANK,
)
from all_ontology.server.knowledge.schemas import (
    KnowledgeConceptList,
    KnowledgeConceptPatch,
    KnowledgeConceptResponse,
    KnowledgeDataLinkCreate,
    KnowledgeDataLinkResponse,
    KnowledgeDataTargetList,
    KnowledgeDeleteResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentList,
    KnowledgeDocumentResponse,
    KnowledgeFactList,
    KnowledgeFactPatch,
    KnowledgeFactResponse,
    KnowledgeGraph,
    KnowledgeGraphResponse,
    KnowledgeGraphQuery,
    KnowledgeGraphQueryResponse,
    KnowledgeGrantUpdate,
    KnowledgeGrantResponse,
    KnowledgeGrantAuditList,
    KnowledgeImportResponse,
    KnowledgeActionList,
    KnowledgeActionPatch,
    KnowledgeActionCapabilityLink,
    KnowledgeActionExecute,
    KnowledgeActionResponse,
    KnowledgeConceptGroupCreate,
    KnowledgeConceptGroupList,
    KnowledgeConceptGroupPatch,
    KnowledgeConceptGroupResponse,
    KnowledgeCapabilityCreate,
    KnowledgeCapabilityList,
    KnowledgeCapabilityPatch,
    KnowledgeCapabilityResponse,
    KnowledgeNetworkCreate,
    KnowledgeNetworkList,
    KnowledgeNetworkPatch,
    KnowledgeNetworkResponse,
    KnowledgeMetricCreate,
    KnowledgeMetricList,
    KnowledgeMetricPatch,
    KnowledgeMetricResponse,
    KnowledgeMetricPreviewResponse,
    KnowledgeMetricValidateResponse,
    KnowledgeVersionCreate,
    KnowledgeVersionList,
    KnowledgeVersionResponse,
    KnowledgeVersionRestoreResponse,
    KnowledgeVersionDiffResponse,
    KnowledgeEvalCaseCreate,
    KnowledgeEvalCaseList,
    KnowledgeEvalCaseResponse,
    KnowledgeEvalRunList,
    KnowledgeEvalRunResponse,
    KnowledgeExecutionList,
    KnowledgeExecutionResponse,
    KnowledgeRelationList,
    KnowledgeRelationPatch,
    KnowledgeRelationResponse,
    KnowledgeRiskList,
    KnowledgeRiskPatch,
    KnowledgeRiskResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# asyncio only keeps a weak reference to a bare task. The parser had the same
# bug and a test now pins the fix; here the task would silently disappear
# mid-extraction and leave the document stuck at "extracting".
_EXTRACTION_TASKS: set[asyncio.Task[Any]] = set()
_RUNNING_DOCUMENTS: set[str] = set()


def _run_extraction(document_id: str) -> None:
    try:
        extract_document(document_id)
    except Exception:
        # `extract_document` already stored the failure on the row; the log is
        # for the operator, not for a caller that has long since been answered.
        logger.exception("Background knowledge extraction failed: %s", document_id)


def _start_extraction(document_id: str) -> None:
    if document_id in _RUNNING_DOCUMENTS:
        return
    _RUNNING_DOCUMENTS.add(document_id)
    task = asyncio.create_task(asyncio.to_thread(_run_extraction, document_id))
    _EXTRACTION_TASKS.add(task)

    def finished(done: asyncio.Task[Any]) -> None:
        _EXTRACTION_TASKS.discard(done)
        _RUNNING_DOCUMENTS.discard(document_id)

    task.add_done_callback(finished)


def _require_network(network_id: str, minimum: str = "read") -> dict[str, Any]:
    access = current_access()
    network = dal.get_network(
        network_id,
        current_zone_ids(),
        user_id=access.user_id if access else None,
        dept_ids=access.dept_ids if access else (),
        zone_permissions=current_zone_permissions(),
    )
    if network is None:
        raise HTTPException(status_code=404, detail="Knowledge network not found.")
    actual = network.get("permission")
    if actual is None or ZONE_PERMISSION_RANK[actual] < ZONE_PERMISSION_RANK[minimum]:
        raise HTTPException(
            status_code=403,
            detail="You do not have the required permission on this knowledge network.",
        )
    return network


def _require_read(network_id: str) -> dict[str, Any]:
    return _require_network(network_id, "read")


def _require_entity_network(
    entity: dict[str, Any] | None,
    *,
    missing: str,
    minimum: str = ZONE_PERMISSION_EDIT,
) -> dict[str, Any]:
    if entity is None:
        raise HTTPException(status_code=404, detail=missing)
    network_id = entity.get("network_id")
    if not network_id:
        raise HTTPException(status_code=404, detail=missing)
    _require_network(str(network_id), minimum)
    return entity


def _require_entity(
    kind: str,
    entity_id: str,
    *,
    missing: str,
    minimum: str = ZONE_PERMISSION_EDIT,
) -> None:
    network_id = dal.entity_network_id(kind, entity_id)
    if network_id is None:
        raise HTTPException(status_code=404, detail=missing)
    _require_network(network_id, minimum)


@router.get("/knowledge/networks", response_model=KnowledgeNetworkList)
def list_knowledge_networks() -> dict[str, Any]:
    access = current_access()
    networks = dal.list_networks(
        current_zone_ids(),
        user_id=access.user_id if access else None,
        dept_ids=access.dept_ids if access else (),
        zone_permissions=current_zone_permissions(),
    )
    return {"data": networks, "count": len(networks)}


@router.post(
    "/knowledge/networks",
    response_model=KnowledgeNetworkResponse,
    status_code=201,
)
def create_knowledge_network(
    request: Request, body: KnowledgeNetworkCreate
) -> dict[str, Any]:
    try:
        if body.zone_id and not zone_is_visible(body.zone_id):
            raise HTTPException(status_code=404, detail="Zone not found")
        network = dal.create_network(
            name=body.name,
            description=body.description,
            domain=body.domain,
            zone_id=body.zone_id,
            created_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    network["permission"] = ZONE_PERMISSION_MANAGE
    return {"data": network}


@router.get(
    "/knowledge/networks/{network_id}",
    response_model=KnowledgeNetworkResponse,
)
def get_knowledge_network(network_id: str) -> dict[str, Any]:
    return {"data": _require_network(network_id)}


@router.patch(
    "/knowledge/networks/{network_id}",
    response_model=KnowledgeNetworkResponse,
)
def update_knowledge_network(
    request: Request, network_id: str, body: KnowledgeNetworkPatch
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    patch = body.model_dump(exclude_unset=True)
    if patch.get("zone_id") and not zone_is_visible(patch["zone_id"]):
        raise HTTPException(status_code=404, detail="Zone not found")
    try:
        network = dal.update_network(
            network_id,
            patch=patch,
            modified_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if network is None:
        raise HTTPException(status_code=404, detail="Knowledge network not found.")
    return {"data": _require_network(network_id, ZONE_PERMISSION_EDIT)}


@router.delete(
    "/knowledge/networks/{network_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_network(network_id: str) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_MANAGE)
    if not dal.delete_network(network_id):
        raise HTTPException(status_code=404, detail="Knowledge network not found.")
    return {"data": {"id": network_id}}


@router.get(
    "/knowledge/networks/{network_id}/grants",
    response_model=KnowledgeGrantResponse,
)
def get_knowledge_network_grants(network_id: str) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_MANAGE)
    return {"data": dal.list_network_grants(network_id)}


@router.put(
    "/knowledge/networks/{network_id}/grants",
    response_model=KnowledgeGrantResponse,
)
def replace_knowledge_network_grants(
    network_id: str, body: KnowledgeGrantUpdate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_MANAGE)
    try:
        grants = dal.replace_network_grants(
            network_id,
            grants=[grant.model_dump() for grant in body.grants],
            user_ids=body.user_ids,
            dept_ids=body.dept_ids,
            actor_user_id=current_access().user_id if current_access() else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": grants}


@router.get(
    "/knowledge/networks/{network_id}/grant-audit",
    response_model=KnowledgeGrantAuditList,
)
def list_knowledge_network_grant_audit(network_id: str) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_MANAGE)
    rows = dal.list_network_grant_audit(network_id)
    return {"data": rows, "count": len(rows)}


@router.get(
    "/knowledge/networks/{network_id}/concepts",
    response_model=KnowledgeConceptList,
)
def list_knowledge_concepts(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    concepts = dal.list_concepts(network_id, current_zone_ids())
    return {"data": concepts, "count": len(concepts)}


@router.get(
    "/knowledge/networks/{network_id}/relations",
    response_model=KnowledgeRelationList,
)
def list_knowledge_relations(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    relations = dal.list_relations(network_id)
    return {"data": relations, "count": len(relations)}


@router.get(
    "/knowledge/networks/{network_id}/facts",
    response_model=KnowledgeFactList,
)
def list_knowledge_facts(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    facts = dal.list_facts(network_id)
    return {"data": facts, "count": len(facts)}


@router.get(
    "/knowledge/networks/{network_id}/documents",
    response_model=KnowledgeDocumentList,
)
def list_knowledge_documents(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    documents = dal.list_documents(network_id)
    return {"data": documents, "count": len(documents)}


@router.post(
    "/knowledge/networks/{network_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=202,
)
def add_knowledge_document(
    request: Request, network_id: str, body: KnowledgeDocumentCreate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    run = get_run(body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Parsing result not found.")
    if run.get("status") != "succeeded":
        raise HTTPException(
            status_code=409, detail="Only successfully parsed documents can be added."
        )
    title = (
        str(run.get("file_name") or run.get("source_name") or "").strip()
        or "Untitled document"
    )
    document, created = dal.create_document(
        network_id=network_id,
        run_id=body.run_id,
        title=title,
        source_name=run.get("source_name"),
        created_by=resolve_internal_user(request, required=False),
    )
    if created or document.get("status") in {"queued", "failed"}:
        dal.update_document(str(document["id"]), status="queued", error_message="")
        _start_extraction(str(document["id"]))
        document = dal.get_document(str(document["id"])) or document
    return {"data": document}


@router.post(
    "/knowledge/documents/{document_id}/extract",
    response_model=KnowledgeDocumentResponse,
    status_code=202,
)
def reextract_knowledge_document(document_id: str) -> dict[str, Any]:
    document = dal.get_document(document_id)
    document = _require_entity_network(
        document, missing="Knowledge document not found.", minimum=ZONE_PERMISSION_EDIT
    )
    if not document.get("run_id"):
        raise HTTPException(
            status_code=409, detail="This document is not linked to a parsing result."
        )
    dal.update_document(document_id, status="queued", error_message="")
    _start_extraction(document_id)
    return {"data": dal.get_document(document_id) or document}


@router.delete(
    "/knowledge/documents/{document_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_document(document_id: str) -> dict[str, Any]:
    _require_entity("document", document_id, missing="Knowledge document not found.")
    if not dal.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    return {"data": {"id": document_id}}


@router.patch(
    "/knowledge/concepts/{concept_id}",
    response_model=KnowledgeConceptResponse,
)
def update_knowledge_concept(
    concept_id: str, body: KnowledgeConceptPatch
) -> dict[str, Any]:
    _require_entity("concept", concept_id, missing="Knowledge concept not found.")
    try:
        concept = dal.update_concept(
            concept_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if concept is None:
        raise HTTPException(status_code=404, detail="Knowledge concept not found.")
    return {"data": concept}


@router.delete(
    "/knowledge/concepts/{concept_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_concept(concept_id: str) -> dict[str, Any]:
    _require_entity("concept", concept_id, missing="Knowledge concept not found.")
    if not dal.delete_concept(concept_id):
        raise HTTPException(status_code=404, detail="Knowledge concept not found.")
    return {"data": {"id": concept_id}}


@router.patch(
    "/knowledge/relations/{relation_id}",
    response_model=KnowledgeRelationResponse,
)
def update_knowledge_relation(
    relation_id: str, body: KnowledgeRelationPatch
) -> dict[str, Any]:
    _require_entity("relation", relation_id, missing="Knowledge relation not found.")
    try:
        relation = dal.update_relation(
            relation_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if relation is None:
        raise HTTPException(status_code=404, detail="Knowledge relation not found.")
    return {"data": relation}


@router.delete(
    "/knowledge/relations/{relation_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_relation(relation_id: str) -> dict[str, Any]:
    _require_entity("relation", relation_id, missing="Knowledge relation not found.")
    if not dal.delete_relation(relation_id):
        raise HTTPException(status_code=404, detail="Knowledge relation not found.")
    return {"data": {"id": relation_id}}


@router.patch(
    "/knowledge/facts/{fact_id}",
    response_model=KnowledgeFactResponse,
)
def update_knowledge_fact(fact_id: str, body: KnowledgeFactPatch) -> dict[str, Any]:
    _require_entity("fact", fact_id, missing="Knowledge fact not found.")
    try:
        fact = dal.update_fact(fact_id, patch=body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail="Knowledge fact not found.")
    return {"data": fact}


@router.delete(
    "/knowledge/facts/{fact_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_fact(fact_id: str) -> dict[str, Any]:
    _require_entity("fact", fact_id, missing="Knowledge fact not found.")
    if not dal.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="Knowledge fact not found.")
    return {"data": {"id": fact_id}}


@router.get(
    "/knowledge/networks/{network_id}/actions",
    response_model=KnowledgeActionList,
)
def list_knowledge_actions(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    actions = dal.list_actions(network_id)
    return {"data": actions, "count": len(actions)}


@router.patch(
    "/knowledge/actions/{action_id}",
    response_model=KnowledgeActionResponse,
)
def update_knowledge_action(
    action_id: str, body: KnowledgeActionPatch
) -> dict[str, Any]:
    _require_entity("action", action_id, missing="Knowledge action not found.")
    try:
        action = dal.update_action(action_id, patch=body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if action is None:
        raise HTTPException(status_code=404, detail="Knowledge action not found.")
    return {"data": action}


@router.delete(
    "/knowledge/actions/{action_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_action(action_id: str) -> dict[str, Any]:
    _require_entity("action", action_id, missing="Knowledge action not found.")
    if not dal.delete_action(action_id):
        raise HTTPException(status_code=404, detail="Knowledge action not found.")
    return {"data": {"id": action_id}}


@router.post(
    "/knowledge/actions/{action_id}/capabilities",
    response_model=KnowledgeDeleteResponse,
)
def link_action_capability(
    action_id: str, body: KnowledgeActionCapabilityLink
) -> dict[str, Any]:
    _require_entity("action", action_id, missing="Knowledge action not found.")
    try:
        return {"data": dal.link_action_capability(action_id, body.capability_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/knowledge/actions/{action_id}/capabilities/{capability_id}",
    response_model=KnowledgeDeleteResponse,
)
def unlink_action_capability(action_id: str, capability_id: str) -> dict[str, Any]:
    _require_entity("action", action_id, missing="Knowledge action not found.")
    if not dal.unlink_action_capability(action_id, capability_id):
        raise HTTPException(
            status_code=404, detail="Action capability mount not found."
        )
    return {"data": {"action_id": action_id, "capability_id": capability_id}}


@router.post(
    "/knowledge/actions/{action_id}/execute",
    response_model=KnowledgeExecutionResponse,
    status_code=201,
)
def execute_knowledge_action(
    request: Request, action_id: str, body: KnowledgeActionExecute
) -> dict[str, Any]:
    _require_entity("action", action_id, missing="Knowledge action not found.")
    if not body.dry_run:
        raise HTTPException(
            status_code=422,
            detail="Real tool execution is not connected to an execution service yet. Build a dry-run plan first.",
        )
    try:
        execution = prepare_action_execution(
            action_id,
            parameters=body.parameters,
            created_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": execution}


@router.get(
    "/knowledge/networks/{network_id}/executions",
    response_model=KnowledgeExecutionList,
)
def list_action_executions(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    executions = dal.list_action_executions(network_id)
    return {"data": executions, "count": len(executions)}


@router.get(
    "/knowledge/networks/{network_id}/risks",
    response_model=KnowledgeRiskList,
)
def list_knowledge_risks(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    risks = dal.list_risks(network_id)
    return {"data": risks, "count": len(risks)}


@router.patch(
    "/knowledge/risks/{risk_id}",
    response_model=KnowledgeRiskResponse,
)
def update_knowledge_risk(risk_id: str, body: KnowledgeRiskPatch) -> dict[str, Any]:
    _require_entity("risk", risk_id, missing="Knowledge risk not found.")
    try:
        risk = dal.update_risk(risk_id, patch=body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if risk is None:
        raise HTTPException(status_code=404, detail="Knowledge risk not found.")
    return {"data": risk}


@router.delete(
    "/knowledge/risks/{risk_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_risk(risk_id: str) -> dict[str, Any]:
    _require_entity("risk", risk_id, missing="Knowledge risk not found.")
    if not dal.delete_risk(risk_id):
        raise HTTPException(status_code=404, detail="Knowledge risk not found.")
    return {"data": {"id": risk_id}}


@router.get(
    "/knowledge/networks/{network_id}/metrics",
    response_model=KnowledgeMetricList,
)
def list_knowledge_metrics(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    metrics = dal.list_metrics(network_id)
    return {"data": metrics, "count": len(metrics)}


@router.post(
    "/knowledge/networks/{network_id}/metrics",
    response_model=KnowledgeMetricResponse,
    status_code=201,
)
def create_knowledge_metric(
    network_id: str, body: KnowledgeMetricCreate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    existing = {item["key"] for item in dal.list_metrics(network_id)}
    base = definition_key(body.name, prefix="m")
    key = base
    suffix = 2
    while key in existing:
        key = f"{base}_{suffix}"
        suffix += 1
    try:
        metric = dal.create_metric(
            network_id=network_id,
            key=key,
            name=body.name,
            description=body.description,
            expression=body.expression,
            unit=body.unit,
            concept_id=body.concept_id,
            sql_attribute_id=body.sql_attribute_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": metric}


@router.patch(
    "/knowledge/metrics/{metric_id}",
    response_model=KnowledgeMetricResponse,
)
def update_knowledge_metric(
    metric_id: str, body: KnowledgeMetricPatch
) -> dict[str, Any]:
    _require_entity("metric", metric_id, missing="Knowledge metric not found.")
    try:
        metric = dal.update_metric(metric_id, patch=body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if metric is None:
        raise HTTPException(status_code=404, detail="Knowledge metric not found.")
    return {"data": metric}


@router.delete(
    "/knowledge/metrics/{metric_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_metric(metric_id: str) -> dict[str, Any]:
    _require_entity("metric", metric_id, missing="Knowledge metric not found.")
    if not dal.delete_metric(metric_id):
        raise HTTPException(status_code=404, detail="Knowledge metric not found.")
    return {"data": {"id": metric_id}}


@router.post(
    "/knowledge/metrics/{metric_id}/validate",
    response_model=KnowledgeMetricValidateResponse,
)
def validate_knowledge_metric(metric_id: str) -> dict[str, Any]:
    _require_entity("metric", metric_id, missing="Knowledge metric not found.")
    try:
        result = validate_metric(metric_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": result}


@router.post(
    "/knowledge/metrics/{metric_id}/preview",
    response_model=KnowledgeMetricPreviewResponse,
)
def preview_knowledge_metric(metric_id: str) -> dict[str, Any]:
    _require_entity("metric", metric_id, missing="Knowledge metric not found.")
    try:
        result = preview_metric(metric_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": result}


@router.get(
    "/knowledge/networks/{network_id}/concept-groups",
    response_model=KnowledgeConceptGroupList,
)
def list_knowledge_concept_groups(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    groups = dal.list_concept_groups(network_id)
    return {"data": groups, "count": len(groups)}


@router.post(
    "/knowledge/networks/{network_id}/concept-groups",
    response_model=KnowledgeConceptGroupResponse,
    status_code=201,
)
def create_knowledge_concept_group(
    network_id: str, body: KnowledgeConceptGroupCreate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    existing = {item["key"] for item in dal.list_concept_groups(network_id)}
    base = definition_key(body.name, prefix="g")
    key = base
    suffix = 2
    while key in existing:
        key = f"{base}_{suffix}"
        suffix += 1
    try:
        group = dal.create_concept_group(
            network_id=network_id,
            name=body.name,
            description=body.description,
            key=key,
            concept_ids=body.concept_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": group}


@router.patch(
    "/knowledge/concept-groups/{group_id}",
    response_model=KnowledgeConceptGroupResponse,
)
def update_knowledge_concept_group(
    group_id: str, body: KnowledgeConceptGroupPatch
) -> dict[str, Any]:
    _require_entity("concept_group", group_id, missing="Concept group not found.")
    try:
        group = dal.update_concept_group(
            group_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if group is None:
        raise HTTPException(status_code=404, detail="Concept group not found.")
    return {"data": group}


@router.delete(
    "/knowledge/concept-groups/{group_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_concept_group(group_id: str) -> dict[str, Any]:
    _require_entity("concept_group", group_id, missing="Concept group not found.")
    if not dal.delete_concept_group(group_id):
        raise HTTPException(status_code=404, detail="Concept group not found.")
    return {"data": {"id": group_id}}


@router.get(
    "/knowledge/networks/{network_id}/capabilities",
    response_model=KnowledgeCapabilityList,
)
def list_knowledge_capabilities(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    capabilities = dal.list_capabilities(network_id)
    return {"data": capabilities, "count": len(capabilities)}


@router.post(
    "/knowledge/networks/{network_id}/capabilities",
    response_model=KnowledgeCapabilityResponse,
    status_code=201,
)
def create_knowledge_capability(
    network_id: str, body: KnowledgeCapabilityCreate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    existing = {item["key"] for item in dal.list_capabilities(network_id)}
    base = definition_key(body.name, prefix="cp")
    key = base
    suffix = 2
    while key in existing:
        key = f"{base}_{suffix}"
        suffix += 1
    try:
        capability = dal.create_capability(
            network_id=network_id,
            key=key,
            name=body.name,
            kind=body.kind,
            description=body.description,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": capability}


@router.patch(
    "/knowledge/capabilities/{capability_id}",
    response_model=KnowledgeCapabilityResponse,
)
def update_knowledge_capability(
    capability_id: str, body: KnowledgeCapabilityPatch
) -> dict[str, Any]:
    _require_entity(
        "capability", capability_id, missing="Knowledge capability not found."
    )
    try:
        capability = dal.update_capability(
            capability_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if capability is None:
        raise HTTPException(status_code=404, detail="Knowledge capability not found.")
    return {"data": capability}


@router.delete(
    "/knowledge/capabilities/{capability_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_capability(capability_id: str) -> dict[str, Any]:
    _require_entity(
        "capability", capability_id, missing="Knowledge capability not found."
    )
    if not dal.delete_capability(capability_id):
        raise HTTPException(status_code=404, detail="Knowledge capability not found.")
    return {"data": {"id": capability_id}}


@router.get(
    "/knowledge/networks/{network_id}/versions",
    response_model=KnowledgeVersionList,
)
def list_knowledge_versions(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    versions = list_versions(network_id)
    return {"data": versions, "count": len(versions)}


@router.post(
    "/knowledge/networks/{network_id}/versions",
    response_model=KnowledgeVersionResponse,
    status_code=201,
)
def create_knowledge_version(
    request: Request, network_id: str, body: KnowledgeVersionCreate
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    try:
        version = create_version(
            network_id,
            label=body.label,
            created_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": version}


@router.post(
    "/knowledge/versions/{version_id}/restore",
    response_model=KnowledgeVersionRestoreResponse,
)
def restore_knowledge_version(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    _require_network(str(version["network_id"]), ZONE_PERMISSION_EDIT)
    try:
        result = restore_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": result}


@router.get(
    "/knowledge/versions/{version_id}/diff",
    response_model=KnowledgeVersionDiffResponse,
)
def diff_knowledge_version(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    _require_network(str(version["network_id"]), "read")
    try:
        result = diff_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": result}


@router.get(
    "/knowledge/networks/{network_id}/eval-cases",
    response_model=KnowledgeEvalCaseList,
)
def list_eval_cases(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    cases = dal.list_eval_cases(network_id)
    return {"data": cases, "count": len(cases)}


@router.post(
    "/knowledge/networks/{network_id}/eval-cases",
    response_model=KnowledgeEvalCaseResponse,
    status_code=201,
)
def create_eval_case(network_id: str, body: KnowledgeEvalCaseCreate) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    case = dal.create_eval_case(
        network_id=network_id,
        question=body.question,
        expected_concepts=body.expected_concepts,
        expected_facts=body.expected_facts,
        notes=body.notes,
    )
    return {"data": case}


@router.delete(
    "/knowledge/eval-cases/{case_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_eval_case(case_id: str) -> dict[str, Any]:
    _require_entity("eval_case", case_id, missing="Eval case not found.")
    if not dal.delete_eval_case(case_id):
        raise HTTPException(status_code=404, detail="Eval case not found.")
    return {"data": {"id": case_id}}


@router.get(
    "/knowledge/networks/{network_id}/eval-runs",
    response_model=KnowledgeEvalRunList,
)
def list_eval_runs(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    runs = dal.list_eval_runs(network_id)
    return {"data": runs, "count": len(runs)}


@router.post(
    "/knowledge/networks/{network_id}/eval-runs",
    response_model=KnowledgeEvalRunResponse,
    status_code=201,
)
def create_eval_run(request: Request, network_id: str) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    run = run_evals(
        network_id,
        created_by=resolve_internal_user(request, required=False),
    )
    return {"data": run}


@router.get(
    "/knowledge/data-targets",
    response_model=KnowledgeDataTargetList,
)
def list_knowledge_data_targets(
    q: str | None = Query(
        default=None, description="Fuzzy search by name or description"
    ),
) -> dict[str, Any]:
    targets = dal.list_data_targets(q, zone_ids=current_zone_ids())
    return {"data": targets, "count": len(targets)}


@router.post(
    "/knowledge/concepts/{concept_id}/links",
    response_model=KnowledgeDataLinkResponse,
    status_code=201,
)
def link_knowledge_concept(
    concept_id: str, body: KnowledgeDataLinkCreate
) -> dict[str, Any]:
    _require_entity("concept", concept_id, missing="Knowledge concept not found.")
    try:
        link = dal.create_data_link(
            concept_id=concept_id,
            target_kind=body.target_kind,
            target_id=body.target_id,
            note=body.note,
            zone_ids=current_zone_ids(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": link}


@router.delete(
    "/knowledge/links/{link_id}",
    response_model=KnowledgeDeleteResponse,
)
def unlink_knowledge_concept(link_id: str) -> dict[str, Any]:
    network_id = dal.data_link_network_id(link_id)
    if network_id is None:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    if not dal.delete_data_link(link_id):
        raise HTTPException(status_code=404, detail="Mapping not found.")
    return {"data": {"id": link_id}}


@router.get(
    "/knowledge/networks/{network_id}/graph",
    response_model=KnowledgeGraphResponse,
)
def get_knowledge_graph(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    concepts = dal.list_concepts(network_id, current_zone_ids())
    relations = dal.list_relations(network_id)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    data_nodes: dict[str, str] = {}
    for concept in concepts:
        nodes.append(
            {
                "id": concept["id"],
                "kind": "concept",
                "label": concept["name"],
                "detail": concept.get("description"),
                "concept_kind": concept.get("kind"),
                "status": concept.get("status"),
                "confidence": concept.get("confidence"),
            }
        )
        for link in concept.get("data_links") or []:
            node_id = f"{link['kind']}:{link['target_id']}"
            data_nodes[node_id] = link.get("name") or link["target_id"]
            edges.append(
                {
                    "id": f"map:{link['id']}",
                    "source": concept["id"],
                    "target": node_id,
                    "kind": "mapped_to",
                    "label": "mapped to",
                    "confidence": link.get("confidence"),
                }
            )
    for node_id, label in data_nodes.items():
        nodes.append(
            {
                "id": node_id,
                "kind": "data",
                "label": label,
                "detail": node_id.split(":", 1)[0],
            }
        )
    for relation in relations:
        edges.append(
            {
                "id": relation["id"],
                "source": relation["source_concept_id"],
                "target": relation["target_concept_id"],
                "kind": relation.get("kind") or "association",
                "label": relation["name"],
                "confidence": relation.get("confidence"),
            }
        )
    for action in dal.list_actions(network_id):
        node_id = f"action:{action['id']}"
        nodes.append(
            {
                "id": node_id,
                "kind": "action",
                "label": action["name"],
                "detail": action.get("description"),
                "concept_kind": action.get("action_intent"),
                "status": action.get("status"),
                "confidence": action.get("confidence"),
            }
        )
        if action.get("bound_concept_id"):
            edges.append(
                {
                    "id": f"acts:{action['id']}",
                    "source": node_id,
                    "target": action["bound_concept_id"],
                    "kind": "acts_on",
                    "label": "acts on",
                    "confidence": action.get("confidence"),
                }
            )
    for risk in dal.list_risks(network_id):
        node_id = f"risk:{risk['id']}"
        nodes.append(
            {
                "id": node_id,
                "kind": "risk",
                "label": risk["name"],
                "detail": risk.get("description"),
                "concept_kind": risk.get("severity"),
                "status": risk.get("status"),
                "confidence": risk.get("confidence"),
            }
        )
        if risk.get("related_concept_id"):
            edges.append(
                {
                    "id": f"risk:{risk['id']}",
                    "source": node_id,
                    "target": risk["related_concept_id"],
                    "kind": "risk_of",
                    "label": "risk of",
                    "confidence": risk.get("confidence"),
                }
            )
    graph = KnowledgeGraph(nodes=nodes, edges=edges)
    return {"data": graph.model_dump()}


@router.post(
    "/knowledge/networks/{network_id}/query",
    response_model=KnowledgeGraphQueryResponse,
)
def query_knowledge_graph(network_id: str, body: KnowledgeGraphQuery) -> dict[str, Any]:
    _require_network(network_id)
    return {
        "data": query_graph(
            network_id,
            start_concept_ids=body.start_concept_ids,
            depth=body.depth,
            direction=body.direction,
            relation_kinds=body.relation_kinds,
            include_data_links=body.include_data_links,
            zone_ids=current_zone_ids(),
        )
    }


@router.get("/knowledge/networks/{network_id}/export")
def export_knowledge_network(network_id: str) -> Response:
    network = _require_network(network_id)
    filename, payload = build_bkn_package(
        network,
        dal.list_concepts(network_id, current_zone_ids()),
        dal.list_relations(network_id),
        dal.list_facts(network_id),
        dal.list_actions(network_id),
        dal.list_risks(network_id),
        dal.list_concept_groups(network_id),
        dal.list_metrics(network_id),
        dal.list_capabilities(network_id),
    )
    return Response(
        content=payload,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/knowledge/networks/{network_id}/import",
    response_model=KnowledgeImportResponse,
)
async def import_knowledge_network(
    network_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    _require_network(network_id, ZONE_PERMISSION_EDIT)
    payload = await file.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="The BKN package exceeds the 64 MB limit."
        )
    if not payload:
        raise HTTPException(
            status_code=422, detail="The uploaded BKN package is empty."
        )
    try:
        result = import_bkn_package(network_id, payload, filename=file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": result}
