# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The table-detail data preview."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pytest import MonkeyPatch

from all_ontology.server.exploration import service


class _Connector:
    dialect = "postgres"

    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        self.database_name = "shop"
        self._frame = frame if frame is not None else pd.DataFrame({"a": [1]})
        self.statements: list[str] = []

    def qualify(self, schema: str | None, table: str) -> str:
        return f'"{schema}"."{table}"'

    def execute(self, sql: str, **_kwargs: Any) -> pd.DataFrame:
        self.statements.append(sql)
        return self._frame


def _stub(monkeypatch: MonkeyPatch, connector: Any) -> None:
    monkeypatch.setattr(
        service,
        "fetch_table_location",
        lambda _id: {
            "id": _id,
            "name": "orders",
            "schema_name": "public",
            "database_name": "shop",
        },
    )
    monkeypatch.setattr(service, "get_connectors", lambda: [connector])


def test_preview_quotes_the_table_and_bounds_the_query(
    monkeypatch: MonkeyPatch,
) -> None:
    connector = _Connector(pd.DataFrame({"id": [1, 2]}))
    _stub(monkeypatch, connector)

    result = service.fetch_table_preview("t1", limit=10)

    assert connector.statements == ['SELECT * FROM "public"."orders" LIMIT 11']
    assert result["columns"] == ["id"]
    assert result["row_count"] == 2
    assert result["truncated"] is False


def test_preview_reports_truncation(monkeypatch: MonkeyPatch) -> None:
    connector = _Connector(pd.DataFrame({"id": [1, 2, 3]}))
    _stub(monkeypatch, connector)

    result = service.fetch_table_preview("t1", limit=2)

    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert result["rows"] == [[1], [2]]


def test_preview_serialises_values_for_json() -> None:
    assert service._preview_value(None) is None
    assert service._preview_value(float("nan")) is None
    assert (
        service._preview_value(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"
    )
    assert service._preview_value(date(2024, 1, 2)) == "2024-01-02"
    assert service._preview_value(Decimal("10.50")) == 10.5
    assert service._preview_value(True) is True
    assert service._preview_value(b"\x00\x01") == "0001"
    # numpy scalars are what a DataFrame yields, and JSON cannot encode them.
    assert service._preview_value(pd.NA) is None


def test_preview_unknown_table_is_a_lookup_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(service, "fetch_table_location", lambda _id: None)

    with pytest.raises(LookupError, match="No table"):
        service.fetch_table_preview("missing")


def test_preview_without_a_connector_is_a_lookup_error(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "fetch_table_location",
        lambda _id: {
            "id": _id,
            "name": "orders",
            "schema_name": "public",
            "database_name": "gone",
        },
    )
    monkeypatch.setattr(service, "get_connectors", lambda: [])

    with pytest.raises(LookupError, match="No live connection"):
        service.fetch_table_preview("t1")
