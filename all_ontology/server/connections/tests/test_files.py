# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Creating a connection from an uploaded file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from all_ontology.server.connections import files

CSV = b"id,name,amount\n1,Alice,10.5\n2,Bob,20\n"


def _stub_storage(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    """Replace storage and connection creation with in-memory fakes."""
    calls: dict[str, Any] = {"stored": [], "deleted": [], "created": [], "ingested": []}

    def upsert_dataset(**kwargs: Any) -> dict[str, Any]:
        calls["stored"].append(kwargs)
        return {"name": kwargs["name"]}

    def delete_dataset(name: str) -> None:
        calls["deleted"].append(name)

    def create_connection(*, connection: dict[str, Any]) -> dict[str, Any]:
        calls["created"].append(connection)
        return connection

    def update_connection(
        *, database_name: str, connection: dict[str, Any]
    ) -> dict[str, Any]:
        calls["created"].append(connection)
        return connection

    def trigger_ingest(connection: dict[str, Any]) -> None:
        calls["ingested"].append(connection)

    monkeypatch.setattr(files, "upsert_dataset", upsert_dataset)
    monkeypatch.setattr(files, "delete_dataset", delete_dataset)
    monkeypatch.setattr(files.service, "create_connection", create_connection)
    monkeypatch.setattr(files.service, "update_connection", update_connection)
    monkeypatch.setattr(files.service, "_database_already_connected", lambda _n: False)
    monkeypatch.setattr(files, "trigger_ingest", trigger_ingest)
    return calls


def test_create_stores_the_dataset_and_registers_the_connection(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub_storage(monkeypatch)

    connection = files.create_file_connection(
        filename="sales.csv",
        content=CSV,
        database="sales_data",
        header_row=0,
        columns=["customer_id", "name", "amount"],
    )

    assert connection["type"] == "file"
    assert connection["database"] == "sales_data"
    assert connection["table"] == "sales_data"
    assert connection["columns"] == ["customer_id", "name", "amount"]
    assert connection["row_count"] == 2
    assert calls["created"][0]["database"] == "sales_data"

    stored = calls["stored"][0]
    assert stored["name"] == "sales_data"
    assert stored["table_name"] == "sales_data"
    assert stored["row_count"] == 2
    # Parquet, not the raw CSV: the chosen shape is stored once.
    assert stored["content"][:4] == b"PAR1"


def test_existing_name_is_rejected_before_anything_is_stored(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub_storage(monkeypatch)
    monkeypatch.setattr(files.service, "_database_already_connected", lambda _n: True)

    with pytest.raises(ValueError, match="already exists"):
        files.create_file_connection(
            filename="sales.csv", content=CSV, database="sales_data"
        )

    assert calls["stored"] == []


def test_a_failed_create_removes_the_stored_dataset(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub_storage(monkeypatch)

    def boom(*, connection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("connection insert failed")

    monkeypatch.setattr(files.service, "create_connection", boom)

    with pytest.raises(RuntimeError):
        files.create_file_connection(
            filename="sales.csv", content=CSV, database="sales_data"
        )

    assert calls["deleted"] == ["sales_data"]


def test_preview_rejects_an_empty_file() -> None:
    with pytest.raises(ValueError, match="empty"):
        files.preview_file("sales.csv", b"")


def test_preview_passes_the_chosen_delimiter() -> None:
    result = files.preview_file("export.pcl", b"id^name\n1^Alice\n", delimiter="^")

    assert result["column_names"] == ["id", "name"]
    assert result["delimiter"] == "^"


def test_create_remembers_the_delimiter(monkeypatch: MonkeyPatch) -> None:
    calls = _stub_storage(monkeypatch)

    connection = files.create_file_connection(
        filename="export.pcl",
        content=b"id^name\n1^Alice\n2^Bob\n",
        database="pcl_rows",
        delimiter="^",
        header_row=0,
        columns=["id", "name"],
    )

    assert connection["delimiter"] == "^"
    assert calls["stored"][0]["row_count"] == 2


def test_preview_rejects_unsupported_types() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        files.preview_file("report.pdf", b"%PDF-1.7")


def test_preview_enforces_the_size_limit(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_UPLOAD_BYTES", 4)

    with pytest.raises(ValueError, match="upload limit"):
        files.preview_file("sales.csv", b"id,name\n")


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "../evil",
        "a/b",
        "sales data",
        "sales-data",
        "2024_sales",
        "x" * 65,
    ],
)
def test_invalid_connection_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="Database name"):
        files.validate_name(name)


@pytest.mark.parametrize("name", ["sales_data", "_sales", "Sales2024"])
def test_valid_connection_names_are_accepted(name: str) -> None:
    assert files.validate_name(name) == name


@pytest.mark.parametrize("name", ["test", "source", "file", "api", "TEST"])
def test_reserved_connection_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        files.validate_name(name)


def test_replace_rebuilds_the_catalog(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub_storage(monkeypatch)
    monkeypatch.setattr(
        files.service,
        "_stored_connection",
        lambda _n: {"type": "file", "database": "sales_data", "filename": "old.csv"},
    )

    updated = files.replace_file_dataset(
        "sales_data",
        filename="new.csv",
        content=CSV,
        header_row=0,
        columns=["id", "name", "amount"],
    )

    assert updated["filename"] == "new.csv"
    assert calls["stored"][0]["name"] == "sales_data"
    # Replacing data changes every column the catalog knows, so ingestion runs
    # even though the connection's filters did not move.
    assert calls["ingested"][0]["filename"] == "new.csv"


def test_replace_refuses_a_connection_of_another_type(
    monkeypatch: MonkeyPatch,
) -> None:
    _stub_storage(monkeypatch)
    monkeypatch.setattr(
        files.service,
        "_stored_connection",
        lambda _n: {"type": "postgresql", "database": "warehouse"},
    )

    with pytest.raises(ValueError, match="not a file connection"):
        files.replace_file_dataset("warehouse", filename="x.csv", content=CSV)


def test_source_roots_default_to_local_shared_directory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FILE_SOURCE_ROOTS", raising=False)
    shared = tmp_path / "shared"
    shared.mkdir()

    assert files.source_roots() == [shared.resolve()]


def test_browse_lists_only_supported_files_and_stays_inside_the_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "nested").mkdir()
    (shared / "sales.csv").write_bytes(CSV)
    (shared / "notes.pdf").write_bytes(b"%PDF-1.7")
    monkeypatch.setenv("FILE_SOURCE_ROOTS", str(shared))

    listing = files.browse_source_path()

    assert listing["path"] == str(shared.resolve())
    assert [entry["name"] for entry in listing["entries"]] == ["nested", "sales.csv"]

    outside = tmp_path / "outside.csv"
    outside.write_bytes(CSV)
    with pytest.raises(ValueError, match="outside the configured shared folders"):
        files.browse_source_path(str(outside))


def test_preview_source_file_reads_a_shared_folder_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    source = shared / "sales.csv"
    source.write_bytes(CSV)
    monkeypatch.setenv("FILE_SOURCE_ROOTS", str(shared))

    result = files.preview_source_file(str(source))

    assert result["filename"] == "sales.csv"
    assert result["row_count"] == 2
    assert result["column_names"] == ["id", "name", "amount"]


def test_create_from_path_records_the_server_source(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls = _stub_storage(monkeypatch)
    shared = tmp_path / "shared"
    shared.mkdir()
    source = shared / "sales.csv"
    source.write_bytes(CSV)
    monkeypatch.setenv("FILE_SOURCE_ROOTS", str(shared))

    connection = files.create_file_connection_from_path(
        path=str(source),
        database="sales_data",
        header_row=0,
        columns=["id", "name", "amount"],
    )

    assert connection["source_path"] == str(source.resolve())
    assert calls["created"][0]["source_path"] == str(source.resolve())
