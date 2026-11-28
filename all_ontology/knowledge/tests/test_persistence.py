# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The knowledge tier against a real database: write, read, cascade, extract."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from all_ontology.env import load_env

load_env()

pytest.importorskip("sqlalchemy")

from sqlalchemy import delete, select  # noqa: E402

from all_ontology.dal import knowledge as dal  # noqa: E402
from all_ontology.dal import access as access_dal  # noqa: E402
from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal.session import store, write_transaction  # noqa: E402
from all_ontology.knowledge.bkn import build_bkn_package  # noqa: E402
from all_ontology.knowledge.bkn_import import import_bkn_package  # noqa: E402
from all_ontology.knowledge.context import retrieve_knowledge_context  # noqa: E402
from all_ontology.knowledge.metrics import preview_metric, validate_metric  # noqa: E402
from all_ontology.knowledge.snapshot import (  # noqa: E402
    create_version,
    diff_version,
    restore_version,
)
from all_ontology.knowledge.evals import run_evals  # noqa: E402
from all_ontology.knowledge.execution import prepare_action_execution  # noqa: E402
from all_ontology.knowledge.query import query_graph  # noqa: E402
from all_ontology.knowledge.extractor import (  # noqa: E402
    ExtractedChunk,
    ExtractedConcept,
    ExtractedFact,
    ExtractedRule,
    extract_document,
)
from all_ontology.server.knowledge.router import get_knowledge_graph  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema():
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read(select(s.knowledge_network.c.id).limit(1))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"knowledge tables unavailable (alembic upgrade head): {exc}")


def _create_parse_run(suffix: str, result_path: str | None = None) -> tuple[str, str]:
    with write_transaction():
        task_id = str(
            store().query_write(
                s.parsing_task.insert()
                .values(name=f"parse-{suffix}", status="succeeded", total_documents=1)
                .returning(s.parsing_task.c.id)
            )[0]["id"]
        )
        parsing_document_id = str(
            store().query_write(
                s.parsing_document.insert()
                .values(
                    task_id=task_id,
                    file_name="order.pdf",
                    status="succeeded",
                )
                .returning(s.parsing_document.c.id)
            )[0]["id"]
        )
        run_id = str(
            store().query_write(
                s.parsing_run.insert()
                .values(
                    task_id=task_id,
                    document_id=parsing_document_id,
                    status="succeeded",
                    result_path=result_path,
                )
                .returning(s.parsing_run.c.id)
            )[0]["id"]
        )
    return task_id, run_id


def _cleanup(network_id: str, task_id: str) -> None:
    if network_id:
        dal.delete_network(network_id)
    if task_id:
        with write_transaction():
            store().query_write(
                delete(s.parsing_task).where(s.parsing_task.c.id == task_id)
            )


