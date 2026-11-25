# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.knowledge.extractor import (
    ExtractedChunk,
    ExtractedConcept,
    ExtractedFact,
    ExtractedRelation,
    concept_key,
    merge_chunks,
)
from all_ontology.knowledge.source import SourceBlock, SourceChunk, chunk_blocks


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
    chunks = chunk_blocks(blocks, max_chars=20)

    assert len(chunks) == 2
    assert chunks[0].page_start == 1
    assert chunks[1].page_start == 2
    page, block = chunks[1].locate("金额为 12,480.00 元")
    assert (page, block) == (2, 0)


def test_merge_deduplicates_and_keeps_evidence() -> None:
    chunk = SourceChunk(
        text="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。",
        page_start=3,
        page_end=3,
        blocks=[
            SourceBlock(
                page=3,
                idx=2,
                type="Text",
                content="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。",
            )
        ],
        spans=[
            (
                0,
                SourceBlock(
                    page=3,
                    idx=2,
                    type="Text",
                    content="采购订单由采购员创建。订单包含物料。订单编号为 PO-001。",
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


def test_concept_key_is_bkn_compatible() -> None:
    assert concept_key("采购订单").startswith("c_")
    assert concept_key("Order Line").startswith("c_order_line")
    for name in ("采购订单", "Order Line", "123"):
        key = concept_key(name)
        assert key[0].islower() or key[0].isdigit()
        assert all(char.islower() or char.isdigit() or char in "_-" for char in key)
