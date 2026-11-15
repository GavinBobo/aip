# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The data tree labels each database with the kind of source behind it."""

from __future__ import annotations

from typing import Any

from pytest import MonkeyPatch

from auto_ontology.dal import connections as dal_connections
from auto_ontology.server.datasources import router


def _databases() -> list[dict[str, Any]]:
    return [
        {
            "id": "1",
            "name": "shop",
            "description": None,
            "num_of_schemas": 1,
            "schemas": [],
            "owner_id": None,
        },
        {
            "id": "2",
            "name": "env_only",
            "description": None,
            "num_of_schemas": 1,
            "schemas": [],
            "owner_id": None,
        },
    ]


def test_databases_carry_their_connection_type(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        router.dal, "fetch_databases", lambda zone_ids=None: _databases()
    )
    monkeypatch.setattr(
        dal_connections,
        "list_connections",
        lambda: [{"database": "shop", "type": "file"}],
    )

    payload = router.list_databases()

    by_name = {row["name"]: row["source_type"] for row in payload["data"]}
    assert by_name == {"shop": "file", "env_only": None}


def test_a_broken_connection_store_does_not_break_the_tree(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        router.dal, "fetch_databases", lambda zone_ids=None: _databases()
    )

    def boom() -> list[dict[str, Any]]:
        raise RuntimeError("store down")

    monkeypatch.setattr(dal_connections, "list_connections", boom)

    payload = router.list_databases()

    assert [row["source_type"] for row in payload["data"]] == [None, None]
