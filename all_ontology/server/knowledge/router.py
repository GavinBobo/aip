# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for knowledge networks, extraction and BKN export."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from all_ontology.dal import knowledge as dal
from all_ontology.knowledge.bkn import build_bkn_package
from all_ontology.knowledge.extractor import extract_document
from all_ontology.parsing.store import get_run
from all_ontology.server.identity import resolve_internal_user
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
    KnowledgeNetworkCreate,
    KnowledgeNetworkList,
    KnowledgeNetworkPatch,
    KnowledgeNetworkResponse,
    KnowledgeRelationList,
    KnowledgeRelationPatch,
    KnowledgeRelationResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# asyncio only keeps a weak reference to a bare task. The parser had the same
# bug and a test now pins the fix; here the task would silently disappear
# mid-extraction and leave the document stuck at "extracting".
_EXTRACTION_TASKS: set[asyncio.Task[Any]] = set()


def _run_extraction(document_id: str) -> None:
    try:
        extract_document(document_id)
    except Exception:
        # `extract_document` already stored the failure on the row; the log is
        # for the operator, not for a caller that has long since been answered.
        logger.exception("Background knowledge extraction failed: %s", document_id)


def _start_extraction(document_id: str) -> None:
    task = asyncio.create_task(asyncio.to_thread(_run_extraction, document_id))
    _EXTRACTION_TASKS.add(task)
    task.add_done_callback(_EXTRACTION_TASKS.discard)


def _require_network(network_id: str) -> dict[str, Any]:
    network = dal.get_network(network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="知识网络不存在。")
    return network


@router.get("/knowledge/networks", response_model=KnowledgeNetworkList)
def list_knowledge_networks() -> dict[str, Any]:
    networks = dal.list_networks()
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
        network = dal.create_network(
            name=body.name,
            description=body.description,
            domain=body.domain,
            created_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    _require_network(network_id)
    try:
        network = dal.update_network(
            network_id,
            patch=body.model_dump(exclude_unset=True),
            modified_by=resolve_internal_user(request, required=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if network is None:
        raise HTTPException(status_code=404, detail="知识网络不存在。")
    return {"data": network}


@router.delete(
    "/knowledge/networks/{network_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_network(network_id: str) -> dict[str, Any]:
    if not dal.delete_network(network_id):
        raise HTTPException(status_code=404, detail="知识网络不存在。")
    return {"data": {"id": network_id}}


@router.get(
    "/knowledge/networks/{network_id}/concepts",
    response_model=KnowledgeConceptList,
)
def list_knowledge_concepts(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    concepts = dal.list_concepts(network_id)
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
    _require_network(network_id)
    run = get_run(body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    if run.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="只能添加已成功解析的文档。")
    title = (
        str(run.get("file_name") or run.get("source_name") or "").strip()
        or "未命名文档"
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
    if document is None:
        raise HTTPException(status_code=404, detail="知识文档不存在。")
    if not document.get("run_id"):
        raise HTTPException(status_code=409, detail="该文档没有绑定解析结果。")
    dal.update_document(document_id, status="queued", error_message="")
    _start_extraction(document_id)
    return {"data": dal.get_document(document_id) or document}


@router.delete(
    "/knowledge/documents/{document_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_document(document_id: str) -> dict[str, Any]:
    if not dal.delete_document(document_id):
        raise HTTPException(status_code=404, detail="知识文档不存在。")
    return {"data": {"id": document_id}}


@router.patch(
    "/knowledge/concepts/{concept_id}",
    response_model=KnowledgeConceptResponse,
)
def update_knowledge_concept(
    concept_id: str, body: KnowledgeConceptPatch
) -> dict[str, Any]:
    if dal.get_concept(concept_id) is None:
        raise HTTPException(status_code=404, detail="知识概念不存在。")
    try:
        concept = dal.update_concept(
            concept_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if concept is None:
        raise HTTPException(status_code=404, detail="知识概念不存在。")
    return {"data": concept}


@router.delete(
    "/knowledge/concepts/{concept_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_concept(concept_id: str) -> dict[str, Any]:
    if not dal.delete_concept(concept_id):
        raise HTTPException(status_code=404, detail="知识概念不存在。")
    return {"data": {"id": concept_id}}


@router.patch(
    "/knowledge/relations/{relation_id}",
    response_model=KnowledgeRelationResponse,
)
def update_knowledge_relation(
    relation_id: str, body: KnowledgeRelationPatch
) -> dict[str, Any]:
    try:
        relation = dal.update_relation(
            relation_id, patch=body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if relation is None:
        raise HTTPException(status_code=404, detail="知识关系不存在。")
    return {"data": relation}


@router.delete(
    "/knowledge/relations/{relation_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_relation(relation_id: str) -> dict[str, Any]:
    if not dal.delete_relation(relation_id):
        raise HTTPException(status_code=404, detail="知识关系不存在。")
    return {"data": {"id": relation_id}}


@router.patch(
    "/knowledge/facts/{fact_id}",
    response_model=KnowledgeFactResponse,
)
def update_knowledge_fact(fact_id: str, body: KnowledgeFactPatch) -> dict[str, Any]:
    try:
        fact = dal.update_fact(fact_id, patch=body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail="知识事实不存在。")
    return {"data": fact}


@router.delete(
    "/knowledge/facts/{fact_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_fact(fact_id: str) -> dict[str, Any]:
    if not dal.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="知识事实不存在。")
    return {"data": {"id": fact_id}}


@router.get(
    "/knowledge/data-targets",
    response_model=KnowledgeDataTargetList,
)
def list_knowledge_data_targets(
    q: str | None = Query(default=None, description="按名称或描述模糊搜索"),
) -> dict[str, Any]:
    targets = dal.list_data_targets(q)
    return {"data": targets, "count": len(targets)}


@router.post(
    "/knowledge/concepts/{concept_id}/links",
    response_model=KnowledgeDataLinkResponse,
    status_code=201,
)
def link_knowledge_concept(
    concept_id: str, body: KnowledgeDataLinkCreate
) -> dict[str, Any]:
    try:
        link = dal.create_data_link(
            concept_id=concept_id,
            target_kind=body.target_kind,
            target_id=body.target_id,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": link}


@router.delete(
    "/knowledge/links/{link_id}",
    response_model=KnowledgeDeleteResponse,
)
def unlink_knowledge_concept(link_id: str) -> dict[str, Any]:
    if not dal.delete_data_link(link_id):
        raise HTTPException(status_code=404, detail="映射不存在。")
    return {"data": {"id": link_id}}


@router.get(
    "/knowledge/networks/{network_id}/graph",
    response_model=KnowledgeGraphResponse,
)
def get_knowledge_graph(network_id: str) -> dict[str, Any]:
    _require_network(network_id)
    concepts = dal.list_concepts(network_id)
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
                    "label": "映射",
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
    graph = KnowledgeGraph(nodes=nodes, edges=edges)
    return {"data": graph.model_dump()}


@router.get("/knowledge/networks/{network_id}/export")
def export_knowledge_network(network_id: str) -> Response:
    network = _require_network(network_id)
    filename, payload = build_bkn_package(
        network,
        dal.list_concepts(network_id),
        dal.list_relations(network_id),
        dal.list_facts(network_id),
    )
    return Response(
        content=payload,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
