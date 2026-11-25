# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""User and department grants over zones.

Needs a migrated database. The Better Auth account table may be absent in CI's
Alembic database, so the fixture creates only the columns this module reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
from sqlalchemy import text

pytest.importorskip("sqlalchemy")

from all_ontology.dal import access as dal  # noqa: E402
from all_ontology.dal import zones as zones_dal  # noqa: E402
from all_ontology.dal.session import store  # noqa: E402
from all_ontology.infra.postgres import FRONTEND_SCHEMA  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema() -> Iterator[None]:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    store().query_read(text("SELECT 1 FROM department LIMIT 1"))
    store().query_read(text("SELECT 1 FROM zone_grant LIMIT 1"))

    schema_existed = bool(
        store().query_read(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"),
            {"schema": FRONTEND_SCHEMA},
        )
    )
    table_existed = bool(
        store().query_read(
            text(
                """
                SELECT 1
                  FROM pg_class AS class
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = class.relnamespace
                 WHERE namespace.nspname = :schema
                   AND class.relname = 'user'
                """
            ),
            {"schema": FRONTEND_SCHEMA},
        )
    )
    store().query_write(text(f"CREATE SCHEMA IF NOT EXISTS {FRONTEND_SCHEMA}"))
    store().query_write(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {FRONTEND_SCHEMA}."user" (
                id text PRIMARY KEY,
                name text NOT NULL,
                email text NOT NULL,
                role text,
                banned boolean NOT NULL DEFAULT false
            )
            """
        )
    )
    try:
        yield
    finally:
        if not table_existed:
            store().query_write(text(f'DROP TABLE IF EXISTS {FRONTEND_SCHEMA}."user"'))
        if not schema_existed:
            store().query_write(text(f"DROP SCHEMA IF EXISTS {FRONTEND_SCHEMA}"))


@pytest.fixture
def world() -> Iterator[dict[str, str]]:
    prefix = f"acl-{uuid.uuid4().hex[:8]}"
    user_ids = [f"{prefix}-u1", f"{prefix}-u2"]
    for index, user_id in enumerate(user_ids, start=1):
        store().query_write(
            text(
                f"""
                INSERT INTO {FRONTEND_SCHEMA}."user"
                    (
                        id, name, email, "emailVerified", "createdAt",
                        "updatedAt", role, banned
                    )
                VALUES (:id, :name, :email, true, now(), now(), 'viewer', false)
                """
            ),
            {
                "id": user_id,
                "name": f"User {index}",
                "email": f"{user_id}@example.com",
            },
        )
    dept = dal.create_department(
        name=f"{prefix} Finance",
        description="books",
        user_ids=[user_ids[0]],
    )
    first_zone = zones_dal.create_zone(
        name=f"{prefix} first",
        description=None,
        color="#0ea5e9",
        item_ids=[],
    )
    second_zone = zones_dal.create_zone(
        name=f"{prefix} second",
        description=None,
        color="#8b5cf6",
        item_ids=[],
    )
    try:
        yield {
            "prefix": prefix,
            "user1": user_ids[0],
            "user2": user_ids[1],
            "dept": dept["id"],
            "zone1": first_zone["id"],
            "zone2": second_zone["id"],
        }
    finally:
        store().query_write(
            text("DELETE FROM zone WHERE name LIKE :prefix"),
            {"prefix": f"{prefix}%"},
        )
        store().query_write(
            text("DELETE FROM department WHERE name LIKE :prefix"),
            {"prefix": f"{prefix}%"},
        )
        store().query_write(
            text(f'DELETE FROM {FRONTEND_SCHEMA}."user" WHERE id = ANY(:ids)'),
            {"ids": user_ids},
        )


def test_department_membership_and_direct_grant_are_unioned(world) -> None:
    dal.replace_zone_grants(world["zone1"], user_ids=[], dept_ids=[world["dept"]])
    dal.replace_zone_grants(world["zone2"], user_ids=[world["user1"]], dept_ids=[])

    resolved = dal.account_access(world["user1"])
    assert resolved is not None
    assert resolved["dept_ids"] == [world["dept"]]
    assert set(resolved["zone_ids"]) == {world["zone1"], world["zone2"]}

    other = dal.account_access(world["user2"])
    assert other is not None
    assert other["zone_ids"] == []


def test_the_strongest_direct_or_department_permission_wins(world) -> None:
    dal.replace_zone_grants(
        world["zone1"],
        grants=[
            {
                "subject_type": "user",
                "subject_id": world["user1"],
                "permission": "read",
            },
            {
                "subject_type": "department",
                "subject_id": world["dept"],
                "permission": "edit",
            },
        ],
    )

    resolved = dal.account_access(world["user1"])
    assert resolved is not None
    assert resolved["zone_permissions"][world["zone1"]] == "edit"
    visible = zones_dal.list_zones([world["zone1"]])
    assert visible[0]["access"]["grants"] == [
        {
            "subject_type": "department",
            "subject_id": world["dept"],
            "permission": "edit",
                "expires_at": None,
        },
        {
            "subject_type": "user",
            "subject_id": world["user1"],
            "permission": "read",
                "expires_at": None,
        },
    ]
    audit = dal.list_zone_grant_audit(world["zone1"])
    assert audit
    assert {
        (grant["subject_type"], grant["permission"]) for grant in audit[0]["after"]
    } == {("user", "read"), ("department", "edit")}


def test_an_unknown_permission_is_rejected(world) -> None:
    with pytest.raises(ValueError, match="Unknown permission"):
        dal.replace_zone_grants(
            world["zone1"],
            grants=[
                {
                    "subject_type": "user",
                    "subject_id": world["user1"],
                    "permission": "owner",
                }
            ],
        )


def test_expired_zone_grants_do_not_grant_access(world) -> None:
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    dal.replace_zone_grants(
        world["zone1"],
        grants=[
            {
                "subject_type": "user",
                "subject_id": world["user1"],
                "permission": "edit",
                "expires_at": past,
            }
        ],
    )
    assert dal.account_access(world["user1"])["zone_ids"] == []  # type: ignore[index]

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    dal.replace_zone_grants(
        world["zone1"],
        grants=[
            {
                "subject_type": "user",
                "subject_id": world["user1"],
                "permission": "edit",
                "expires_at": future,
            }
        ],
    )
    resolved = dal.account_access(world["user1"])
    assert resolved is not None
    assert resolved["zone_permissions"][world["zone1"]] == "edit"


def test_a_disabled_zone_grants_nothing(world) -> None:
    dal.replace_zone_grants(world["zone1"], user_ids=[world["user1"]], dept_ids=[])
    zones_dal.set_zone_enabled(world["zone1"], False)

    resolved = dal.account_access(world["user1"])
    assert resolved is not None
    assert world["zone1"] not in resolved["zone_ids"]


def test_zone_list_is_limited_to_the_effective_scope(world) -> None:
    dal.replace_zone_grants(world["zone1"], user_ids=[world["user1"]], dept_ids=[])
    visible = zones_dal.list_zones([world["zone1"]])

    assert [zone["id"] for zone in visible] == [world["zone1"]]
    assert visible[0]["access"]["user_ids"] == [world["user1"]]
    assert zones_dal.get_zone_by_id(world["zone2"], [world["zone1"]]) is None


def test_an_unknown_grant_subject_is_refused(world) -> None:
    with pytest.raises(dal.UnknownZoneGrantSubjects):
        dal.replace_zone_grants(world["zone1"], user_ids=["missing-user"], dept_ids=[])


def test_replacing_membership_changes_the_effective_department(world) -> None:
    dal.replace_zone_grants(world["zone1"], user_ids=[], dept_ids=[world["dept"]])
    dal.update_department(world["dept"], {}, user_ids=[world["user2"]])

    assert dal.account_access(world["user1"])["zone_ids"] == []  # type: ignore[index]
    resolved = dal.account_access(world["user2"])
    assert resolved is not None
    assert resolved["zone_ids"] == [world["zone1"]]
