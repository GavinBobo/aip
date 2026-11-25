# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from fastapi.testclient import TestClient
import pytest

from all_ontology.server import __main__ as server_main
from all_ontology.server.access import (
    RequestAccess,
    current_zone_ids,
    load_request_access,
    reset_request_access,
    set_request_access,
    zone_permission,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def fake_access(user_id: str) -> RequestAccess | None:
        if user_id == "missing":
            return None
        if user_id == "admin":
            return RequestAccess(
                user_id=user_id,
                role="admin",
                dept_ids=(),
                zone_ids=None,
                zone_permissions=None,
                is_admin=True,
            )
        return RequestAccess(
            user_id=user_id,
            role="viewer",
            dept_ids=("dept-1",),
            zone_ids=(),
            zone_permissions=(),
            is_admin=False,
        )

    monkeypatch.setattr(server_main, "load_request_access", fake_access)
    return TestClient(server_main.create_app())


def test_an_api_request_without_identity_is_rejected(client: TestClient) -> None:
    assert client.get("/api/access/me").status_code == 401


def test_an_unknown_account_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/access/me", headers={"x-all-ontology-user-id": "missing"}
    )
    assert response.status_code == 401


def test_a_viewer_is_resolved_to_their_effective_scope(client: TestClient) -> None:
    response = client.get(
        "/api/access/me", headers={"x-all-ontology-user-id": "viewer-1"}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "user_id": "viewer-1",
        "role": "viewer",
        "is_admin": False,
        "dept_ids": ["dept-1"],
        "zone_ids": [],
        "zone_permissions": {},
    }


def test_an_admin_has_the_explicit_unscoped_state(client: TestClient) -> None:
    response = client.get("/api/access/me", headers={"x-all-ontology-user-id": "admin"})

    assert response.status_code == 200
    assert response.json()["data"]["zone_ids"] is None
    assert response.json()["data"]["zone_permissions"] is None


def test_a_banned_admin_does_not_resolve_to_an_unscoped_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "all_ontology.server.access.access_dal.account_access",
        lambda _user_id: {
            "role": "admin",
            "banned": True,
            "dept_ids": [],
            "zone_ids": [],
        },
    )

    assert load_request_access("banned-admin") is None


def test_zone_permissions_are_ranked_for_operation_checks() -> None:
    token = set_request_access(
        RequestAccess(
            user_id="viewer-1",
            role="viewer",
            dept_ids=("dept-1",),
            zone_ids=("z-read", "z-edit"),
            zone_permissions=(("z-read", "read"), ("z-edit", "edit")),
            is_admin=False,
        )
    )
    try:
        assert current_zone_ids() == ["z-read", "z-edit"]
        assert current_zone_ids("edit") == ["z-edit"]
        assert zone_permission("z-read") == "read"
        assert zone_permission("z-edit") == "edit"
        assert zone_permission("z-missing") is None
    finally:
        reset_request_access(token)