def test_extraction_roundtrip_and_network_cascade() -> None:
    suffix = uuid.uuid4().hex[:8]
    network_id = ""
    task_id = ""
    try:
        network = dal.create_network(
            name=f"kn-test-{suffix}",
            description="roundtrip",
            domain="test",
            created_by=None,
        )
        network_id = str(network["id"])
        task_id, run_id = _create_parse_run(suffix)

        knowledge_document, created = dal.create_document(
            network_id=network_id,
            run_id=run_id,
            title="order.pdf",
            source_name="order.pdf",
            created_by=None,
        )
        assert created is True
        document_id = str(knowledge_document["id"])

        result = dal.save_extraction(
            document_id,
            summary="采购订单包含物料。",
            concepts=[
                {
                    "key": "c_order",
                    "name": "采购订单",
                    "description": "采购业务的主单据。",
                    "kind": "entity",
                    "aliases": ["订单"],
                    "attributes": [{"name": "金额", "type": "number"}],
                    "confidence": 0.9,
                    "evidence": [{"page": 1, "block_index": 2, "quote": "采购订单"}],
                },
                {
                    "key": "c_material",
                    "name": "物料",
                    "description": "采购标的。",
                    "kind": "entity",
                    "aliases": [],
                    "attributes": [],
                    "confidence": 0.8,
                    "evidence": [],
                },
            ],
            relations=[
                {
                    "key": "r_order_contains_material",
                    "source_key": "c_order",
                    "target_key": "c_material",
                    "name": "包含",
                    "description": "订单包含物料。",
                    "kind": "part_of",
                    "confidence": 0.85,
                    "evidence": [
                        {"page": 1, "block_index": 3, "quote": "订单包含物料"}
                    ],
                }
            ],
            facts=[
                {
                    "subject_key": "c_order",
                    "object_text": "PO-001",
                    "predicate": "编号为",
                    "statement": "采购订单的编号为 PO-001。",
                    "confidence": 0.9,
                    "evidence": [
                        {"page": 1, "block_index": 4, "quote": "订单编号为 PO-001"}
                    ],
                }
            ],
            actions=[
                {
                    "key": "a_submit_order",
                    "name": "提交采购订单",
                    "description": "采购员提交订单进入审批。",
                    "action_intent": "add",
                    "bound_key": "c_order",
                    "parameters": [{"name": "order_id", "type": "string"}],
                    "confidence": 0.8,
                    "evidence": [
                        {"page": 1, "block_index": 5, "quote": "提交采购订单"}
                    ],
                }
            ],
            risks=[
                {
                    "key": "k_approval_risk",
                    "name": "越权审批风险",
                    "description": "未经授权的人员审批订单。",
                    "severity": "high",
                    "mitigation": "审批前校验角色权限。",
                    "related_key": "c_order",
                    "confidence": 0.8,
                    "evidence": [
                        {"page": 1, "block_index": 6, "quote": "审批前校验角色权限"}
                    ],
                }
            ],
            metrics=[
                {
                    "key": "m_monthly_spend",
                    "name": "月采购额",
                    "description": "本月采购订单金额之和。",
                    "expression": "SUM(amount)",
                    "unit": "元",
                    "concept_key": "c_order",
                    "confidence": 0.8,
                    "evidence": [{"page": 1, "block_index": 7, "quote": "月采购额"}],
                }
            ],
            chunk_count=1,
        )
        assert result["concept_count"] == 2
        assert result["relation_count"] == 1
        assert result["fact_count"] == 1
        assert result["action_count"] == 1
        assert result["risk_count"] == 1
        assert result["metric_count"] == 1

        concepts = dal.list_concepts(network_id)
        order = next(item for item in concepts if item["name"] == "采购订单")
        assert order["aliases"] == ["订单"]
        assert order["evidence_count"] == 1
        facts = dal.list_facts(network_id)
        assert facts[0]["evidence"][0]["page"] == 1
        actions = dal.list_actions(network_id)
        assert actions[0]["bound_concept_name"] == "采购订单"
        assert actions[0]["evidence"][0]["page"] == 1
        risks = dal.list_risks(network_id)
        assert risks[0]["severity"] == "high"
        assert risks[0]["related_concept_name"] == "采购订单"
        capability = dal.create_capability(
            network_id=network_id,
            key="cp_purchase_tool",
            name="采购工具",
            kind="function",
            description="",
            config={"box_id": "box_purchase", "tool_id": "tool_submit"},
        )
        dal.link_action_capability(actions[0]["id"], capability["id"])
        actions = dal.list_actions(network_id)
        assert actions[0]["capabilities"][0]["name"] == "采购工具"
        execution = prepare_action_execution(
            str(actions[0]["id"]),
            parameters={"order_id": "PO-001"},
            created_by=None,
        )
        assert execution["status"] == "planned"
        assert execution["plan"]["capability"]["name"] == "采购工具"
        metrics = dal.list_metrics(network_id)
        assert metrics[0]["expression"] == "SUM(amount)"
        assert metrics[0]["unit"] == "元"
        validation = validate_metric(str(metrics[0]["id"]))
        assert validation["valid"] is True
        assert validation["mode"] == "sql_syntax"
        with pytest.raises(ValueError, match="not bound to a data table"):
            preview_metric(str(metrics[0]["id"]))
        dal.update_concept(order["id"], patch={"status": "certified"})
        dal.update_fact(facts[0]["id"], patch={"status": "certified"})
        dal.update_action(actions[0]["id"], patch={"status": "certified"})
        dal.update_risk(risks[0]["id"], patch={"status": "certified"})
        dal.update_metric(metrics[0]["id"], patch={"status": "certified"})
        knowledge_context = retrieve_knowledge_context("采购订单审批风险")
        assert "采购订单" in knowledge_context
        assert "越权审批风险" in knowledge_context
        assert "证据" in knowledge_context
        assert "月采购额" in retrieve_knowledge_context("月采购额")
        graph = get_knowledge_graph(network_id)["data"]
        assert {"concept", "action", "risk"} <= {
            node["kind"] for node in graph["nodes"]
        }
        query = query_graph(
            network_id,
            start_concept_ids=[order["id"]],
            depth=1,
            direction="both",
        )
        assert {node["id"] for node in query["nodes"]} >= {
            order["id"],
            concepts[1]["id"],
        }

        group = dal.create_concept_group(
            network_id=network_id,
            name="采购",
            description="采购相关概念",
            key="g_procurement",
            concept_ids=[order["id"]],
        )
        assert [item["name"] for item in group["concepts"]] == ["采购订单"]
        groups = dal.list_concept_groups(network_id)

        network = dal.get_network(network_id)
        assert network is not None
        filename, payload = build_bkn_package(
            network,
            concepts,
            dal.list_relations(network_id),
            facts,
            actions,
            risks,
            groups,
            metrics,
            dal.list_capabilities(network_id),
        )
        assert filename.endswith(".bkn.tar.gz")
        assert payload

        assert dal.delete_network(network_id) is True
        network_id = ""
        with write_transaction():
            assert not store().query_read(
                select(s.knowledge_concept.c.id).where(
                    s.knowledge_concept.c.key == "c_order"
                )
            )
    finally:
        _cleanup(network_id, task_id)


