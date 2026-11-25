# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from all_ontology.parsing import sources


def test_browse_and_scan_any_readable_folder(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.7")
    (nested / "b.PDF").write_bytes(b"%PDF-1.7")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    listing = sources.browse_server_path(str(tmp_path))
    assert listing["path"] == str(tmp_path.resolve())
    assert [entry["name"] for entry in listing["entries"]] == ["nested"]

    found = sources.scan_server_files(str(tmp_path), suffixes={".pdf"}, max_files=10)
    assert [item["relative"] for item in found] == ["a.pdf", "nested/b.PDF"]


def test_optional_allowlist_can_narrow_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv("PARSING_SOURCE_ROOTS", str(allowed))

    assert sources.browse_server_path(str(allowed))["path"] == str(allowed.resolve())
    with pytest.raises(ValueError, match="PARSING_SOURCE_ROOTS"):
        sources.browse_server_path(str(outside))
