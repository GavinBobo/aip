# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""DB-backed smoke test for the ERD -> data-ontology candidate service.

Skipped without a migrated Postgres, like the rest of the ERD DAL tests.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select

pytest.importorskip("sqlalchemy")

from all_ontology.dal import erd as erd_dal  # noqa: E402
from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal.session import store  # noqa: E402
from all_ontology.dal.zones import create_zone, delete_zone  # noqa: E402
from all_ontology.server.erd import ontology  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema():
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read("SELECT 1 FROM erd_canvas LIMIT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"all_ontology schema unavailable (alembic upgrade head): {exc}")


@pytest.fixture
def world():
    prefix = f"oc-{uuid.uuid4().hex[:8]}"

    def insert(table, **values):
        return store().query_write(
            table.insert().values(**values).returning(table.c.id)
        )[0]["id"]

    db_id = insert(s.catalog_database, name=f"{prefix}-db")
    schema_id = insert(s.catalog_schema, database_id=db_id, name="public")
    customers_id = insert(
        s.catalog_table,
        schema_id=schema_id,
        name=f"{prefix}_customers",
        pk=["id"],
        description="Customer master data",
    )
    orders_id = insert(
        s.catalog_table,
        schema_id=schema_id,
        name=f"{prefix}_orders",
        pk=["id"],
        description="One row per order",
    )
    customer_pk = insert(
        s.catalog_column,
        table_id=customers_id,
        name="id",
        data_type="bigint",
        ordinal_position=1,
        is_nullable=False,
        is_unique=True,
        distinct_ratio=1.0,
        sample_values='["1", "2"]',
    )
    insert(
        s.catalog_column,
        table_id=orders_id,
        name="id",
        data_type="bigint",
        ordinal_position=1,
        is_nullable=False,
        is_unique=True,
        distinct_ratio=1.0,
    )
    order_customer = insert(
        s.catalog_column,
        table_id=orders_id,
        name="customer_id",
        data_type="bigint",
        ordinal_position=2,
        is_nullable=True,
        sample_values='["1", "2"]',
    )
    store().query_write(
        s.column__foreign_key.insert().values(
            source_column_id=order_customer,
            target_column_id=customer_pk,
        )
    )
    zone_id = create_zone(
        name=f"{prefix}-zone",
        description=None,
        color="#76b900",
        item_ids=[orders_id, customers_id],
    )["id"]

    yield {
        "prefix": prefix,
        "db_id": db_id,
        "orders_id": orders_id,
        "customers_id": customers_id,
        "order_customer_id": order_customer,
        "zone_id": zone_id,
    }

    # Terms and ColumnAttributes are not owned by the catalog row in every
    # direction (a Term can be shared), so clean the test's rows explicitly.
    term_ids = store().query_read(
        select(s.table__term.c.term_id).where(
            s.table__term.c.table_id.in_([orders_id, customers_id])
        )
    )
    store().query_write(
        delete(s.column_attribute).where(
            s.column_attribute.c.table_id.in_([orders_id, customers_id])
        )
    )
    if term_ids:
        store().query_write(
            delete(s.term).where(
                s.term.c.id.in_([row["term_id"] for row in term_ids])
            )
        )
    store().query_write(
        s.catalog_database.delete().where(s.catalog_database.c.id == db_id)
    )
    delete_zone(zone_id)


def test_report_and_apply_create_a_term_and_semantic_fk(world) -> None:
    canvas = erd_dal.get_or_create_canvas(world["zone_id"])
    orders_node = next(
        node for node in canvas["nodes"] if node["table_id"] == world["orders_id"]
    )
    customers_node = next(
        node for node in canvas["nodes"] if node["table_id"] == world["customers_id"]
    )
    relationship = erd_dal.create_relationship(
        canvas_id=canvas["id"],
        source_node_id=orders_node["id"],
        target_node_id=customers_node["id"],
        source_columns=["customer_id"],
        target_columns=["id"],
        cardinality="many-to-one",
        label="placed by",
    )

    report = ontology.build_report(world["zone_id"])
    assert report is not None
    candidate = next(
        item for item in report["relationships"] if item["id"] == relationship["id"]
    )
    assert candidate["status"] == "validated"
    assert candidate["checks"]["catalog_fk"] is True

    result = ontology.apply_candidates(
        world["zone_id"],
        ontology.OntologyApplyRequest(
            entity_node_ids=[orders_node["id"]],
            relationship_ids=[relationship["id"]],
            create_terms=True,
            create_semantic_fks=True,
        ),
    )
    assert result["terms_created"]
    assert result["semantic_fks_created"]

    term_rows = store().query_read(
        select(s.table__term.c.term_id).where(
            s.table__term.c.table_id == world["orders_id"]
        )
    )
    assert term_rows
    fk_rows = store().query_read(
        select(s.column__semantic_fk.c.attribute_id).where(
            s.column__semantic_fk.c.column_id == world["order_customer_id"]
        )
    )
    assert fk_rows
