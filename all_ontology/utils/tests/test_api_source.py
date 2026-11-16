# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reading a REST endpoint into a DataFrame."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
from pytest import MonkeyPatch

from all_ontology.utils import api_source
from all_ontology.utils.api_source import (
    ApiSourceError,
    apply_column_names,
    fetch_frame,
    normalize_config,
    preview_api,
)


class _Response:
    def __init__(
        self,
        payload: Any = None,
        *,
        status_code: int = 200,
        content_type: str = "application/json",
        raw: bytes | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._raw = raw if raw is not None else json.dumps(payload).encode()

    @property
    def content(self) -> bytes:
        return self._raw

    @property
    def text(self) -> str:
        return self._raw.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _config(**overrides: Any) -> dict[str, Any]:
    values = {"url": "https://api.example.com/v1/customers", "method": "GET"}
    values.update(overrides)
    return normalize_config(values)


def test_normalize_config_parses_text_json_and_defaults() -> None:
    config = normalize_config(
        {
            "url": "https://api.example.com/v1/customers",
            "headers": '{"Accept": "application/json"}',
            "params": '{"limit": "10"}',
        }
    )

    assert config["method"] == "GET"
    assert config["headers"] == {"Accept": "application/json"}
    assert config["params"] == {"limit": "10"}
    assert config["auth_type"] == "none"
    assert config["timeout_s"] == 30


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"url": ""}, "http"),
        ({"url": "ftp://example.com"}, "http"),
        ({"url": "https://x", "method": "DELETE"}, "Method"),
        ({"url": "https://x", "auth_type": "oauth"}, "Auth"),
        ({"url": "https://x", "headers": "{bad"}, "headers"),
        ({"url": "https://x", "method": "GET", "body": '{"a": 1}'}, "body"),
    ],
)
def test_normalize_config_rejects_bad_values(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ApiSourceError, match=message):
        normalize_config(raw)


def test_rows_are_found_under_common_wrappers(monkeypatch: MonkeyPatch) -> None:
    payload = {"data": {"items": [{"id": 1, "name": "Alice"}]}}
    monkeypatch.setattr(api_source.httpx, "request", lambda *a, **k: _Response(payload))

    frame = fetch_frame(_config())

    assert frame.to_dict(orient="records") == [{"id": 1, "name": "Alice"}]


def test_records_path_wins_over_detection(monkeypatch: MonkeyPatch) -> None:
    payload = {"data": [{"id": 1}], "extra": {"rows": [{"id": 2}, {"id": 3}]}}
    monkeypatch.setattr(api_source.httpx, "request", lambda *a, **k: _Response(payload))

    frame = fetch_frame(_config(records_path="extra.rows"))

    assert frame["id"].tolist() == [2, 3]


def test_a_missing_records_path_is_an_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_source.httpx, "request", lambda *a, **k: _Response({"data": []})
    )

    with pytest.raises(ApiSourceError, match="records_path"):
        fetch_frame(_config(records_path="nope.rows"))


def test_nested_objects_are_flattened_and_lists_become_text(
    monkeypatch: MonkeyPatch,
) -> None:
    payload = [
        {"id": 1, "customer": {"name": "Alice"}, "tags": ["a", "b"]},
    ]
    monkeypatch.setattr(api_source.httpx, "request", lambda *a, **k: _Response(payload))

    frame = fetch_frame(_config())

    assert frame.loc[0, "customer.name"] == "Alice"
    assert json.loads(frame.loc[0, "tags"]) == ["a", "b"]


def test_bearer_auth_sets_the_header(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def request(*_args: Any, **kwargs: Any) -> _Response:
        seen.update(kwargs)
        return _Response([{"id": 1}])

    monkeypatch.setattr(api_source.httpx, "request", request)
    fetch_frame(_config(auth_type="bearer", token="secret-token"))

    assert seen["headers"]["Authorization"] == "Bearer secret-token"


def test_bearer_without_a_token_is_an_error() -> None:
    with pytest.raises(ApiSourceError, match="bearer token"):
        fetch_frame(_config(auth_type="bearer"))


def test_http_errors_are_reported(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_source.httpx,
        "request",
        lambda *a, **k: _Response({}, status_code=404, raw=b"missing"),
    )

    with pytest.raises(ApiSourceError, match="HTTP 404"):
        fetch_frame(_config())


def test_csv_responses_are_read(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_source.httpx,
        "request",
        lambda *a, **k: _Response(
            None, content_type="text/csv", raw=b"id,name\n1,Alice\n2,Bob\n"
        ),
    )

    frame = fetch_frame(_config())

    assert frame["name"].tolist() == ["Alice", "Bob"]


def test_non_json_responses_are_rejected(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_source.httpx,
        "request",
        lambda *a, **k: _Response(None, content_type="text/html", raw=b"<html>"),
    )

    with pytest.raises(ApiSourceError, match="not JSON or CSV"):
        fetch_frame(_config())


def test_renames_match_by_source_name_not_position() -> None:
    frame = pd.DataFrame({"id": [1], "name": ["Alice"], "extra": [True]})

    renamed, pairs = apply_column_names(
        frame, [{"source": "name", "name": "customer_name"}]
    )

    assert list(renamed.columns) == ["id", "customer_name", "extra"]
    assert {"source": "name", "name": "customer_name"} in pairs


def test_renames_survive_a_field_the_api_dropped() -> None:
    frame = pd.DataFrame({"id": [1]})

    renamed, pairs = apply_column_names(
        frame,
        [
            {"source": "name", "name": "customer_name"},
            {"source": "id", "name": "customer_id"},
        ],
    )

    assert list(renamed.columns) == ["customer_id"]
    assert [pair["source"] for pair in pairs] == ["id"]


def test_duplicate_renames_are_made_distinct() -> None:
    frame = pd.DataFrame({"a": [1], "b": [2]})

    renamed, _ = apply_column_names(
        frame,
        [{"source": "a", "name": "x"}, {"source": "b", "name": "X"}],
    )

    assert list(renamed.columns) == ["x", "X_2"]


def test_preview_reports_rows_and_columns(monkeypatch: MonkeyPatch) -> None:
    payload = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    monkeypatch.setattr(api_source.httpx, "request", lambda *a, **k: _Response(payload))

    result = preview_api(_config())

    assert result["row_count"] == 2
    assert result["column_count"] == 2
    assert result["rows"][0] == ["1", "Alice"]
    assert [column["source"] for column in result["columns"]] == ["id", "name"]
    assert result["method"] == "GET"
