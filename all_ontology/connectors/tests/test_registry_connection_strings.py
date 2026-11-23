# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.connectors.registry import parse_connection_strings


def test_parse_connection_strings_accepts_commas_and_newlines() -> None:
    raw = """
        postgresql://localhost/first
        clickhouse://localhost/second,

        snowflake://account?database=third
    """

    assert parse_connection_strings(raw) == [
        "postgresql://localhost/first",
        "clickhouse://localhost/second",
        "snowflake://account?database=third",
    ]


def test_parse_connection_strings_keeps_a_sql_server_port_comma() -> None:
    raw = (
        "mssql://sa:pw@db.example.com,1433/sales,"
        "postgresql://localhost/second"
    )

    assert parse_connection_strings(raw) == [
        "mssql://sa:pw@db.example.com,1433/sales",
        "postgresql://localhost/second",
    ]
