# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Value-profile fields added with the 1.3 semantic-quality port."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from all_ontology.semantic.visit_enter import calculate_columns_profiling
from all_ontology.utils.sql_identifiers import qualified_name


def _connector() -> MagicMock:
    connector = MagicMock()
    connector.dialect = "postgres"
    connector.qualify.side_effect = lambda schema, table: qualified_name(
        schema, table, dialect="postgres"
    )
    return connector


@patch("all_ontology.semantic.visit_enter.store_column_date_formats")
@patch("all_ontology.semantic.visit_enter.store_column_uniqueness")
@patch("all_ontology.semantic.visit_enter.store_column_sample_values")
def test_mostly_distinct_column_is_unique_at_95_percent(
    _samples: MagicMock, _unique: MagicMock, _dates: MagicMock
) -> None:
    connector = _connector()
    connector.execute.return_value = pd.DataFrame(
        {"customer_id": list(range(19)) + [0]}
    )
    table = {"id": "t1", "name": "customers", "schema_name": "public"}
    columns = [{"name": "customer_id", "data_type": "integer"}]

    profiling = calculate_columns_profiling(table, columns, connector)

    assert profiling["customer_id"]["distinct_ratio"] == 0.95
    assert profiling["customer_id"]["is_unique"] is True


@patch("all_ontology.semantic.visit_enter.store_column_date_formats")
@patch("all_ontology.semantic.visit_enter.store_column_uniqueness")
@patch("all_ontology.semantic.visit_enter.store_column_sample_values")
def test_ninety_percent_distinct_column_is_not_unique(
    _samples: MagicMock, _unique: MagicMock, _dates: MagicMock
) -> None:
    connector = _connector()
    connector.execute.return_value = pd.DataFrame({"status": list(range(18)) + [0, 0]})
    table = {"id": "t1", "name": "orders", "schema_name": "public"}
    columns = [{"name": "status", "data_type": "text"}]

    profiling = calculate_columns_profiling(table, columns, connector)

    assert profiling["status"]["distinct_ratio"] == 0.9
    assert profiling["status"]["is_unique"] is False


@patch("all_ontology.semantic.visit_enter.store_column_date_formats")
@patch("all_ontology.semantic.visit_enter.store_column_uniqueness")
@patch("all_ontology.semantic.visit_enter.store_column_sample_values")
def test_pii_columns_are_left_out_of_the_sample_query(
    _samples: MagicMock, _unique: MagicMock, _dates: MagicMock
) -> None:
    connector = _connector()
    connector.execute.return_value = pd.DataFrame({"status": ["open", "closed"]})
    table = {"id": "t1", "name": "users", "schema_name": "public"}
    columns = [
        {"name": "email", "data_type": "text"},
        {"name": "status", "data_type": "text"},
    ]

    calculate_columns_profiling(table, columns, connector, pii_columns={"email"})

    sql = connector.execute.call_args_list[0][0][0]
    assert '"email"' not in sql
    assert '"status"' in sql
