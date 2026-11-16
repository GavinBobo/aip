# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""How a picture block is written into the Markdown answer.

The three formats the API advertises have to mean something:

* ``url``    — a link the app can actually resolve (``/api/parsing/assets/...``)
* ``base64`` — a self-contained ``.md`` with the pixels inline
* ``none``   — the picture is dropped

Everything here is a pure function on a small array, so it costs milliseconds —
unlike the pipeline, which needs both model services.
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

from all_ontology.parsing.config.settings import settings
from all_ontology.parsing.service import (
    create_instance,
    delete_instance,
    list_instances,
    read_instance,
    write_result,
)
from all_ontology.parsing.pipeline.models import Block, BlockType, ContentFormat
from all_ontology.parsing.pipeline.postprocess.picture_postprocess import (
    document_slug,
    postprocess_picture,
)


def _block() -> Block:
    return Block(
        idx=3,
        type=BlockType.PICTURE,
        bbox=[0.0, 0.0, 20.0, 20.0],
        content="",
        format=ContentFormat.TEXT,
    )


def _crop() -> np.ndarray:
    # 20x20 BGR with a gradient, so the encoder has real content to write.
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(20, dtype=np.uint8) * 12
    image[:, :, 1] = 200
    return image


@pytest.fixture
def asset_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        settings.pipeline, "image_output_dir", str(tmp_path), raising=False
    )
    return tmp_path


def test_url_mode_emits_a_link_the_app_can_serve(asset_dir: Path) -> None:
    block = postprocess_picture(_block(), _crop(), "invoice.pdf", 0, {"image": "url"})

    assert block.content == "![](/api/parsing/assets/invoice/imgs/0_3.png)"
    assert block.format == ContentFormat.MARKDOWN
    written = asset_dir / "invoice" / "imgs" / "0_3.png"
    assert written.is_file() and written.stat().st_size > 0


def test_base64_mode_is_self_contained(asset_dir: Path) -> None:
    block = postprocess_picture(
        _block(), _crop(), "invoice.pdf", 0, {"image": "base64"}
    )

    assert block.content.startswith("![](data:image/png;base64,")
    payload = block.content[len("![](data:image/png;base64,") : -len(")")]
    assert base64.b64decode(payload)[:4] == b"\x89PNG"
    # Nothing is written to disk in this mode.
    assert not any(asset_dir.rglob("*.png"))


def test_none_mode_drops_the_picture(asset_dir: Path) -> None:
    block = postprocess_picture(_block(), _crop(), "invoice.pdf", 0, {"image": "none"})
    assert block.content == ""
    assert not any(asset_dir.rglob("*.png"))


def test_the_default_is_a_link(asset_dir: Path) -> None:
    block = postprocess_picture(_block(), _crop(), "invoice.pdf", 0, None)
    assert block.content.startswith("![](/api/parsing/assets/")


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("report.pdf", "report"),
        ("Quarter 3 / 报表.pdf", "Quarter-3"),
        ("../../etc/passwd", "etc-passwd"),
        ("", "document"),
    ],
)
def test_document_slug_stays_inside_the_asset_directory(
    file_name: str, expected: str
) -> None:
    """A filename must not be able to steer the write out of the asset folder."""
    slug = document_slug(file_name)
    assert slug == expected
    assert "/" not in slug and "\\" not in slug and ".." not in slug


def test_the_uploaded_file_is_kept_under_the_configured_directory(
    asset_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source document has to outlive the request that parsed it."""
    monkeypatch.setattr(settings.pipeline, "upload_dir", str(asset_dir), raising=False)

    instance = create_instance(b"%PDF-1.4 fake", "Quarter 3 / 报表.pdf")

    assert instance is not None
    # <upload_dir>/<document>/<run>/<file>: the run folder is what makes two
    # uploads of the same name two instances rather than one overwritten one.
    assert instance.document == "Quarter-3"
    assert instance.source.parent == instance.directory
    assert instance.directory.parent.name == "Quarter-3"
    assert instance.source.name == "报表.pdf"
    assert instance.source.read_bytes() == b"%PDF-1.4 fake"
    # Inside the configured directory, not beside it.
    assert asset_dir in instance.source.parents


def test_a_name_that_cannot_be_written_is_sanitised(
    asset_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.pipeline, "upload_dir", str(asset_dir), raising=False)

    instance = create_instance(b"x", "bad:na*me?.png")

    assert instance is not None
    assert instance.source.name == "bad_na_me_.png"
    assert instance.source.is_file()


def test_a_bad_upload_directory_does_not_fail_the_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only volume should cost the stored copy, not the answer."""
    monkeypatch.setattr(
        settings.pipeline, "upload_dir", "Z:\\definitely-not-here", raising=False
    )
    assert create_instance(b"x", "a.png") is None


def test_a_finished_run_can_be_listed_read_and_deleted(
    asset_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 解析实例 page is just the disc: write, list, read, remove."""
    monkeypatch.setattr(settings.pipeline, "upload_dir", str(asset_dir), raising=False)
    instance = create_instance(b"%PDF-1.4 fake", "invoice.pdf")
    assert instance is not None

    write_result(
        instance,
        {
            "file_name": "invoice.pdf",
            "outputs": {"markdown": "# Invoice"},
            "metadata": {"page_num": 2, "processing_time_ms": 12.5},
        },
    )

    listed = list_instances()
    assert [entry["id"] for entry in listed] == [instance.id]
    # The list is an index, not a payload: the answer stays behind the detail call.
    assert "outputs" not in listed[0]
    assert listed[0]["page_num"] == 2
    assert listed[0]["has_markdown"] is True

    detail = read_instance(instance.document, instance.run)
    assert detail["outputs"]["markdown"] == "# Invoice"
    assert detail["metadata"]["page_num"] == 2

    delete_instance(instance.document, instance.run)
    assert list_instances() == []
    assert not instance.directory.exists()


@pytest.mark.parametrize(
    ("document", "run"),
    [("..", "20260101-000000-abcdef"), ("ok", "../../etc"), ("ok", "not-a-run-id")],
)
def test_instance_ids_cannot_walk_out_of_the_upload_directory(
    asset_dir: Path, monkeypatch: pytest.MonkeyPatch, document: str, run: str
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(settings.pipeline, "upload_dir", str(asset_dir), raising=False)
    with pytest.raises(HTTPException) as caught:
        read_instance(document, run)
    assert caught.value.status_code == 404
