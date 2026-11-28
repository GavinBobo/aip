# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The rule CRUD route shape."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

knowledge_router = importlib.import_module("all_ontology.server.knowledge.router")


def _rule() -> dict:
    return {
        "id": "rule-1",
        "network_id": "net-1",
        "key": "rule_approval",
        "name": "Approval rule",
        "statement": "Orders above 10000 require approval.",
        "description": None,
        "scope": "orders",
        "condition": "amount > 10000",
        "roles": ["CFO"],
        "exceptions": [],
        "effective_from": None,
        "effective_to": None,
        "status": "draft",
        "confidence": 0.9,
        "source_document_id": None,
        "concepts": [],
        "metrics": [],
        "actions": [],
        "evidence": [],
    }


def test_rules_list_and_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge_router, "_require_network", lambda *args, **kwargs: {})
    monkeypatch.setattr(knowledge_router.dal, "list_rules", lambda network_id: [])
    monkeypatch.setattr(
        knowledge_router.dal,
        "create_rule",
        lambda **kwargs: _rule(),
    )
    app = FastAPI()
    app.include_router(knowledge_router.router, prefix="/api")
    client = TestClient(app)

    listed = client.get("/api/knowledge/networks/net-1/rules")
    assert listed.status_code == 200
    assert listed.json()["count"] == 0

    created = client.post(
        "/api/knowledge/networks/net-1/rules",
        json={
            "name": "Approval rule",
            "statement": "Orders above 10000 require approval.",
            "roles": ["CFO"],
        },
    )
    assert created.status_code == 201
    assert created.json()["data"]["statement"].startswith("Orders")
