# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "SQLDatabase",
    "ClickHouseDatabase",
    "DatabricksDatabase",
    "DuckDBDatabase",
    "FileUploadDatabase",
    "HeavyDBDatabase",
    "KyuubiDatabase",
    "MSSQLDatabase",
    "MySQLDatabase",
    "PostgresDatabase",
    "SnowflakeDatabase",
    "SQLiteDatabase",
    "TrinoDatabase",
    "get_connectors",
    "invalidate_connectors_cache",
]

#: Connector classes are heavyweight: importing this package used to load every
#: driver (Snowflake, Databricks, pandas, ...) even for a caller that only reads
#: one class or a helper. Resolve each name on first use instead.
_LAZY: dict[str, tuple[str, str]] = {
    "SQLDatabase": ("all_ontology.connectors.base", "SQLDatabase"),
    "ClickHouseDatabase": ("all_ontology.connectors.clickhouse", "ClickHouseDatabase"),
    "DatabricksDatabase": ("all_ontology.connectors.databricks", "DatabricksDatabase"),
    "DuckDBDatabase": ("all_ontology.connectors.duckdb", "DuckDBDatabase"),
    "FileUploadDatabase": ("all_ontology.connectors.fileupload", "FileUploadDatabase"),
    "HeavyDBDatabase": ("all_ontology.connectors.heavydb", "HeavyDBDatabase"),
    "KyuubiDatabase": ("all_ontology.connectors.kyuubi", "KyuubiDatabase"),
    "MSSQLDatabase": ("all_ontology.connectors.mssql", "MSSQLDatabase"),
    "MySQLDatabase": ("all_ontology.connectors.mysql", "MySQLDatabase"),
    "PostgresDatabase": ("all_ontology.connectors.postgres", "PostgresDatabase"),
    "SnowflakeDatabase": ("all_ontology.connectors.snowflake", "SnowflakeDatabase"),
    "SQLiteDatabase": ("all_ontology.connectors.sqlite", "SQLiteDatabase"),
    "TrinoDatabase": ("all_ontology.connectors.trino", "TrinoDatabase"),
    "get_connectors": ("all_ontology.connectors.registry", "get_connectors"),
    "invalidate_connectors_cache": (
        "all_ontology.connectors.registry",
        "invalidate_connectors_cache",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