def test_extract_document_reads_a_parse_run(tmp_path, monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:8]
    network_id = ""
    task_id = ""
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "file_name": "policy.pdf",
                "outputs": {
                    "json": {
                        "pages": [
                            {
                                "page_num": 0,
                                "blocks": [
                                    {
                                        "idx": 0,
                                        "type": "Title",
                                        "content": "采购制度",
                                    },
                                    {
                                        "idx": 1,
                                        "type": "Text",
                                        "content": "采购订单必须由采购经理审批。",
                                    },
                                ],
                            }
                        ]
                    },
                    "markdown": "# 采购制度\n\n采购订单必须由采购经理审批。",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        network = dal.create_network(
            name=f"kn-flow-{suffix}",
            description=None,
            domain=None,
            created_by=None,
        )
        network_id = str(network["id"])
        task_id, run_id = _create_parse_run(suffix, str(result_path))
        knowledge_document, _ = dal.create_document(
            network_id=network_id,
            run_id=run_id,
            title="policy.pdf",
            source_name="policy.pdf",
            created_by=None,
        )
        knowledge_document_id = str(knowledge_document["id"])

        def fake_chunk(title, chunk, index, total):
            return ExtractedChunk(
                summary="采购制度要求审批。",
                concepts=[
                    ExtractedConcept(
                        name="采购订单",
                        description="采购业务的主单据。",
                        evidence_quote="采购订单必须由采购经理审批",
                    ),
                    ExtractedConcept(
                        name="采购经理",
                        description="负责审批采购订单的角色。",
                        confidence=0.8,
                    ),
                ],
                facts=[
                    ExtractedFact(
                        subject="采购订单",
                        predicate="审批人是",
                        object="采购经理",
                        statement="采购订单必须由采购经理审批。",
                        evidence_quote="采购订单必须由采购经理审批",
                    )
                ],
            )

        monkeypatch.setattr(
            "all_ontology.knowledge.extractor._extract_chunk", fake_chunk
        )
        result = extract_document(knowledge_document_id, max_chunks=2)

        assert result["status"] == "extracted"
        assert result["chunk_count"] == 1
        assert result["concepts"] == 2
        assert result["facts"] == 1
        facts = dal.list_facts(network_id)
        assert facts[0]["evidence"][0]["page"] == 1
        assert facts[0]["evidence"][0]["block_index"] == 1
        chunks = store().query_read(
            select(s.knowledge_chunk.c.text, s.knowledge_chunk.c.page_start).where(
                s.knowledge_chunk.c.document_id == knowledge_document_id
            )
        )
        assert chunks
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["text"]
    finally:
        _cleanup(network_id, task_id)


def test_bkn_export_import_roundtrip() -> None:
    source_id = ""
    target_id = ""
    try:
        source = dal.create_network(
            name=f"kn-export-{uuid.uuid4().hex[:8]}",
            description="source",
            domain=None,
            created_by=None,
        )
        source_id = str(source["id"])
        target = dal.create_network(
            name=f"kn-import-{uuid.uuid4().hex[:8]}",
            description="target",
            domain=None,
            created_by=None,
        )
        target_id = str(target["id"])
        concepts = [
            {
                "id": "concept-source",
                "key": "c_purchase_order",
                "name": "采购订单",
                "description": "采购业务的主单据。",
                "kind": "entity",
                "aliases": ["订单"],
                "attributes": [
                    {"name": "amount", "display_name": "金额", "type": "number"}
                ],
            },
            {
                "id": "concept-target",
                "key": "c_material",
                "name": "物料",
                "description": "采购标的。",
                "kind": "entity",
                "aliases": [],
                "attributes": [],
            },
        ]
        payload = build_bkn_package(
            source,
            concepts,
            [
                {
                    "id": "relation-1",
                    "key": "r_contains",
                    "source_concept_id": "concept-source",
                    "target_concept_id": "concept-target",
                    "name": "包含",
                    "description": "",
                    "kind": "part_of",
                }
            ],
            [],
            [
                {
                    "key": "a_submit",
                    "name": "提交采购订单",
                    "description": "提交订单。",
                    "action_intent": "add",
                    "bound_concept_id": "concept-source",
                    "parameters": [],
                }
            ],
            [
                {
                    "key": "k_approval",
                    "name": "越权审批风险",
                    "description": "未经授权审批。",
                    "severity": "high",
                    "mitigation": "校验角色。",
                }
            ],
            [
                {
                    "key": "g_procurement",
                    "name": "采购",
                    "description": "",
                    "concepts": [
                        {
                            "id": "concept-source",
                            "key": "c_purchase_order",
                            "name": "采购订单",
                        }
                    ],
                }
            ],
            [
                {
                    "key": "m_monthly_spend",
                    "name": "月采购额",
                    "description": "月度采购金额。",
                    "expression": "SUM(amount)",
                    "unit": "元",
                    "concept_id": "concept-source",
                }
            ],
            [
                {
                    "key": "cp_supply_skill",
                    "name": "供应链分析",
                    "kind": "skill",
                    "description": "",
                    "config": {},
                }
            ],
        )[1]

        result = import_bkn_package(target_id, payload, "roundtrip.bkn.tar.gz")
        assert result["concept_count"] == 2
        assert result["relation_count"] == 1
        assert result["action_count"] == 1
        assert result["risk_count"] == 1
        assert result["group_count"] == 1
        assert result["metric_count"] == 1
        assert result["capability_count"] == 1

        imported_concepts = dal.list_concepts(target_id)
        assert {item["name"] for item in imported_concepts} == {"采购订单", "物料"}
        assert dal.list_relations(target_id)[0]["target_name"] == "物料"
        assert dal.list_actions(target_id)[0]["bound_concept_name"] == "采购订单"
        assert dal.list_risks(target_id)[0]["severity"] == "high"
        assert dal.list_metrics(target_id)[0]["expression"] == "SUM(amount)"
        assert dal.list_capabilities(target_id)[0]["name"] == "供应链分析"
        assert [
            item["name"] for item in dal.list_concept_groups(target_id)[0]["concepts"]
        ] == ["采购订单"]
    finally:
        if source_id:
            dal.delete_network(source_id)
        if target_id:
            dal.delete_network(target_id)


def test_network_version_restore() -> None:
    network_id = ""
    try:
        network = dal.create_network(
            name=f"kn-version-{uuid.uuid4().hex[:8]}",
            description="version test",
            domain=None,
            created_by=None,
        )
        network_id = str(network["id"])
        concepts = [
            {
                "id": "version-concept",
                "key": "c_versioned",
                "name": "版本化概念",
                "description": "snapshot",
                "kind": "entity",
                "aliases": [],
                "attributes": [],
            }
        ]
        payload = build_bkn_package(
            network,
            concepts,
            [],
            [],
            [],
            [],
            [
                {
                    "key": "g_versioned",
                    "name": "版本分组",
                    "description": "",
                    "concepts": [
                        {
                            "id": "version-concept",
                            "key": "c_versioned",
                            "name": "版本化概念",
                        }
                    ],
                }
            ],
            [
                {
                    "key": "m_versioned",
                    "name": "版本指标",
                    "description": "",
                    "expression": "COUNT(*)",
                    "unit": "个",
                    "concept_id": "version-concept",
                }
            ],
            [
                {
                    "key": "cp_versioned",
                    "name": "版本能力",
                    "kind": "skill",
                    "description": "",
                    "config": {},
                }
            ],
        )[1]
        import_bkn_package(network_id, payload, "version.bkn.tar.gz")
        version = create_version(network_id, label="before delete", created_by=None)

        concept = dal.list_concepts(network_id)[0]
        dal.update_concept(str(concept["id"]), patch={"name": "版本化概念2"})
        changed_diff = diff_version(str(version["id"]))
        changed = changed_diff["collections"]["concepts"]["changed"][0]
        assert "name" in changed["fields"]
        assert changed["before"]["name"] == "版本化概念"

        dal.delete_concept(str(concept["id"]))
        assert dal.list_concepts(network_id) == []
        diff = diff_version(str(version["id"]))
        assert diff["collections"]["concepts"]["removed"][0]["label"] == "版本化概念"

        restored = restore_version(str(version["id"]))
        assert restored["version"] == version["version"]
        assert [item["name"] for item in dal.list_concepts(network_id)] == [
            "版本化概念"
        ]
        assert dal.list_metrics(network_id)[0]["name"] == "版本指标"
        assert dal.list_concept_groups(network_id)[0]["name"] == "版本分组"
        assert dal.list_capabilities(network_id)[0]["name"] == "版本能力"
    finally:
        if network_id:
            dal.delete_network(network_id)


def test_knowledge_eval_run() -> None:
    network_id = ""
    try:
        network = dal.create_network(
            name=f"kn-eval-{uuid.uuid4().hex[:8]}",
            description="eval test",
            domain=None,
            created_by=None,
        )
        network_id = str(network["id"])
        payload = build_bkn_package(
            network,
            [
                {
                    "id": "eval-concept",
                    "key": "c_eval",
                    "name": "采购审批规则",
                    "description": "采购订单必须审批。",
                    "kind": "rule",
                    "aliases": [],
                    "attributes": [],
                }
            ],
            [],
            [],
        )[1]
        import_bkn_package(network_id, payload, "eval.bkn.tar.gz")
        concept = dal.list_concepts(network_id)[0]
        dal.update_concept(str(concept["id"]), patch={"status": "certified"})
        dal.create_eval_case(
            network_id=network_id,
            question="采购审批规则是什么？",
            expected_concepts=["采购审批规则"],
            expected_facts=[],
            notes=None,
        )
        run = run_evals(network_id)
        assert run["total"] == 1
        assert run["passed"] == 1
        assert run["details"][0]["passed"] is True
    finally:
        if network_id:
            dal.delete_network(network_id)


def test_knowledge_network_zone_scope() -> None:
    zone_id = ""
    network_id = ""
    public_id = ""
    try:
        zone_id = str(
            store().query_write(
                s.zone.insert()
                .values(name=f"knowledge-zone-{uuid.uuid4().hex[:8]}")
                .returning(s.zone.c.id)
            )[0]["id"]
        )
        network = dal.create_network(
            name=f"kn-zoned-{uuid.uuid4().hex[:8]}",
            description=None,
            domain=None,
            zone_id=zone_id,
            created_by=None,
        )
        network_id = str(network["id"])
        public = dal.create_network(
            name=f"kn-public-{uuid.uuid4().hex[:8]}",
            description=None,
            domain=None,
            created_by=None,
        )
        public_id = str(public["id"])

        assert network_id not in {item["id"] for item in dal.list_networks([])}
        assert network_id in {item["id"] for item in dal.list_networks([zone_id])}
        assert dal.get_network(network_id, []) is None
        assert dal.get_network(network_id, [zone_id]) is not None
        assert public_id in {item["id"] for item in dal.list_networks([])}
    finally:
        if network_id:
            dal.delete_network(network_id)
        if public_id:
            dal.delete_network(public_id)
        if zone_id:
            with write_transaction():
                store().query_write(delete(s.zone).where(s.zone.c.id == zone_id))


def test_knowledge_network_explicit_grants() -> None:
    dept_id = ""
    network_id = ""
    try:
        department = access_dal.create_department(
            name=f"knowledge-dept-{uuid.uuid4().hex[:8]}",
            description=None,
            user_ids=[],
        )
        dept_id = str(department["id"])
        network = dal.create_network(
            name=f"kn-grant-{uuid.uuid4().hex[:8]}",
            description=None,
            domain=None,
            created_by=None,
        )
        network_id = str(network["id"])
        dal.replace_network_grants(network_id, user_ids=[], dept_ids=[dept_id])
        dal.replace_network_grants(
            network_id,
            grants=[
                {
                    "subject_type": "department",
                    "subject_id": dept_id,
                    "permission": "edit",
                }
            ],
        )
        assert dal.list_network_grants(network_id)["grants"][0]["permission"] == "edit"
        audits = dal.list_network_grant_audit(network_id)
        assert audits
        assert audits[0]["action"] == "replace"
        assert audits[0]["after"][0]["permission"] == "edit"
        assert network_id not in {
            item["id"] for item in dal.list_networks([], dept_ids=[])
        }
        assert network_id in {
            item["id"] for item in dal.list_networks([], dept_ids=[dept_id])
        }
        assert dal.get_network(network_id, [], dept_ids=[]) is None
        assert dal.get_network(network_id, [], dept_ids=[dept_id]) is not None
        dal.replace_network_grants(
            network_id,
            grants=[
                {
                    "subject_type": "department",
                    "subject_id": dept_id,
                    "permission": "read",
                    "expires_at": (
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                }
            ],
        )
        assert dal.get_network(network_id, [], dept_ids=[dept_id]) is None
    finally:
        if network_id:
            dal.delete_network(network_id)
        if dept_id:
            access_dal.delete_department(dept_id)


def test_knowledge_context_mirrors_the_question_language() -> None:
    """English questions get English scaffolding; the facts stay untouched."""
    suffix = uuid.uuid4().hex[:8]
    network_id = ""
    try:
        network = dal.create_network(
            name=f"kn-i18n-{suffix}",
            description=None,
            domain=None,
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
        dal.save_extraction(
            str(document["id"]),
            summary="Purchase orders require approval.",
            concepts=[
                {
                    "key": "c_purchase_order",
                    "name": "Purchase order",
                    "description": "The main purchasing document.",
                    "kind": "entity",
                    "aliases": [],
                    "attributes": [],
                    "confidence": 0.9,
                    "evidence": [
                        {"page": 2, "block_index": 1, "quote": "Purchase order"}
                    ],
                }
            ],
            relations=[],
            facts=[
                {
                    "subject_key": "c_purchase_order",
                    "object_text": "PO-001",
                    "predicate": "has id",
                    "statement": "The purchase order id is PO-001.",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "page": 2,
                            "block_index": 2,
                            "quote": "purchase order id is PO-001",
                        }
                    ],
                }
            ],
            chunk_count=1,
        )
        concept = dal.list_concepts(network_id)[0]
        fact = dal.list_facts(network_id)[0]
        dal.update_concept(str(concept["id"]), patch={"status": "certified"})
        dal.update_fact(str(fact["id"]), patch={"status": "certified"})

        context = retrieve_knowledge_context("purchase order approval")
        assert "Purchase order" in context
        assert "Evidence, page 2" in context
        assert "证据" not in context
    finally:
        if network_id:
            dal.delete_network(network_id)
