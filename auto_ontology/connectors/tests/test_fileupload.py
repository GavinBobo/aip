# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The connector over an uploaded dataset, against a stubbed catalog store."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import pytest
from pytest import MonkeyPatch

from auto_ontology.connectors.connection_string_factory import build_connection_string
from auto_ontology.connectors.fileupload import FileUploadDatabase, _dataset_name
from auto_ontology.connectors.registry import create_connector


FRAME = pd.DataFrame(
    {
        "customer_id": [1, 2, 3],
        "name": ["Alice", "Bob", None],
        "amount": [10.5, 20.0, 30.25],
    }
)


def _parquet(frame: pd.DataFrame = FRAME) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _dataset(name: str = "demo_sales", table: str = "demo_sales") -> dict[str, Any]:
    return {
        "name": name,
        "filename": "sales.csv",
        "table_name": table,
        "row_count": len(FRAME),
        "size_bytes": 0,
        "content": _parquet(),
    }


def test_dataset_name_is_read_from_the_url() -> None:
    assert _dataset_name("fileupload://demo%20sales") == "demo sales"
    assert _dataset_name("file://demo") == "demo"
    # API snapshots are stored in the same place and addressed the same way.
    assert _dataset_name("dataset://crm_rows") == "crm_rows"


def test_connection_string_round_trips_through_the_factory() -> None:
    url = build_connection_string({"type": "file", "database": "demo sales"})

    assert url == "fileupload://demo%20sales"
    assert _dataset_name(url) == "demo sales"


def test_api_connections_build_a_dataset_url() -> None:
    url = build_connection_string({"type": "api", "database": "crm_rows"})

    assert url == "dataset://crm_rows"
    assert _dataset_name(url) == "crm_rows"


def test_missing_dataset_is_a_clear_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("auto_ontology.dal.uploads.get_dataset", lambda _name: None)

    with pytest.raises(ValueError, match="No uploaded dataset"):
        FileUploadDatabase("fileupload://gone")


def test_connector_registers_the_table_and_reports_the_connection_name(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_ontology.dal.uploads.get_dataset", lambda _name: _dataset()
    )

    database = create_connector("fileupload://demo_sales")

    try:
        assert isinstance(database, FileUploadDatabase)
        assert database.dialect == "duckdb"
        # The catalog and text-to-SQL route on this name, so it must be the
        # connection's, not DuckDB's ``memory``.
        assert database.database_name == "demo_sales"

        tables = database.get_tables()
        assert tables.to_dict(orient="records") == [
            {"table_schema": "main", "table_name": "demo_sales"}
        ]

        qualified = database.qualify("main", "demo_sales")
        assert qualified == '"demo_sales"."main"."demo_sales"'
        rows = database.execute(f"SELECT COUNT(*) AS n FROM {qualified}")
        assert int(rows.iloc[0]["n"]) == 3

        # Generated SQL names the table ``database.schema.table``; the attached
        # catalog is what makes that three-part name resolve.
        rows = database.execute("SELECT COUNT(*) AS n FROM demo_sales.main.demo_sales")
        assert int(rows.iloc[0]["n"]) == 3
    finally:
        database.close()


def test_get_columns_reports_real_nullability(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "auto_ontology.dal.uploads.get_dataset", lambda _name: _dataset()
    )

    database = FileUploadDatabase("fileupload://demo_sales")
    try:
        columns = database.get_columns().set_index("column_name")
        assert bool(columns.loc["name", "is_nullable"]) is True
        assert bool(columns.loc["customer_id", "is_nullable"]) is False
    finally:
        database.close()


def test_query_history_is_empty(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "auto_ontology.dal.uploads.get_dataset", lambda _name: _dataset()
    )

    database = FileUploadDatabase("fileupload://demo_sales")
    try:
        history = database.get_queries()
        assert list(history.columns) == ["end_time", "query_text"]
        assert history.empty
    finally:
        database.close()


def test_corrupt_stored_data_is_a_clear_error(monkeypatch: MonkeyPatch) -> None:
    dataset = _dataset()
    dataset["content"] = b"not parquet"
    monkeypatch.setattr("auto_ontology.dal.uploads.get_dataset", lambda _name: dataset)

    with pytest.raises(ValueError, match="could not be read"):
        FileUploadDatabase("fileupload://demo_sales")
