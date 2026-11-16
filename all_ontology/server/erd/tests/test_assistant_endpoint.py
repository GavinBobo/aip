# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The assistant route's contract, without a database or a model call.

Two things are worth pinning here that the validator tests cannot see: the
response arrives inside the usual ``{"data": ...}`` envelope, and a zone that
does not exist fails *before* an LLM request is spent on it. Both are easy to
break in a refactor and invisible until someone's canvas chat stops answering.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from all_ontology.server.erd import assistant
from all_ontology.server.models import ErdAssistantAction, ErdAssistantReply

# The package re-exports the ``router`` *instance*, which shadows the submodule
# for ``import ... as``; importlib returns the module itself.
erd_router = importlib.import_module("all_ontology.server.erd.router")


def _client(monkeypatch: pytest.MonkeyPatch, reply: ErdAssistantReply) -> TestClient:
    monkeypatch.setattr(erd_router, "canvas_or_404", lambda zone_id: {"id": "c-1"})
    monkeypatch.setattr(assistant, "ask", lambda body: reply)
    app = FastAPI()
    app.include_router(erd_router.router, prefix="/api")
    return TestClient(app)


def _body() -> dict[str, Any]:
    return {
        "zone_id": "z-1",
        "message": "给订单加一个时间戳",
        "canvas": {"nodes": [], "relationships": []},
        "history": [],
    }


def test_the_answer_arrives_in_the_data_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = ErdAssistantReply(
        reply="已经加好了",
        actions=[ErdAssistantAction(kind="add_column", node_id="n-1", name="ts")],
        warnings=[],
    )
    response = _client(monkeypatch, reply).post("/api/erd/assistant", json=_body())
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["reply"] == "已经加好了"
    assert payload["actions"][0]["kind"] == "add_column"


def test_an_unknown_zone_fails_before_the_model_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[Any] = []

    def missing(zone_id: str) -> dict:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")

    monkeypatch.setattr(erd_router, "canvas_or_404", missing)
    monkeypatch.setattr(assistant, "ask", lambda body: called.append(body) or None)
    app = FastAPI()
    app.include_router(erd_router.router, prefix="/api")
    response = TestClient(app).post("/api/erd/assistant", json=_body())

    assert response.status_code == 404
    assert called == []


def test_an_empty_message_is_rejected_by_schema_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, ErdAssistantReply(reply="unused"))
    response = client.post("/api/erd/assistant", json={**_body(), "message": ""})
    assert response.status_code == 422
