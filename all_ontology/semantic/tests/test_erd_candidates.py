# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure tests for the ERD -> data-ontology candidate analysis."""

from __future__ import annotations

from all_ontology.semantic.erd_candidates import build_candidate_report


def _canvas() -> dict:
    return {
        "id": "canvas-1",
        "zone_id": "zone-1",
        "zone_name": "Sales",
        "nodes": [
            {
                "id": "node-orders",
                "table_id": "table-orders",
                "name": "public.orders",
                "category": "fact",
                "note": None,
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_primary_key": True,
                    },
                    {
                        "name": "customer_id",
                        "data_type": "bigint",
                        "is_nullable": True,
                    },
                ],
            },
            {
                "id": "node-customers",
                "table_id": "table-customers",
                "name": "public.customers",
                "category": "dimension",
                "note": "Customer master data",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_primary_key": True,
                    },
                ],
            },
            {
                "id": "node-draft",
                "table_id": None,
                "name": "draft.audit_log",
                "category": None,
                "note": None,
                "columns": [{"name": "id", "data_type": "uuid"}],
            },
        ],
        "relationships": [
            {
                "id": "rel-orders-customers",
                "source_node_id": "node-orders",
                "target_node_id": "node-customers",
                "source_columns": ["customer_id"],
                "target_columns": ["id"],
                "cardinality": "many-to-one",
                "label": "placed by",
            }
        ],
    }


def _tables() -> dict:
    return {
        "table-orders": {
            "id": "table-orders",
            "database_name": "sales",
            "schema_name": "public",
            "table_name": "orders",
            "description": "One row per order",
            "pk": ["id"],
            "is_junction_table": False,
            "term": None,
            "columns": [
                {
                    "id": "col-orders-id",
                    "name": "id",
                    "data_type": "bigint",
                    "is_primary_key": True,
                    "is_unique": True,
                    "distinct_ratio": 1.0,
                    "is_nullable": False,
                },
                {
                    "id": "col-orders-customer",
                    "name": "customer_id",
                    "data_type": "bigint",
                    "is_unique": False,
                    "is_nullable": True,
                    "sample_values": ["1", "2"],
                },
            ],
        },
        "table-customers": {
            "id": "table-customers",
            "database_name": "sales",
            "schema_name": "public",
            "table_name": "customers",
            "description": "Customer master data",
            "pk": ["id"],
            "is_junction_table": False,
            "term": {
                "id": "term-customers",
                "name": "Customers",
                "description": "Customer master data",
            },
            "columns": [
                {
                    "id": "col-customers-id",
                    "name": "id",
                    "data_type": "bigint",
                    "is_primary_key": True,
                    "is_unique": True,
                    "distinct_ratio": 1.0,
                    "is_nullable": False,
                    "sample_values": ["1", "2", "3"],
                }
            ],
        },
    }


def test_entities_capture_mapping_role_and_virtual_status() -> None:
    report = build_candidate_report(_canvas(), _tables())
    entities = {entity["id"]: entity for entity in report["entities"]}

    orders = entities["node-orders"]
    assert orders["table_id"] == "table-orders"
    assert orders["semantic_role"] == "fact"
    assert orders["primary_keys"] == ["id"]
    assert orders["status"] == "ready"
    assert orders["proposed_term"]["name"] == "Orders"

    draft = entities["node-draft"]
    assert draft["table_id"] is None
    assert draft["status"] == "virtual"
    assert draft["simulated"] is True
    assert any(warning["code"] == "virtual_table" for warning in draft["warnings"])


def test_relationship_is_validated_by_fk_type_and_value_overlap() -> None:
    report = build_candidate_report(
        _canvas(),
        _tables(),
        catalog_fks=[
            {
                "source_column_id": "col-orders-customer",
                "source_table_id": "table-orders",
                "source_column": "customer_id",
                "target_column_id": "col-customers-id",
                "target_table_id": "table-customers",
                "target_column": "id",
            }
        ],
    )
    relationship = report["relationships"][0]

    assert relationship["status"] == "validated"
    assert relationship["referencing_table"] == "sales.public.orders"
    assert relationship["referenced_table"] == "sales.public.customers"
    assert relationship["checks"]["catalog_fk"] is True
    assert relationship["checks"]["type_compatible"] is True
    assert relationship["checks"]["target_unique"] is True
    assert relationship["checks"]["value_overlap"] == 1.0
    assert relationship["apply"]["can_apply"] is True


def test_one_to_many_reverses_the_fk_owner() -> None:
    canvas = _canvas()
    canvas["relationships"][0]["cardinality"] = "one-to-many"
    report = build_candidate_report(canvas, _tables())
    relationship = report["relationships"][0]

    assert relationship["referencing_table"] == "sales.public.customers"
    assert relationship["referenced_table"] == "sales.public.orders"
    assert relationship["referencing_columns"] == ["id"]
    assert relationship["referenced_columns"] == ["customer_id"]


def test_many_to_many_is_logical_only_and_needs_a_junction() -> None:
    canvas = _canvas()
    canvas["relationships"][0]["cardinality"] = "many-to-many"
    report = build_candidate_report(canvas, _tables())
    relationship = report["relationships"][0]

    assert relationship["status"] == "logical_only"
    assert relationship["apply"]["can_apply"] is False
    assert any(
        warning["code"] == "relationship_many_to_many"
        for warning in relationship["warnings"]
    )


def test_catalog_fk_not_drawn_is_reported() -> None:
    report = build_candidate_report(
        _canvas(),
        _tables(),
        catalog_fks=[
            {
                "source_column_id": "col-orders-customer",
                "source_table_id": "table-orders",
                "source_column": "customer_id",
                "target_column_id": "col-customers-id",
                "target_table_id": "table-customers",
                "target_column": "id",
            }
        ],
    )
    # The ERD relationship covers the catalog FK, so it is not a gap.
    assert report["catalog_fks_not_drawn"] == []

    canvas = _canvas()
    canvas["relationships"] = []
    report = build_candidate_report(
        canvas,
        _tables(),
        catalog_fks=[
            {
                "source_column_id": "col-orders-customer",
                "source_table_id": "table-orders",
                "source_column": "customer_id",
                "target_column_id": "col-customers-id",
                "target_table_id": "table-customers",
                "target_column": "id",
            }
        ],
    )
    assert len(report["catalog_fks_not_drawn"]) == 1
    assert any(gap["code"] == "catalog_fk_not_in_erd" for gap in report["gaps"])
