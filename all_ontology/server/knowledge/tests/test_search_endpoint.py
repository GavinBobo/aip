# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The knowledge search route's envelope and visibility contract."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

knowledge_router = importlib.import_module("all_ontology.server.knowledge.router")


def _result() -> dict:
    return {
        "query": "approval",
        "mode": "human",
        "total": 1,
        "returned": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "results": [
            {
                "kind": "chunk",
                "id": "chunk-1",
                "score": 1.2,
                "title": "purchase-policy.pdf",
                "snippet": "CFO approval is required.",
                "network_id": "net-1",
                "network_name": "Procurement",
                "document_id": "doc-1",
                "document_title": "purchase-policy.pdf",
                "page": 3,
                "citation": {"page": 3},
                "metadata": {},
                "evidence": [],
            }
        ],
        "facets": {"kinds": {"chunk": 1}, "networks": [], "documents": []},
        "context": "## Knowledge retrieval context\n",
    }


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        knowledge_router,
        "current_access",
        lambda: SimpleNamespace(user_id="u-1", dept_ids=()),
    )
    monkeypatch.setattr(knowledge_router, "current_zone_ids", lambda: [])
    monkeypatch.setattr(knowledge_router, "current_zone_permissions", lambda: {})
    monkeypatch.setattr(
        knowledge_router.dal, "visible_network_ids", lambda *args, **kwargs: ["net-1"]
    )
    monkeypatch.setattr(
        knowledge_router,
        "search_knowledge",
        lambda *args, **kwargs: _result(),
    )
    app = FastAPI()
    app.include_router(knowledge_router.router, prefix="/api")
    return TestClient(app)


def test_search_returns_the_data_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch).post(
        "/api/knowledge/search",
        json={"query": "approval", "mode": "human"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["query"] == "approval"
    assert payload["results"][0]["kind"] == "chunk"


def test_an_unknown_network_is_a_404_before_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(knowledge_router.dal, "get_network", lambda *args, **kwargs: None)
    response = client.post(
        "/api/knowledge/search",
        json={"query": "approval", "network_id": "missing"},
    )
    assert response.status_code == 404
