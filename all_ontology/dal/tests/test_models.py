# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ORM layer: entities write and read the same rows Core does.

These go through a real database on purpose. The point of ``dal/models.py`` is
that ``select(Zone)`` and ``select(s.zone.c.id)`` are the same query, and that
an ORM write inside ``write_transaction()`` is visible to the Core statements
around it -- neither claim can be checked without Postgres.

Needs a migrated database and skips without one.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import select  # noqa: E402

from all_ontology.dal import models as m  # noqa: E402
from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal.models import (  # noqa: E402
    CatalogColumn,
    CatalogDatabase,
    CatalogSchema,
    CatalogTable,
    ErdCanvas,
    ErdNode,
    ErdRelationship,
    Zone,
    ZoneTarget,
)
from all_ontology.dal.session import orm_session, store, write_transaction  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema():
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read("SELECT 1 FROM erd_canvas LIMIT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"all_ontology schema unavailable (alembic upgrade head): {exc}")


@pytest.fixture
def database():
    """One throwaway database row; cascades take the whole catalog tree with it."""
    name = f"orm-{uuid.uuid4().hex[:8]}"
    with orm_session() as db:
        entity = CatalogDatabase(name=name)
        db.add(entity)
        db.flush()
        database_id = entity.id
    yield database_id
    with orm_session() as db:
        row = db.get(CatalogDatabase, database_id)
        if row is not None:
            db.delete(row)


def test_every_table_has_an_entity() -> None:
    """No table may be left without a hand-written, documented model."""
    mapped = {mapper.local_table.name for mapper in m.Base.registry.mappers}
    unmapped = set(s.METADATA.tables) - mapped
    assert not unmapped, f"tables without an ORM entity: {sorted(unmapped)}"


def test_an_entity_and_a_core_query_read_the_same_row(database) -> None:
    with orm_session() as db:
        entity = db.get(CatalogDatabase, database)
        assert entity is not None
        assert entity.name.startswith("orm-")
        entity_name = entity.name

    # The Core path sees exactly what the ORM just wrote.
    rows = store().query_read(
        select(s.catalog_database.c.name).where(s.catalog_database.c.id == database)
    )
    assert rows[0]["name"] == entity_name


def test_relationships_walk_the_catalog_tree(database) -> None:
    with orm_session() as db:
        root = db.get(CatalogDatabase, database)
        assert root is not None
        child = CatalogSchema(database_id=root.id, name="public")
        db.add(child)
        db.flush()
        table = CatalogTable(schema_id=child.id, name="orders")
        db.add(table)
        db.flush()
        db.add(CatalogColumn(table_id=table.id, name="id", data_type="bigint"))
        db.flush()

        # Re-read through the relationship, not through the ids we just kept.
        reloaded = db.get(CatalogDatabase, database)
        assert reloaded is not None
        assert [schema.name for schema in reloaded.schemas] == ["public"]
        assert [item.name for item in reloaded.schemas[0].tables] == ["orders"]
        assert [col.name for col in reloaded.schemas[0].tables[0].columns] == ["id"]


def test_deleting_a_database_cascades_through_the_orm(database) -> None:
    with orm_session() as db:
        root = db.get(CatalogDatabase, database)
        assert root is not None
        child = CatalogSchema(database_id=root.id, name="public")
        db.add(child)
        db.flush()
        schema_id = child.id
        db.delete(root)

    left = store().query_read(
        select(s.catalog_schema.c.id).where(s.catalog_schema.c.id == schema_id)
    )
    assert left == []


def test_an_orm_write_joins_an_open_transaction(database) -> None:
    """Inside ``write_transaction`` the session borrows the block's connection."""
    with pytest.raises(RuntimeError):
        with write_transaction():
            store().query_write(
                s.zone.insert().values(name="orm-rollback", color="#000000")
            )
            # Visible to a Core read in the same block...
            inside = store().query_read(
                select(s.zone.c.id).where(s.zone.c.name == "orm-rollback")
            )
            assert inside
            raise RuntimeError("roll back")

    # ...and gone once the block rolls back, which proves both statements ran
    # on one connection rather than two autocommits.
    after = store().query_read(
        select(s.zone.c.id).where(s.zone.c.name == "orm-rollback")
    )
    assert after == []


def test_zone_targets_come_back_through_the_relationship(database) -> None:
    zone_name = f"orm-zone-{uuid.uuid4().hex[:8]}"
    with orm_session() as db:
        zone = Zone(name=zone_name, color="#76b900")
        db.add(zone)
        db.flush()
        zone_id = zone.id
        db.add(ZoneTarget(zone_id=zone_id, database_id=database))
        db.flush()

    with orm_session() as db:
        reloaded = db.get(Zone, zone_id)
        assert reloaded is not None
        assert [target.database_id for target in reloaded.targets] == [database]

    with orm_session() as db:
        zone = db.get(Zone, zone_id)
        if zone is not None:
            db.delete(zone)


def test_a_canvas_graph_is_deleted_as_a_unit() -> None:
    """Canvas -> nodes -> relationships cascade without touching other canvases."""
    with orm_session() as db:
        zone = Zone(name=f"orm-canvas-{uuid.uuid4().hex[:8]}", color="#000000")
        db.add(zone)
        db.flush()
        zone_id = zone.id
        canvas = ErdCanvas(zone_id=zone_id)
        db.add(canvas)
        db.flush()
        canvas_id = canvas.id
        left = ErdNode(canvas_id=canvas_id, name="public.a", x=0, y=0)
        right = ErdNode(canvas_id=canvas_id, name="public.b", x=300, y=0)
        db.add_all([left, right])
        db.flush()
        db.add(
            ErdRelationship(
                canvas_id=canvas_id,
                source_node_id=left.id,
                target_node_id=right.id,
                cardinality="many-to-one",
            )
        )
        db.flush()

    with orm_session() as db:
        stored = db.get(ErdCanvas, canvas_id)
        assert stored is not None
        assert len(stored.nodes) == 2
        assert len(stored.relationships) == 1
        db.delete(stored)

    assert (
        store().query_read(
            select(s.erd_relationship.c.id).where(
                s.erd_relationship.c.canvas_id == canvas_id
            )
        )
        == []
    )
    with orm_session() as db:
        zone = db.get(Zone, zone_id)
        if zone is not None:
            db.delete(zone)
