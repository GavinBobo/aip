# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One page through the whole pipeline, with only the two HTTP calls faked.

Everything between "bytes in" and "Markdown out" runs for real: the image is
decoded by opencv, the layout response is parsed by ``parse_layout_batch``, the
recognition orchestration crops each block out of the page, the assembler puts
the blocks in reading order and both emitters run. Only ``/inference`` and the
vision model are replaced — they are the two things that need a GPU host.

That is exactly the boundary the port touched: import paths and the service
layer, not the algorithms. If this passes, "moved to another package" did not
break the pipeline; whether the real model produces good text is a different
question, and one only a real endpoint can answer.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from auto_ontology.parsing.config.settings import settings
from auto_ontology.parsing.pipeline import layout as layout_module
from auto_ontology.parsing.pipeline import recognition as recognition_module
from auto_ontology.parsing.pipeline.orchestrator import process_document


def _png(width: int = 200, height: int = 80) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def one_text_block(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake the layout service and the vision model; record what was recognised."""
    recognised: list[str] = []

    # The service is told to return blocks already in reading order, which skips
    # the separate reading-order model call — the third HTTP dependency.
    monkeypatch.setattr(
        settings.layout_analyze_model, "provides_reading_order", True, raising=False
    )

    async def fake_request_batch(encoded_images: object) -> dict:
        return {
            "status": "success",
            "params": {},
            "data": {
                # 3 is BlockType.TEXT in LA_CLASS_ID_TO_BLOCK_TYPE.
                "labels": [[3]],
                "boxes": [[[8.0, 8.0, 180.0, 60.0]]],
                "scores": [[0.95]],
            },
        }

    async def fake_recognize_text(image: object, model_options: object = None) -> str:
        recognised.append("called")
        return "发票金额 1,280.00 元"

    monkeypatch.setattr(
        layout_module.layout_client, "request_batch", fake_request_batch
    )
    monkeypatch.setattr(
        recognition_module.model_client, "recognize_text", fake_recognize_text
    )
    return recognised


def test_one_page_becomes_markdown_and_json(one_text_block: list[str]) -> None:
    result = asyncio.run(process_document(_png(), "receipt.png", ["markdown", "json"]))

    assert one_text_block == ["called"], "the vision model must be asked for the block"
    assert result["file_name"] == "receipt.png"

    markdown = result["outputs"]["markdown"]
    assert "发票金额 1,280.00 元" in markdown

    # JSON keeps the layout, which is what an agent consumes.
    payload = result["outputs"]["json"]
    assert payload, "json output must not be empty"
    assert "发票金额" in str(payload)

    assert result["metadata"]["page_num"] == 1
    assert result["metadata"]["file_type"] == ".png"
    assert result["metadata"]["processing_time_ms"] >= 0


def test_markdown_can_be_skipped(one_text_block: list[str]) -> None:
    """Asking for JSON alone must not pay for the Markdown renderer."""
    result = asyncio.run(process_document(_png(), "receipt.png", ["json"]))
    assert "markdown" not in result["outputs"]
    assert result["outputs"]["json"]
