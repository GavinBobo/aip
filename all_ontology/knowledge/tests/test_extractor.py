# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.knowledge.extractor import (
    ExtractedAction,
    ExtractedChunk,
    ExtractedConcept,
    ExtractedFact,
    ExtractedMetric,
    ExtractedRelation,
    ExtractedRisk,
    ExtractedRule,
    concept_key,
    merge_chunks,
)
from all_ontology.knowledge.source import SourceBlock, SourceChunk, chunk_blocks


def test_merge_gives_colliding_slugs_distinct_keys() -> None:
    """Two names that slugify identically must not overwrite each other."""
    chunk = SourceChunk(
        text="A B and A/B are distinct concepts.", page_start=1, page_end=1
    )
    result = ExtractedChunk(
        concepts=[
            ExtractedConcept(name="A B", evidence_quote="A B"),
            ExtractedConcept(name="A/B", evidence_quote="A/B"),
        ]
    )

    merged = merge_chunks([(chunk, result)])

    keys = [concept["key"] for concept in merged.concepts]
    assert len(keys) == len(set(keys)) == 2
    assert {concept["name"] for concept in merged.concepts} == {"A B", "A/B"}


def test_chunking_keeps_page_and_block_locators() -> None:
    blocks = [
        SourceBlock(page=1, idx=0, type="Title", content="采购订单"),
        SourceBlock(
            page=2,
            idx=0,
            type="Text",
            content="订单由采购员创建，金额为 12,480.00 元。",
        ),
    ]
    chunks = chunk_blocks(blocks, max_chars=30)

    assert len(chunks) == 2
    assert chunks[0].page_start == 1
    assert chunks[1].page_start == 2
    page, block = chunks[1].locate("金额为 12,480.00 元")
    assert (page, block) == (2, 0)


def test_merge_keeps_rules_with_evidence_and_concept_link() -> None:
    chunk = SourceChunk(
        text="Purchase orders above 10000 require CFO approval.",
        page_start=1,
        page_end=1,
        blocks=[
            SourceBlock(
                page=1,
                idx=1,
                type="Text",
                content="Purchase orders above 10000 require CFO approval.",
            )
        ],
        spans=[
            (
                0,
                SourceBlock(
                    page=1,
                    idx=1,
                    type="Text",
                    content="Purchase orders above 10000 require CFO approval.",
                ),
            )
        ],
    )
    result = ExtractedChunk(
        concepts=[ExtractedConcept(name="Purchase order", evidence_quote="Purchase order")],
        rules=[
            ExtractedRule(
                name="CFO approval rule",
                statement="Purchase orders above 10000 require CFO approval.",
                roles=["CFO"],
                related_concept="Purchase order",
                evidence_quote="Purchase orders above 10000 require CFO approval.",
            )
        ],
    )

    merged = merge_chunks([(chunk, result)])

    assert len(merged.rules) == 1
    assert merged.rules[0]["roles"] == ["CFO"]
    assert merged.rules[0]["concept_key"] == merged.concepts[0]["key"]
    assert merged.rules[0]["evidence"][0]["page"] == 1


def test_merge_deduplicates_and_keeps_evidence() -> None:
    chunk = SourceChunk(
        text="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。采购员提交采购订单。审批前校验角色权限。月采购额 = SUM(amount)，单位为元。",
        page_start=3,
        page_end=3,
        blocks=[
            SourceBlock(
                page=3,
                idx=2,
                type="Text",
                content="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。采购员提交采购订单。审批前校验角色权限。月采购额 = SUM(amount)，单位为元。",
            )
        ],
        spans=[
            (
                0,
                SourceBlock(
                    page=3,
                    idx=2,
                    type="Text",
                    content="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。采购员提交采购订单。审批前校验角色权限。月采购额 = SUM(amount)，单位为元。",
                ),
            )
        ],
    )
    result = ExtractedChunk(
        summary="采购订单的创建与编号。",
        concepts=[
            ExtractedConcept(
                name="采购订单",
                kind="entity",
                description="采购业务的主单据。",
                aliases=["订单"],
                confidence=0.9,
            )
        ],
        relations=[
            ExtractedRelation(
                source="采购订单",
                target="物料",
                name="包含",
                kind="part_of",
                evidence_quote="订单包含物料",
            )
        ],
        facts=[
            ExtractedFact(
                subject="采购订单",
                predicate="编号为",
                object="PO-001",
                statement="采购订单的编号为 PO-001。",
                evidence_quote="订单编号为 PO-001",
            ),
            ExtractedFact(
                subject="采购订单",
                predicate="由谁创建",
                object="采购员",
                statement="采购订单由采购员创建。",
                evidence_quote="这句不在原文里",
            ),
        ],
        actions=[
            ExtractedAction(
                name="提交采购订单",
                description="采购员提交采购订单。",
                action_intent="add",
                bound_concept="采购订单",
                evidence_quote="采购员提交采购订单",
            )
        ],
        risks=[
            ExtractedRisk(
                name="越权审批风险",
                description="审批前需要校验角色权限。",
                severity="high",
                mitigation="校验角色权限。",
                related_concept="采购订单",
                evidence_quote="审批前校验角色权限",
            )
        ],
        metrics=[
            ExtractedMetric(
                name="月采购额",
                description="月度采购金额。",
                expression="SUM(amount)",
                unit="元",
                related_concept="采购订单",
                evidence_quote="月采购额 = SUM(amount)",
            )
        ],
    )

    merged = merge_chunks([(chunk, result)])

    assert {concept["name"] for concept in merged.concepts} == {"采购订单", "物料"}
    order = next(
        concept for concept in merged.concepts if concept["name"] == "采购订单"
    )
    assert order["aliases"] == ["订单"]
    assert order["evidence"][0]["page"] == 3
    assert merged.relations[0]["evidence"][0]["page"] == 3
    # The unsupported fact is dropped rather than stored as a plausible guess.
    assert [fact["statement"] for fact in merged.facts] == ["采购订单的编号为 PO-001。"]
    assert merged.facts[0]["object_text"] == "PO-001"
    assert merged.actions[0]["bound_key"] == order["key"]
    assert merged.risks[0]["severity"] == "high"
    assert merged.metrics[0]["expression"] == "SUM(amount)"
    assert merged.metrics[0]["unit"] == "元"


def test_concept_key_is_bkn_compatible() -> None:
    assert concept_key("采购订单").startswith("c_")
    assert concept_key("Order Line").startswith("c_order_line")
    for name in ("采购订单", "Order Line", "123"):
        key = concept_key(name)
        assert key[0].islower() or key[0].isdigit()
        assert all(char.islower() or char.isdigit() or char in "_-" for char in key)
