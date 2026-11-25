# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import io
import tarfile

from all_ontology.knowledge.bkn import build_bkn_package


def _files(payload: bytes) -> dict[str, str]:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        return {
            member.name: archive.extractfile(member).read().decode("utf-8")
            for member in archive.getmembers()
            if member.isfile()
        }


def test_bkn_package_has_network_objects_relations_and_evidence() -> None:
    network = {
        "name": "采购知识",
        "description": "从采购制度与订单中抽取。",
        "version": "1.0",
        "domain": "供应链",
    }
    concepts = [
        {
            "id": "concept-1",
            "key": "c_purchase_order",
            "name": "采购订单",
            "description": "采购业务的主单据。",
            "kind": "entity",
            "aliases": ["订单"],
            "attributes": [
                {
                    "name": "金额",
                    "display_name": "金额",
                    "type": "number",
                    "description": "含税金额",
                }
            ],
            "confidence": 0.9,
            "status": "certified",
        },
        {
            "id": "concept-2",
            "key": "c_material",
            "name": "物料",
            "description": "采购标的。",
            "kind": "entity",
            "aliases": [],
            "attributes": [],
            "confidence": 0.8,
            "status": "draft",
        },
    ]
    relations = [
        {
            "id": "relation-1",
            "key": "r_contains",
            "source_concept_id": "concept-1",
            "target_concept_id": "concept-2",
            "name": "包含",
            "description": "订单包含物料。",
            "kind": "part_of",
            "confidence": 0.85,
        }
    ]
    facts = [
        {
            "statement": "采购订单 PO-001 的金额为 12,480.00 元。",
            "evidence": [
                {"page": 3, "block_index": 2, "quote": "合计金额：人民币 12,480.00 元"}
            ],
        }
    ]
    actions = [
        {
            "key": "a_submit_order",
            "name": "提交采购订单",
            "description": "采购员提交订单。",
            "action_intent": "add",
            "bound_concept_id": "concept-1",
            "parameters": [{"name": "order_id", "type": "string"}],
        }
    ]
    risks = [
        {
            "key": "k_approval_risk",
            "name": "越权审批风险",
            "description": "未经授权审批。",
            "severity": "high",
            "mitigation": "校验角色。",
        }
    ]
    groups = [
        {
            "key": "g_procurement",
            "name": "采购",
            "description": "采购相关概念",
            "concepts": [
                {"id": "concept-1", "key": "c_purchase_order", "name": "采购订单"}
            ],
        }
    ]
    metrics = [
        {
            "key": "m_monthly_spend",
            "name": "月采购额",
            "description": "月度采购金额。",
            "expression": "SUM(amount)",
            "unit": "元",
            "concept_id": "concept-1",
        }
    ]
    capabilities = [
        {
            "key": "cp_supply_skill",
            "name": "供应链分析",
            "kind": "skill",
            "description": "",
            "config": {},
        }
    ]

    filename, payload = build_bkn_package(
        network,
        concepts,
        relations,
        facts,
        actions,
        risks,
        groups,
        metrics,
        capabilities,
    )
    files = _files(payload)

    assert filename.endswith(".bkn.tar.gz")
    assert 'bkn_spec: "3.0"' in files["network.bkn"]
    assert "object_types/c_purchase_order.bkn" in files
    assert "relation_types/r_contains.bkn" in files
    assert "action_types/a_submit_order.bkn" in files
    assert "risk_types/k_approval_risk.bkn" in files
    assert "concept_groups/g_procurement.bkn" in files
    assert "object_metrics/m_monthly_spend@1.json" in files
    assert "SUM(amount)" in files["object_metrics/m_monthly_spend@1.json"]
    assert "capabilities:" in files["network.bkn"]
    assert "供应链分析" in files["network.bkn"]
    assert "| concept_id | concept-1 |" not in files["relation_types/r_contains.bkn"]
    assert (
        "| c_purchase_order | c_material | direct |"
        in files["relation_types/r_contains.bkn"]
    )
    assert "Primary Keys: concept_id" in files["object_types/c_purchase_order.bkn"]
    # The package scaffolding stays English so bkn-foundry tools can parse it;
    # object names and descriptions keep the language they were extracted in.
    assert "Extraction confidence:" in files["object_types/c_purchase_order.bkn"]
    assert "Aliases: " in files["object_types/c_purchase_order.bkn"]
    assert "Severity:" in files["risk_types/k_approval_risk.bkn"]
    assert "Mitigation:" in files["risk_types/k_approval_risk.bkn"]
    assert "12,480.00" in files["evidence.json"]
