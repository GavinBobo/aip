# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio

import cv2
import numpy as np

from all_ontology.parsing.config.settings import settings
from all_ontology.parsing.image_understanding import understand_result_images
from all_ontology.parsing.model.client import model_client


def _result() -> dict:
    return {
        "outputs": {
            "json": {
                "pages": [
                    {
                        "page_num": 0,
                        "blocks": [
                            {
                                "idx": 0,
                                "type": "Picture",
                                "content": (
                                    "![](/api/parsing/assets/doc/imgs/0_0.png)"
                                ),
                            }
                        ],
                    }
                ]
            }
        }
    }


def _write_picture(tmp_path, width: int = 10, height: int = 10):
    directory = tmp_path / "assets" / "doc" / "imgs"
    directory.mkdir(parents=True)
    path = directory / "0_0.png"
    cv2.imwrite(str(path), np.zeros((height, width, 3), dtype=np.uint8))
    return directory.parent.parent


def test_small_or_disabled_pictures_are_recorded_without_vlm(
    monkeypatch, tmp_path
) -> None:
    image_dir = _write_picture(tmp_path)
    monkeypatch.setattr(settings.pipeline, "image_output_dir", str(image_dir))
    monkeypatch.setattr(settings.pipeline, "image_url_prefix", "/api/parsing/assets")

    disabled = asyncio.run(
        understand_result_images(
            _result(),
            prompt="describe",
            min_area_px=50,
            enabled=False,
            max_tokens=64,
        )
    )
    assert disabled[0]["vlm_status"] == "disabled"
    assert disabled[0]["area_px"] == 100
    assert len(disabled[0]["image_md5"]) == 32

    too_small = asyncio.run(
        understand_result_images(
            _result(),
            prompt="describe",
            min_area_px=101,
            enabled=True,
            max_tokens=64,
        )
    )
    assert too_small[0]["vlm_status"] == "skipped_small"


def test_vlm_content_is_written_back_to_the_block(monkeypatch, tmp_path) -> None:
    image_dir = _write_picture(tmp_path)
    monkeypatch.setattr(settings.pipeline, "image_output_dir", str(image_dir))
    monkeypatch.setattr(settings.pipeline, "image_url_prefix", "/api/parsing/assets")
    monkeypatch.setattr(settings.pipeline, "image_vlm_concurrency", 1)

    async def fake_describe(prompt, image, *, model_options=None, max_tokens=None):
        return "图表显示月度采购金额持续上升。"

    monkeypatch.setattr(model_client, "describe_image", fake_describe)
    result = _result()

    records = asyncio.run(
        understand_result_images(
            result,
            prompt="describe",
            min_area_px=50,
            enabled=True,
            max_tokens=64,
        )
    )

    assert records[0]["vlm_status"] == "succeeded"
    assert "月度采购金额" in records[0]["vlm_content"]
    block = result["outputs"]["json"]["pages"][0]["blocks"][0]
    assert block["vlm_status"] == "succeeded"
    assert "[Image interpretation]" in block["content"]
