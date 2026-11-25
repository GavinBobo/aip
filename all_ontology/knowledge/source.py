# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read an OXR parse run back as page-aware blocks.

The parser already stores both Markdown and block JSON. Knowledge extraction
uses the block JSON because a citation needs a page and a block index; the
Markdown is only a fallback for old runs that were saved without ``json`` in
the requested output formats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from all_ontology.parsing.store import get_run


@dataclass
class SourceBlock:
    page: int
    idx: int | None
    type: str | None
    content: str


@dataclass
class SourceChunk:
    text: str
    page_start: int
    page_end: int
    blocks: list[SourceBlock] = field(default_factory=list)
    #: ``(offset_in_text, block)`` so a quote can be traced to a page.
    spans: list[tuple[int, SourceBlock]] = field(default_factory=list)

    def locate(self, quote: str) -> tuple[int | None, int | None]:
        """Return ``(page, block_index)`` for a quote, best effort."""
        text = str(quote or "").strip()
        if not text:
            return self.page_start, None
        position = self.text.find(text)
        if position < 0 and len(text) > 24:
            position = self.text.find(text[:24])
        if position < 0:
            return self.page_start, None
        owner = None
        for offset, block in self.spans:
            if offset <= position:
                owner = block
            else:
                break
        if owner is None:
            return self.page_start, None
        return owner.page, owner.idx


def _read_result(run: dict[str, Any]) -> dict[str, Any]:
    path = run.get("result_path")
    if not path:
        return {}
    try:
        return json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _edited_content(
    run: dict[str, Any], page: int, idx: int | None, content: str
) -> str:
    edits = run.get("edits") or {}
    if idx is None:
        return content
    # The stored edits are keyed by the parser's zero-based page; the page
    # passed here is already one-based for display.
    edit = edits.get(f"{page - 1}:{idx}")
    return str(edit["content"]) if edit and "content" in edit else content


def blocks_for_run(run_id: str) -> tuple[list[SourceBlock], dict[str, Any]]:
    run = get_run(run_id)
    if run is None:
        raise ValueError("Parsing result not found.")
    if run.get("status") != "succeeded":
        raise ValueError(
            "Knowledge can only be extracted from a successful parsing result."
        )
    record = _read_result(run)
    outputs = record.get("outputs") or {}

    blocks: list[SourceBlock] = []
    pages = ((outputs.get("json") or {}).get("pages")) or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_number = int(page.get("page_num") or 0) + 1
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            content = str(block.get("content") or "").strip()
            if not content:
                continue
            idx = block.get("idx")
            blocks.append(
                SourceBlock(
                    page=page_number,
                    idx=int(idx) if isinstance(idx, int) else None,
                    type=str(block.get("type") or "") or None,
                    content=_edited_content(run, page_number, idx, content),
                )
            )
    if not blocks:
        markdown = str(outputs.get("markdown") or "").strip()
        if markdown:
            blocks.append(
                SourceBlock(page=1, idx=None, type="Markdown", content=markdown)
            )

    if not blocks:
        raise ValueError("This parsing result has no text to extract from.")
    metadata = {
        "run_id": run_id,
        "file_name": record.get("file_name") or run.get("file_name"),
        "source_name": record.get("source_name") or run.get("source_name"),
        "page_count": run.get("page_count"),
    }
    return blocks, metadata


def chunk_blocks(
    blocks: list[SourceBlock],
    *,
    max_chars: int = 6000,
    max_chunks: int = 12,
) -> list[SourceChunk]:
    """Group blocks into page-aware chunks without splitting a block."""
    chunks: list[SourceChunk] = []
    current: list[SourceBlock] = []
    current_chars = 0

    def finish() -> None:
        nonlocal current, current_chars
        if not current:
            return
        text_parts: list[str] = []
        spans: list[tuple[int, SourceBlock]] = []
        offset = 0
        for block in current:
            if text_parts:
                text_parts.append("\n\n")
                offset += 2
            spans.append((offset, block))
            text_parts.append(block.content)
            offset += len(block.content)
        chunks.append(
            SourceChunk(
                text="".join(text_parts),
                page_start=current[0].page,
                page_end=current[-1].page,
                blocks=list(current),
                spans=spans,
            )
        )
        current = []
        current_chars = 0

    expanded: list[SourceBlock] = []
    for block in blocks:
        if len(block.content) <= max_chars:
            expanded.append(block)
            continue
        # A Markdown fallback is one block that can be much larger than the
        # model window. Split it while keeping the same page/idx so citations
        # still point at the page they came from.
        for start in range(0, len(block.content), max_chars):
            expanded.append(
                SourceBlock(
                    page=block.page,
                    idx=block.idx,
                    type=block.type,
                    content=block.content[start : start + max_chars],
                )
            )

    for block in expanded:
        length = len(block.content)
        if current and current_chars + length + 2 > max_chars:
            finish()
        current.append(block)
        current_chars += length + 2
        if current_chars >= max_chars:
            finish()
    finish()
    return chunks[:max_chunks]
