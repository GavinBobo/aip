# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Knowledge retrieval over chunks, graph objects and citations."""

from __future__ import annotations

import os
import uuid

import pytest

from all_ontology.env import load_env

load_env()

pytest.importorskip("sqlalchemy")

from sqlalchemy import select  # noqa: E402

from all_ontology.dal import knowledge as dal  # noqa: E402
from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal.session import store  # noqa: E402
from all_ontology.knowledge.search import (  # noqa: E402
    retrieve_agent_context,
    search_knowledge,
)


@pytest.fixture(scope="module", autouse=True)
def require_schema():
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read(select(s.knowledge_chunk.c.id).limit(1))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"knowledge tables unavailable (alembic upgrade head): {exc}")


@pytest.fixture
def world():
    suffix = uuid.uuid4().hex[:8]
    network = dal.create_network(
        name=f"kn-search-{suffix}",
        description="retrieval",
        domain="procurement",
        created_by=None,
    )
    network_id = str(network["id"])
    document, _ = dal.create_document(
        network_id=network_id,
        run_id=None,
        title="purchase-policy.pdf",
        source_name="purchase-policy.pdf",
        created_by=None,
    )
    document_id = str(document["id"])
    dal.save_extraction(
        document_id,
        summary="Purchase approval policy.",
        concepts=[
            {
                "key": "c_purchase_order",
                "name": "Purchase order",
                "description": "The main purchasing document.",
                "kind": "entity",
                "aliases": ["PO"],
                "attributes": [],
                "confidence": 0.9,
                "evidence": [
                    {"page": 3, "block_index": 12, "quote": "Purchase order"}
                ],
            }
        ],
        relations=[],
        facts=[
            {
                "subject_key": "c_purchase_order",
                "object_text": "CFO",
                "predicate": "requires approval from",
                "statement": "Purchase orders above 10,000 require CFO approval.",
                "confidence": 0.9,
                "evidence": [
                    {
                        "page": 3,
                        "block_index": 12,
                        "quote": "Purchase orders above 10,000 require CFO approval.",
                    }
                ],
            }
        ],
        rules=[
            {
                "key": "rule_approval",
                "name": "CFO approval rule",
                "statement": "Purchase orders above 10,000 require CFO approval.",
                "description": "Approval threshold.",
                "scope": "procurement",
                "condition": "amount > 10000",
                "roles": ["CFO"],
                "exceptions": [],
                "concept_key": "c_purchase_order",
                "metric_key": None,
                "action_key": None,
                "confidence": 0.9,
                "evidence": [
                    {
                        "page": 3,
                        "block_index": 12,
                        "quote": "Purchase orders above 10,000 require CFO approval.",
                    }
                ],
            }
        ],
        chunks=[
            {
                "chunk_index": 1,
                "text": "Purchase orders above 10,000 require CFO approval before submission.",
                "page_start": 3,
                "page_end": 3,
                "block_start": 12,
                "block_end": 12,
            },
            {
                "chunk_index": 2,
                "text": "采购订单超过一万元需要财务总监审批。",
                "page_start": 4,
                "page_end": 4,
                "block_start": 1,
                "block_end": 1,
            },
        ],
        chunk_count=2,
    )
    yield {"network_id": network_id, "document_id": document_id}
    dal.delete_network(network_id)


def test_human_search_returns_chunks_facts_and_citations(world) -> None:
    result = search_knowledge(
        "purchase order approval",
        network_ids=[world["network_id"]],
        zone_ids=None,
        mode="human",
        limit=20,
    )
    kinds = {item["kind"] for item in result["results"]}
    assert "chunk" in kinds
    assert "fact" in kinds
    assert "concept" in kinds
    assert "rule" in kinds
    assert result["total"] > 0
    assert result["context"]
    chunk = next(item for item in result["results"] if item["kind"] == "chunk")
    assert chunk["page"] == 3
    assert "CFO approval" in chunk["snippet"]
    fact = next(item for item in result["results"] if item["kind"] == "fact")
    assert fact["evidence"]
    assert fact["evidence"][0]["page"] == 3
    rules = dal.list_rules(world["network_id"])
    assert len(rules) == 1
    assert rules[0]["roles"] == ["CFO"]
    assert rules[0]["evidence"][0]["page"] == 3
    chinese = search_knowledge(
        "财务总监审批",
        network_ids=[world["network_id"]],
        zone_ids=None,
        mode="human",
        limit=20,
    )
    assert any(
        item["kind"] == "chunk" and "财务总监审批" in (item["snippet"] or "")
        for item in chinese["results"]
    )


def test_agent_search_is_conservative_until_reviewed(world) -> None:
    before = search_knowledge(
        "CFO approval",
        network_ids=[world["network_id"]],
        zone_ids=None,
        mode="agent",
        limit=20,
    )
    assert before["results"] == []

    concept = dal.list_concepts(world["network_id"])[0]
    fact = dal.list_facts(world["network_id"])[0]
    dal.update_concept(str(concept["id"]), patch={"status": "certified"})
    dal.update_fact(str(fact["id"]), patch={"status": "certified"})

    after = search_knowledge(
        "CFO approval",
        network_ids=[world["network_id"]],
        zone_ids=None,
        mode="agent",
        limit=20,
    )
    kinds = {item["kind"] for item in after["results"]}
    assert "chunk" in kinds
    assert "fact" in kinds
    assert after["context"]
    assert retrieve_agent_context(
        "CFO approval",
        network_ids=[world["network_id"]],
        zone_ids=None,
    )
