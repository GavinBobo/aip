# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The semantic-bridge coverage endpoint."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

knowledge_router = importlib.import_module("all_ontology.server.knowledge.router")


def test_bridge_reports_each_mapping_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge_router, "_require_network", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        knowledge_router.dal,
        "list_concepts",
        lambda network_id: [
            {"id": "c1", "name": "Order", "kind": "entity", "status": "draft", "data_links": []},
            {
                "id": "c2",
                "name": "Supplier",
                "kind": "entity",
                "status": "certified",
                "data_links": [{"id": "l1", "kind": "table", "name": "suppliers"}],
            },
        ],
    )
    monkeypatch.setattr(
        knowledge_router.dal,
        "list_metrics",
        lambda network_id: [
            {
                "id": "m1",
                "name": "Monthly spend",
                "expression": "SUM(amount)",
                "unit": "CNY",
                "status": "reviewed",
                "sql_attribute_id": "s1",
                "sql_attribute_name": "monthly_spend",
            }
        ],
    )
    monkeypatch.setattr(
        knowledge_router.dal,
        "list_rules",
        lambda network_id: [
            {
                "id": "r1",
                "name": "Approval threshold",
                "statement": "Orders above 10000 require approval.",
                "status": "reviewed",
                "metrics": [{"id": "m1"}],
                "actions": [{"id": "a1"}],
            }
        ],
    )
    monkeypatch.setattr(
        knowledge_router.dal,
        "list_actions",
        lambda network_id: [
            {
                "id": "a1",
                "name": "Submit approval",
                "status": "certified",
                "capabilities": [],
            }
        ],
    )
    monkeypatch.setattr(
        knowledge_router.dal,
        "list_capabilities",
        lambda network_id: [{"id": "cap1", "name": "Approval tool", "kind": "function"}],
    )

    app = FastAPI()
    app.include_router(knowledge_router.router, prefix="/api")
    response = TestClient(app).get("/api/knowledge/networks/net-1/bridge")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["concept_total"] == 2
    assert data["summary"]["concept_linked"] == 1
    assert data["summary"]["metric_linked"] == 1
    assert data["summary"]["rule_total"] == 1
    assert data["summary"]["rule_linked"] == 1
    assert data["summary"]["action_linked"] == 0
    assert data["summary"]["coverage"] == 0.6
    assert data["capabilities"][0]["name"] == "Approval tool"
