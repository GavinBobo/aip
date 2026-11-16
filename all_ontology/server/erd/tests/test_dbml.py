# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""DBML reader/writer."""

from __future__ import annotations
import pytest
from all_ontology.server.erd.dbml import DbmlParseError, export_dbml, parse_dbml

DOCUMENT = """
// a comment that must be ignored
Table public.customers {
  id bigint [pk]
  name varchar(120) [not null, note: 'display name']
  Note: 'people who buy'
}
Table public.orders {
  id bigint [pk]
  customer_id bigint [not null]
  total decimal(10,2) [note: 'gross, in USD']
}
Ref: public.orders.customer_id > public.customers.id
"""


def test_parses_tables_columns_and_a_reference() -> None:
    nodes, relationships, warnings = parse_dbml(DOCUMENT)
    assert warnings == []
    assert [node["name"] for node in nodes] == ["public.customers", "public.orders"]
    customers = nodes[0]
    assert customers["note"] == "people who buy"
    assert customers["columns"][0]["is_primary_key"] is True
    assert customers["columns"][1]["is_nullable"] is False
    assert customers["columns"][1]["note"] == "display name"
    assert nodes[1]["columns"][2]["data_type"] == "decimal(10,2)"
    assert nodes[1]["columns"][2]["note"] == "gross, in USD"
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


def test_all_four_operators_map_to_cardinalities() -> None:
    document = """
Table a { x int }
Table b { y int }
Ref: a.x > b.y
Ref named: a.x < b.y
Ref {
  a.x - b.y
  a.x <> b.y
}
"""
    _, relationships, _ = parse_dbml(document)
    assert [rel["cardinality"] for rel in relationships] == [
        "many-to-one",
        "one-to-many",
        "one-to-one",
        "many-to-many",
    ]


def test_round_trip_preserves_tables_columns_and_refs() -> None:
    nodes, relationships, _ = parse_dbml(DOCUMENT)
    exported = export_dbml(nodes, relationships)
    again_nodes, again_relationships, warnings = parse_dbml(exported)
    assert warnings == []
    assert [node["name"] for node in again_nodes] == [node["name"] for node in nodes]
    assert again_nodes[0]["note"] == "people who buy"
    assert again_nodes[0]["columns"][1]["data_type"] == "varchar(120)"
    assert again_relationships[0]["source_columns"] == ["customer_id"]
    assert again_relationships[0]["cardinality"] == "many-to-one"


def test_qualified_names_keep_their_schema_and_spaces() -> None:
    document = """Table main."order lines" {
  "id" int [pk]
}
Table main.customers {
  id int [pk]
}
Ref: main."order lines"."id" > main.customers.id
"""
    nodes, relationships, warnings = parse_dbml(document)
    assert warnings == []
    assert [node["name"] for node in nodes] == ["main.order lines", "main.customers"]
    assert relationships[0]["source"] == "main.order lines"
    assert relationships[0]["target"] == "main.customers"

    exported = export_dbml(nodes, relationships)
    again_nodes, again_relationships, _ = parse_dbml(exported)
    assert [node["name"] for node in again_nodes] == [
        "main.order lines",
        "main.customers",
    ]
    assert again_relationships[0]["target"] == "main.customers"


def test_unsupported_blocks_are_warnings_not_failures() -> None:
    document = """
Enum status {
  active
  paused
}
Table t {
  id int [pk]
  Indexes {
    (id) [unique]
  }
}
"""
    nodes, _, warnings = parse_dbml(document)
    assert [node["name"] for node in nodes] == ["t"]
    assert any("Enum" in warning for warning in warnings)
    # Indexes are supported now, so they are parsed rather than skipped.
    assert nodes[0]["indexes"] == [{"name": None, "columns": ["id"], "unique": True}]


def test_malformed_reference_reports_its_line() -> None:
    document = """Table a {
  x int
}
Ref: a.x >
"""
    with pytest.raises(DbmlParseError) as caught:
        parse_dbml(document)
    assert caught.value.line == 4


def test_unclosed_block_is_rejected() -> None:
    document = """Table a {
  x int
"""
    with pytest.raises(DbmlParseError):
        parse_dbml(document)


def test_indexes_are_parsed_and_exported() -> None:
    document = """Table public.orders {
  id bigint [pk]
  customer_id bigint
  Indexes {
    (customer_id, id) [unique, name: 'ix_orders_customer']
    id
  }
}
"""
    nodes, _, warnings = parse_dbml(document)
    assert warnings == []
    assert nodes[0]["indexes"] == [
        {
            "name": "ix_orders_customer",
            "columns": ["customer_id", "id"],
            "unique": True,
        },
        {"name": None, "columns": ["id"], "unique": False},
    ]

    exported = export_dbml(nodes, [])
    assert "Indexes {" in exported
    assert "(customer_id, id) [unique, name: 'ix_orders_customer']" in exported

    again, _, _ = parse_dbml(exported)
    assert again[0]["indexes"] == nodes[0]["indexes"]
