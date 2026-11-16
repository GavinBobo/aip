# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Creating and refreshing a REST-backed connection."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from pytest import MonkeyPatch

from all_ontology.server.connections import apis

FRAME = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})


def _stub(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"stored": [], "deleted": [], "created": [], "ingested": []}

    monkeypatch.setattr(apis, "fetch_frame", lambda _config: FRAME.copy())
    monkeypatch.setattr(
        apis,
        "upsert_dataset",
        lambda **kwargs: calls["stored"].append(kwargs) or {"name": kwargs["name"]},
    )
    monkeypatch.setattr(
        apis, "delete_dataset", lambda name: calls["deleted"].append(name)
    )

    def create_connection(*, connection: dict[str, Any]) -> dict[str, Any]:
        calls["created"].append(connection)
        return connection

    def update_connection(
        *, database_name: str, connection: dict[str, Any]
    ) -> dict[str, Any]:
        calls["created"].append(connection)
        return connection

    monkeypatch.setattr(apis.service, "create_connection", create_connection)
    monkeypatch.setattr(apis.service, "update_connection", update_connection)
    monkeypatch.setattr(apis.service, "_database_already_connected", lambda _n: False)

    import all_ontology.server.ingestion.proxy as proxy

    monkeypatch.setattr(
        proxy, "trigger_ingest", lambda connection: calls["ingested"].append(connection)
    )
    return calls


def _config(**overrides: Any) -> dict[str, Any]:
    values = {"url": "https://api.example.com/rows", "method": "GET"}
    values.update(overrides)
    return values


def test_create_stores_the_snapshot_and_registers_the_connection(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub(monkeypatch)

    connection = apis.create_api_connection(
        database="crm_rows",
        config=_config(
            auth_type="bearer",
            token="secret",
            columns=[{"source": "name", "name": "customer_name"}],
        ),
    )

    assert connection["type"] == "api"
    assert connection["database"] == "crm_rows"
    assert connection["url"] == "https://api.example.com/rows"
    assert connection["row_count"] == 2
    assert connection["columns"] == [
        {"source": "id", "name": "id"},
        {"source": "name", "name": "customer_name"},
    ]
    assert connection["fetched_at"]

    stored = calls["stored"][0]
    assert stored["name"] == "crm_rows"
    assert stored["content"][:4] == b"PAR1"
    assert stored["filename"] == "GET https://api.example.com/rows"


def test_create_rejects_a_bad_url_before_storing(monkeypatch: MonkeyPatch) -> None:
    calls = _stub(monkeypatch)

    with pytest.raises(ValueError, match="http"):
        apis.create_api_connection(database="crm_rows", config={"url": ""})

    assert calls["stored"] == []


def test_a_failed_create_removes_the_snapshot(monkeypatch: MonkeyPatch) -> None:
    calls = _stub(monkeypatch)
    monkeypatch.setattr(
        apis.service,
        "create_connection",
        lambda *, connection: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        apis.create_api_connection(database="crm_rows", config=_config())

    assert calls["deleted"] == ["crm_rows"]


def test_refresh_reuses_the_stored_token_and_reingests(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub(monkeypatch)
    stored = {
        "type": "api",
        "database": "crm_rows",
        "url": "https://api.example.com/rows",
        "method": "GET",
        "auth_type": "bearer",
        "token": "stored-token",
        "columns": [{"source": "id", "name": "customer_id"}],
    }
    monkeypatch.setattr(apis.service, "_stored_connection", lambda _n: stored)
    seen: dict[str, Any] = {}

    def fetch(config: dict[str, Any]) -> pd.DataFrame:
        seen.update(config)
        return FRAME.copy()

    monkeypatch.setattr(apis, "fetch_frame", fetch)

    updated = apis.refresh_api_connection("crm_rows")

    # The UI never receives the token, so a blank one here means "keep it".
    assert seen["token"] == "stored-token"
    assert updated["columns"] == [
        {"source": "id", "name": "customer_id"},
        {"source": "name", "name": "name"},
    ]
    assert calls["stored"][0]["name"] == "crm_rows"
    assert calls["ingested"][0]["database"] == "crm_rows"


def test_refresh_refuses_a_connection_of_another_type(
    monkeypatch: MonkeyPatch,
) -> None:
    _stub(monkeypatch)
    monkeypatch.setattr(
        apis.service,
        "_stored_connection",
        lambda _n: {"type": "file", "database": "crm_rows"},
    )

    with pytest.raises(ValueError, match="not an API connection"):
        apis.refresh_api_connection("crm_rows")
