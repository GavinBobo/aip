# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The candidate route's envelope and explicit apply contract."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ontology_router = importlib.import_module("all_ontology.server.erd.ontology")


def _report() -> dict:
    return {
        "zone_id": "zone-1",
        "canvas_id": "canvas-1",
        "zone_name": "Sales",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "summary": {
            "node_count": 1,
            "mapped_node_count": 1,
            "virtual_node_count": 0,
            "term_count": 0,
            "description_count": 1,
            "relationship_count": 0,
            "validated_relationship_count": 0,
            "existing_semantic_fk_count": 0,
            "issue_count": 1,
            "gap_count": 1,
            "readiness": 0.55,
            "readiness_label": "review",
        },
        "entities": [],
        "relationships": [],
        "catalog_fks_not_drawn": [],
        "gaps": [],
    }


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(ontology_router, "require_zone", lambda zone_id: None)
    monkeypatch.setattr(
        ontology_router, "require_zone_permission", lambda zone_id, minimum: None
    )
    monkeypatch.setattr(ontology_router, "build_report", lambda zone_id: _report())
    monkeypatch.setattr(
        ontology_router,
        "apply_candidates",
        lambda zone_id, body: {
            "terms_created": [
                {"table_id": "table-1", "term_id": "term-1", "name": "Orders"}
            ],
            "terms_updated": [],
            "terms_reused": [],
            "semantic_fks_created": [],
            "skipped": [],
            "errors": [],
        },
    )
    app = FastAPI()
    app.include_router(ontology_router.router, prefix="/api")
    return TestClient(app)


def test_report_is_returned_in_the_data_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _client(monkeypatch).get("/api/erd/canvases/zone-1/ontology-candidates")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["zone_id"] == "zone-1"
    assert payload["summary"]["readiness_label"] == "review"


def test_apply_sends_selected_ids_and_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _client(monkeypatch).post(
        "/api/erd/canvases/zone-1/ontology-candidates/apply",
        json={
            "entity_node_ids": ["node-1"],
            "relationship_ids": [],
            "create_terms": True,
            "create_semantic_fks": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["terms_created"][0]["name"] == "Orders"
