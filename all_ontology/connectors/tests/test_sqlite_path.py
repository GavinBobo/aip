# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""How a SQLite URI turns into a filesystem path.

The Windows case is the one that bit: ``sqlite:///C:/dir/db.sqlite`` parses to
``/C:/dir/db.sqlite``, and handing that to ``Path`` roots it on the current
drive instead of the file the user meant. The connector then reported "database
not found" for a file that was right there.
"""

from __future__ import annotations

from pathlib import Path

from all_ontology.connectors.sqlite import _sqlite_path_from_connection_string


def test_a_posix_file_uri_keeps_its_absolute_path() -> None:
    assert _sqlite_path_from_connection_string("sqlite:////data/shop.sqlite") == Path(
        "//data/shop.sqlite"
    )


def test_a_windows_drive_uri_drops_the_uri_slash() -> None:
    parsed = _sqlite_path_from_connection_string("sqlite:///C:/data/shop.sqlite")
    assert parsed == Path("C:/data/shop.sqlite")
    assert not str(parsed).startswith("\\C:")


def test_a_windows_uri_with_backslashes_is_accepted() -> None:
    parsed = _sqlite_path_from_connection_string("sqlite:///C:\\Users\\me\\shop.sqlite")
    assert parsed == Path("C:\\Users\\me\\shop.sqlite")


def test_a_bare_path_is_used_verbatim() -> None:
    assert _sqlite_path_from_connection_string("./shop.sqlite") == Path("./shop.sqlite")


def test_percent_escapes_are_decoded() -> None:
    assert _sqlite_path_from_connection_string("sqlite:////tmp/my%20shop.sqlite") == (
        Path("//tmp/my shop.sqlite")
    )
