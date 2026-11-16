# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""SQL DDL export/import."""

from __future__ import annotations
import re
import pytest
from all_ontology.server.erd.ddl import export_sql, parse_sql

NODES = [
    {
        "id": "n1",
        "name": "public.customers",
        "columns": [
            {
                "name": "id",
                "data_type": "bigint",
                "is_primary_key": True,
                "is_unique": False,
                "is_nullable": False,
            },
            {
                "name": "email",
                "data_type": "varchar(120)",
                "is_primary_key": False,
                "is_unique": True,
                "is_nullable": True,
            },
        ],
    },
    {
        "id": "n2",
        "name": "public.orders",
        "columns": [
            {
                "name": "id",
                "data_type": "bigint",
                "is_primary_key": True,
                "is_unique": False,
                "is_nullable": False,
            },
            {
                "name": "customer_id",
                "data_type": "bigint",
                "is_primary_key": False,
                "is_unique": False,
                "is_nullable": False,
            },
        ],
    },
]
RELATIONSHIPS = [
    {
        "source_node_id": "n2",
        "target_node_id": "n1",
        "source_columns": ["customer_id"],
        "target_columns": ["id"],
        "cardinality": "many-to-one",
        "label": None,
    }
]


def test_postgres_export_has_create_table_and_foreign_key() -> None:
    sql = export_sql(NODES, RELATIONSHIPS, "postgres")
    assert 'CREATE TABLE "public"."customers" (' in sql
    assert '"id" bigint NOT NULL' in sql
    assert 'PRIMARY KEY ("id")' in sql
    assert 'ALTER TABLE "public"."orders" ADD CONSTRAINT' in sql
    assert 'FOREIGN KEY ("customer_id") REFERENCES "public"."customers" ("id")' in sql


def test_mysql_uses_backticks() -> None:
    sql = export_sql(NODES, RELATIONSHIPS, "mysql")
    assert "CREATE TABLE `public`.`customers` (" in sql
    assert "`customer_id`" in sql


def test_sqlite_inlines_the_foreign_key() -> None:
    sql = export_sql(NODES, RELATIONSHIPS, "sqlite")
    assert "ALTER TABLE" not in sql
    assert 'FOREIGN KEY ("customer_id") REFERENCES "public"."customers" ("id")' in sql


def test_many_to_many_is_reported_not_invented() -> None:
    relationships = [
        {
            "source_node_id": "n1",
            "target_node_id": "n2",
            "source_columns": ["id"],
            "target_columns": ["id"],
            "cardinality": "many-to-many",
            "label": None,
        }
    ]
    sql = export_sql(NODES, relationships, "postgres")
    assert "many-to-many; a junction table is required" in sql
    assert "ALTER TABLE" not in sql


def test_export_then_import_round_trips_tables_and_keys() -> None:
    nodes, relationships, warnings = parse_sql(export_sql(NODES, RELATIONSHIPS))
    assert warnings == []
    assert [node["name"] for node in nodes] == ["public.customers", "public.orders"]
    customers = nodes[0]
    assert customers["columns"][0]["is_primary_key"] is True
    assert customers["columns"][1]["is_unique"] is True
    assert relationships[0]["source"] == "public.orders"
    assert relationships[0]["source_columns"] == ["customer_id"]
    assert relationships[0]["target"] == "public.customers"
    assert relationships[0]["target_columns"] == ["id"]


def test_alter_table_foreign_key_is_parsed() -> None:
    sql = """
ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id)
    REFERENCES public.customers (id);
"""
    _, relationships, _ = parse_sql(sql)
    assert relationships == [
        {
            "source": "public.orders",
            "source_columns": ["customer_id"],
            "target": "public.customers",
            "target_columns": ["id"],
            "cardinality": "many-to-one",
            "label": None,
        }
    ]


