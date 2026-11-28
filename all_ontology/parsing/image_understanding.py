# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Interpret extracted document pictures with the configured vision model.

The parser already crops every Picture block and writes a PNG. This pass adds
the missing semantic half: hash the crop, compare its pixel area with the
configured threshold, and (when it qualifies) ask the VLM for a reading. The
reading is written back onto the block so knowledge extraction can cite it as
text, and a structured record is returned for ``parsing_image``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from all_ontology.parsing.config.settings import settings
from all_ontology.parsing.model.client import model_client

logger = logging.getLogger(__name__)

_IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _picture_blocks(result: dict[str, Any]):
    pages = ((result.get("outputs") or {}).get("json") or {}).get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_num") or 0) + 1
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").lower() != "picture":
                continue
            if not str(block.get("content") or "").strip():
                continue
            yield page_no, block


def _local_path(content: str, *, image_dir: Path, url_prefix: str) -> Path | None:
    match = _IMAGE_LINK.search(content or "")
    if not match:
        return None
    url = match.group(1).strip()
    prefix = url_prefix.rstrip("/")
    if url.startswith(prefix + "/"):
        relative = url[len(prefix) + 1 :]
        return image_dir / relative
    candidate = Path(url)
    if candidate.is_absolute():
        return candidate
    return None


def _image_url(content: str) -> str | None:
    match = _IMAGE_LINK.search(content or "")
    return match.group(1).strip() if match else None


async def understand_result_images(
    result: dict[str, Any],
    *,
    prompt: str,
    min_area_px: int,
    enabled: bool,
    max_tokens: int,
    model_options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Annotate Picture blocks and return ``parsing_image`` row payloads.

    A VLM failure never fails the parse: the row carries ``failed`` and the
    error text, and the document still finishes with its Markdown/blocks.
    """
    image_dir = Path(settings.pipeline.image_output_dir).resolve()
    prefix = settings.pipeline.image_url_prefix
    semaphore = asyncio.Semaphore(max(1, settings.pipeline.image_vlm_concurrency))

    async def one(page: int, block: dict[str, Any]) -> dict[str, Any]:
        content = str(block.get("content") or "")
        url = _image_url(content)
        path = None
        payload: bytes | None = None
        if url and url.startswith("data:image/") and ";base64," in url:
            try:
                payload = base64.b64decode(url.split(",", 1)[1])
            except Exception:  # noqa: BLE001 - malformed inline image
                payload = None
        else:
            path = _local_path(content, image_dir=image_dir, url_prefix=prefix)
            if path is not None and path.is_file():
                payload = await asyncio.to_thread(path.read_bytes)
        record: dict[str, Any] = {
            "page": page,
            "block_index": int(block.get("idx") or 0),
            "image_path": "" if (url or "").startswith("data:") else (url or ""),
            "image_file_path": str(path) if path is not None else None,
            "vlm_prompt": prompt,
            "vlm_status": "failed",
            "vlm_content": None,
            "vlm_error": None,
            "width": None,
            "height": None,
            "area_px": None,
            "image_md5": "",
        }
        if payload is None:
            record["vlm_error"] = "extracted image file is missing"
            block["vlm_status"] = "failed"
            block["vlm_error"] = record["vlm_error"]
            return record

        image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            record["vlm_error"] = "extracted image could not be decoded"
            block["vlm_status"] = "failed"
            block["vlm_error"] = record["vlm_error"]
            return record

        height, width = int(image.shape[0]), int(image.shape[1])
        area = width * height
        record.update(
            {
                "image_md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                "width": width,
                "height": height,
                "area_px": area,
            }
        )
        block["image_md5"] = record["image_md5"]
        block["image_path"] = record["image_path"]
        block["area_px"] = area

        if not enabled:
            record["vlm_status"] = "disabled"
            block["vlm_status"] = "disabled"
            return record
        if area < min_area_px:
            record["vlm_status"] = "skipped_small"
            block["vlm_status"] = "skipped_small"
            return record

        try:
            async with semaphore:
                text = await model_client.describe_image(
                    prompt,
                    image,
                    model_options=model_options,
                    max_tokens=max_tokens,
                )
            record["vlm_content"] = str(text).strip()
            record["vlm_status"] = "succeeded"
            block["vlm_content"] = record["vlm_content"]
            block["vlm_status"] = "succeeded"
            if record["vlm_content"]:
                # Knowledge extraction reads block content. Appending the
                # reading makes picture-only pages learnable without teaching
                # the extractor a second input format.
                block["content"] = (
                    f"{content}\n\n[Image interpretation]\n{record['vlm_content']}"
                )
        except Exception as error:  # noqa: BLE001 - pictures are best-effort
            record["vlm_status"] = "failed"
            record["vlm_error"] = (str(error) or type(error).__name__)[:1000]
            block["vlm_status"] = "failed"
            block["vlm_error"] = record["vlm_error"]
            logger.warning(
                "Image interpretation failed (page=%s, block=%s): %s",
                page,
                block.get("idx"),
                record["vlm_error"],
            )
        return record

    records = await asyncio.gather(
        *(one(page, block) for page, block in _picture_blocks(result))
    )
    return list(records)
