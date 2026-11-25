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

    filename, payload = build_bkn_package(network, concepts, relations, facts)
    files = _files(payload)

    assert filename.endswith(".bkn.tar.gz")
    assert 'bkn_spec: "3.0"' in files["network.bkn"]
    assert "object_types/c_purchase_order.bkn" in files
    assert "relation_types/r_contains.bkn" in files
    assert "| concept_id | concept-1 |" not in files["relation_types/r_contains.bkn"]
    assert (
        "| c_purchase_order | c_material | direct |"
        in files["relation_types/r_contains.bkn"]
    )
    assert "Primary Keys: concept_id" in files["object_types/c_purchase_order.bkn"]
    assert "12,480.00" in files["evidence.json"]