def test_inline_reference_is_parsed() -> None:
    sql = """
CREATE TABLE orders (
  id bigint PRIMARY KEY,
  customer_id bigint NOT NULL REFERENCES customers (id),
  total numeric(10,2) DEFAULT 0
);
"""
    nodes, relationships, _ = parse_sql(sql)
    assert nodes[0]["columns"][2]["data_type"] == "numeric(10,2)"
    assert relationships[0]["source_columns"] == ["customer_id"]


def test_quoted_names_and_comments() -> None:
    sql = """
-- a comment
CREATE TABLE "public"."order lines" (
  "id" bigint PRIMARY KEY,
  "amount" numeric(10,2) NOT NULL
);
"""
    nodes, _, warnings = parse_sql(sql)
    assert warnings == []
    assert nodes[0]["name"] == "public.order lines"
    assert nodes[0]["columns"][1]["data_type"] == "numeric(10,2)"


def test_unknown_dialect_is_rejected() -> None:
    with pytest.raises(ValueError):
        export_sql(NODES, RELATIONSHIPS, "oracle")


def test_table_notes_become_comments() -> None:
    nodes = [
        {
            "id": "n1",
            "name": "public.customers",
            "note": "one row per customer's account",
            "columns": [
                {
                    "name": "id",
                    "data_type": "bigint",
                    "is_primary_key": True,
                    "is_unique": False,
                    "is_nullable": False,
                }
            ],
        }
    ]
    postgres = export_sql(nodes, [], "postgres")
    assert (
        "COMMENT ON TABLE \"public\".\"customers\" IS 'one row per customer''s account';"
        in postgres
    )
    mysql = export_sql(nodes, [], "mysql")
    assert "COMMENT = 'one row per customer''s account';" in mysql
    sqlite = export_sql(nodes, [], "sqlite")
    assert "-- note: one row per customer's account" in sqlite


def test_indexes_become_create_index_and_come_back() -> None:
    nodes = [
        {
            "id": "n1",
            "name": "public.customers",
            "columns": [
                {
                    "name": "email",
                    "data_type": "varchar(120)",
                    "is_primary_key": False,
                    "is_unique": False,
                    "is_nullable": False,
                }
            ],
            "indexes": [
                {"name": "ix_customers_email", "columns": ["email"], "unique": True}
            ],
        }
    ]
    sql = export_sql(nodes, [], "postgres")
    assert (
        'CREATE UNIQUE INDEX "ix_customers_email" ON "public"."customers" ("email");'
        in sql
    )

    parsed, _, warnings = parse_sql(sql)
    assert warnings == []
    assert parsed[0]["indexes"] == [
        {"name": "ix_customers_email", "columns": ["email"], "unique": True}
    ]


def test_non_ascii_columns_do_not_collapse_constraint_names() -> None:
    """Sanitising Chinese column names used to give both keys the same name."""
    nodes = [
        {
            "id": "a",
            "name": "main.dash_board",
            "columns": [
                {"name": "日期", "data_type": "date", "is_primary_key": True},
                {"name": "商品浏览量", "data_type": "bigint", "is_primary_key": False},
            ],
        },
        {
            "id": "b",
            "name": "main.format",
            "columns": [
                {"name": "订单编号", "data_type": "text", "is_primary_key": True},
                {"name": "数量", "data_type": "bigint", "is_primary_key": False},
            ],
        },
    ]
    relationships = [
        {
            "source_node_id": "a",
            "target_node_id": "b",
            "source_columns": ["日期"],
            "target_columns": ["订单编号"],
            "cardinality": "many-to-one",
        },
        {
            "source_node_id": "a",
            "target_node_id": "b",
            "source_columns": ["商品浏览量"],
            "target_columns": ["数量"],
            "cardinality": "many-to-one",
        },
    ]
    sql = export_sql(nodes, relationships, "postgres")
    names = re.findall(r'ADD CONSTRAINT "([^"]+)"', sql)
    assert len(names) == 2
    assert len(set(names)) == 2
