# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A Zone editor can edit catalog metadata; a read grant cannot."""

from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

pytest.importorskip("sqlalchemy")

from all_ontology.dal import access as access_dal  # noqa: E402
from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal import zones as zones_dal  # noqa: E402
from all_ontology.dal.session import store  # noqa: E402
from all_ontology.infra.postgres import FRONTEND_SCHEMA  # noqa: E402
from all_ontology.server.__main__ import create_app  # noqa: E402


@pytest.fixture
def editable_catalog() -> dict[str, str]:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    prefix = f"edit-{uuid.uuid4().hex[:8]}"
    user_id = f"{prefix}-u"
    store().query_write(
        text(
            f"""
            INSERT INTO {FRONTEND_SCHEMA}."user"
                (
                    id, name, email, "emailVerified", "createdAt",
                    "updatedAt", role, banned
                )
            VALUES (:id, :id, :email, true, now(), now(), 'viewer', false)
            """
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    department = access_dal.create_department(
        name=f"{prefix}-dept", description=None, user_ids=[user_id]
    )
    database_id = str(
        store().query_write(
            s.catalog_database.insert()
            .values(name=prefix)
            .returning(s.catalog_database.c.id)
        )[0]["id"]
    )
    schema_id = str(
        store().query_write(
            s.catalog_schema.insert()
            .values(database_id=database_id, name="public")
            .returning(s.catalog_schema.c.id)
        )[0]["id"]
    )
    table_id = str(
        store().query_write(
            s.catalog_table.insert()
            .values(schema_id=schema_id, name="orders", description="old")
            .returning(s.catalog_table.c.id)
        )[0]["id"]
    )
    zone = zones_dal.create_zone(
        name=f"{prefix}-zone",
        description=None,
        color="#0ea5e9",
        item_ids=[table_id],
    )
    access_dal.replace_zone_grants(
        zone["id"],
        grants=[
            {
                "subject_type": "department",
                "subject_id": department["id"],
                "permission": "edit",
            }
        ],
    )
    try:
        yield {
            "user_id": user_id,
            "table_id": table_id,
            "zone_id": zone["id"],
            "dept_id": department["id"],
            "database_id": database_id,
        }
    finally:
        store().query_write(s.zone.delete().where(s.zone.c.id == zone["id"]))
        store().query_write(
            s.catalog_database.delete().where(s.catalog_database.c.id == database_id)
        )
        store().query_write(
            s.department.delete().where(s.department.c.id == department["id"])
        )
        store().query_write(
            text(f'DELETE FROM {FRONTEND_SCHEMA}."user" WHERE id = :id'),
            {"id": user_id},
        )


def test_zone_edit_grant_allows_catalog_metadata_edit(editable_catalog) -> None:
    client = TestClient(create_app())
    headers = {"x-all-ontology-user-id": editable_catalog["user_id"]}

    response = client.patch(
        f"/api/nodes/{editable_catalog['table_id']}",
        json={"description_certified": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["description_certified"] is True


def test_zone_read_grant_rejects_catalog_metadata_edit(editable_catalog) -> None:
    access_dal.replace_zone_grants(
        editable_catalog["zone_id"],
        grants=[
            {
                "subject_type": "department",
                "subject_id": editable_catalog["dept_id"],
                "permission": "read",
            }
        ],
    )
    client = TestClient(create_app())

    response = client.patch(
        f"/api/nodes/{editable_catalog['table_id']}",
        json={"description_certified": True},
        headers={"x-all-ontology-user-id": editable_catalog["user_id"]},
    )

    assert response.status_code == 403
