# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connections backed by an uploaded spreadsheet, CSV, or Parquet file.

The wizard flow is: upload → preview → choose the header row → rename columns →
create. The chosen shape is materialised once (Parquet, stored on the catalog
database) and from then on the connection behaves like any other source: the
catalog is ingested from it and text-to-SQL runs against it through DuckDB.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

from all_ontology.dal.uploads import delete_dataset, upsert_dataset
from all_ontology.server.connections import service
from all_ontology.server.ingestion.proxy import trigger_ingest
from all_ontology.utils.tabular_files import (
    SUPPORTED_SUFFIXES,
    TabularFileError,
    build_frame,
    detect_format,
    frame_to_parquet,
    normalize_delimiter,
    preview,
    sanitize_table_name,
)

logger = logging.getLogger(__name__)

#: Largest upload accepted. Bigger files are rejected before parsing: the
#: workbook is decoded in memory and the result is stored on the catalog row,
#: so an unbounded upload is an unbounded memory and database cost.
MAX_UPLOAD_BYTES = int(os.environ.get("FILE_UPLOAD_MAX_BYTES", str(100 * 1024 * 1024)))

#: Connection names double as the catalog key, the dataset's storage key, and
#: the DuckDB catalog that generated SQL names in ``database.schema.table``.
#: The prompt renders that unquoted, so the name has to be a plain identifier.
_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: Names shadowed by fixed ``/connections/<name>`` routes. The Next.js route
#: handlers for ``test``, ``source``, ``file``, and ``api`` win over the
#: dynamic ``[database_name]`` handler, so a connection with one of these
#: names could be created yet never read, updated, or deleted.
_RESERVED_NAMES = frozenset({"test", "source", "file", "api"})


def validate_name(name: str) -> str:
    """Return a cleaned connection name or raise ``ValueError``."""
    cleaned = str(name or "").strip()
    if not _NAME_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Database name must start with a letter or underscore and contain "
            "only letters, digits, and underscores (up to 64 characters)"
        )
    if cleaned.lower() in _RESERVED_NAMES:
        # These collide with fixed /connections/<name> routes on both the
        # FastAPI and Next.js sides; the connection would become unreachable.
        raise ValueError(
            "That connection name is reserved by the API; choose a different name"
        )
    return cleaned


def source_roots() -> list[Path]:
    """Directories the server-side file picker may browse or read.

    ``FILE_SOURCE_ROOTS`` is a path-separator- or comma-separated allowlist.
    When it is unset, the local ``./shared`` directory is the only root, which
    keeps local development useful without exposing the rest of the host.
    """
    raw = os.environ.get("FILE_SOURCE_ROOTS", "").strip()
    configured = [
        part.strip()
        for chunk in raw.split(os.pathsep)
        for part in chunk.split(",")
        if part.strip()
    ]
    candidates = (
        [Path(part).expanduser() for part in configured]
        if configured
        else [Path.cwd() / "shared"]
    )

    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_dir() or resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _root_containing(path: Path, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        if path == root or root in path.parents:
            return root
    return None


def _resolve_source_path(raw_path: str) -> tuple[Path, list[Path], Path]:
    """Resolve *raw_path* and prove it stays inside a configured root."""
    roots = source_roots()
    if not roots:
        raise ValueError(
            "No server-side shared folders are configured. Set FILE_SOURCE_ROOTS "
            "to one or more readable directories."
        )
    raw = str(raw_path or "").strip()
    if raw == "":
        raise ValueError("A server file path is required")
    try:
        candidate = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Could not open {raw!r}: {exc}") from exc
    root = _root_containing(candidate, roots)
    if root is None:
        raise ValueError("The path is outside the configured shared folders")
    return candidate, roots, root


def browse_source_path(raw_path: str | None = None) -> dict[str, Any]:
    """List one shared-folder directory, or the roots when none is selected."""
    roots = source_roots()
    if not roots:
        return {"roots": [], "path": None, "parent": None, "entries": []}

    if raw_path is None or str(raw_path).strip() == "":
        if len(roots) > 1:
            return {
                "roots": [str(root) for root in roots],
                "path": None,
                "parent": None,
                "entries": [
                    {
                        "name": root.name or str(root),
                        "path": str(root),
                        "kind": "directory",
                        "is_root": True,
                    }
                    for root in roots
                ],
            }
        directory = roots[0]
        root = directory
    else:
        directory, _, root = _resolve_source_path(str(raw_path))
        if not directory.is_dir():
            raise ValueError(f"{str(raw_path)!r} is not a directory")

    try:
        children = list(directory.iterdir())
    except OSError as exc:
        raise ValueError(f"Could not list {str(directory)!r}: {exc}") from exc

    entries: list[dict[str, Any]] = []
    for child in children:
        try:
            resolved = child.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if _root_containing(resolved, roots) is None:
            continue
        if resolved.is_dir():
            entries.append(
                {"name": child.name, "path": str(resolved), "kind": "directory"}
            )
        elif resolved.is_file() and resolved.suffix.lower() in SUPPORTED_SUFFIXES:
            try:
                size = resolved.stat().st_size
            except OSError:
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(resolved),
                    "kind": "file",
                    "size": size,
                }
            )
    entries.sort(
        key=lambda entry: (entry["kind"] != "directory", entry["name"].lower())
    )

    parent = None if directory == root else str(directory.parent)
    return {
        "roots": [str(item) for item in roots],
        "path": str(directory),
        "parent": parent,
        "entries": entries,
    }


def _read_source_file(raw_path: str) -> tuple[str, bytes]:
    source, _, _ = _resolve_source_path(raw_path)
    if not source.is_file():
        raise ValueError(f"{str(source)!r} is not a file")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not read {str(source)!r}: {exc}") from exc
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"The file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
            "file limit"
        )
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read {str(source)!r}: {exc}") from exc
    _checked_content(source.name, content)
    return source.name, content


def preview_source_file(
    path: str,
    *,
    sheet: str | None = None,
    delimiter: str | None = None,
) -> dict[str, Any]:
    """Preview a file read from a configured server-side shared folder."""
    filename, content = _read_source_file(path)
    return preview_file(filename, content, sheet=sheet, delimiter=delimiter)


def _checked_content(filename: str, content: bytes) -> bytes:
    """Validate an upload's type and size before any parsing happens."""
    if not content:
        raise ValueError("The uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"The file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
            "upload limit"
        )
    detect_format(filename)
    return content


def preview_file(
    filename: str,
    content: bytes,
    *,
    sheet: str | None = None,
    delimiter: str | None = None,
) -> dict[str, Any]:
    """Describe an upload for the header/rename step."""
    _checked_content(filename, content)
    return preview(filename, content, sheet=sheet, delimiter=delimiter)


def _materialise(
    filename: str,
    content: bytes,
    *,
    sheet: str | None,
    header_row: int,
    columns: Sequence[str] | None,
    delimiter: str | None,
    keep_columns: Sequence[int] | None = None,
) -> tuple[bytes, list[str], int]:
    """Build the stored Parquet plus the column names and row count."""
    _checked_content(filename, content)
    try:
        frame = build_frame(
            filename,
            content,
            sheet=sheet,
            header_row=header_row,
            columns=columns,
            delimiter=delimiter,
            keep_columns=keep_columns,
        )
    except TabularFileError:
        raise
    except Exception as exc:  # noqa: BLE001 - driver/engine specific
        raise TabularFileError(f"Could not read the file: {exc}") from exc
    return frame_to_parquet(frame), [str(name) for name in frame.columns], len(frame)


def create_file_connection(
    *,
    filename: str,
    content: bytes,
    database: str,
    sheet: str | None = None,
    header_row: int = 0,
    columns: Sequence[str] | None = None,
    delimiter: str | None = None,
    keep_columns: Sequence[int] | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    """Store the upload and register it as a connection."""
    database = validate_name(database)
    delimiter = normalize_delimiter(delimiter)
    if service._database_already_connected(database):
        raise ValueError(f"A connection for database {database!r} already exists")

    payload, column_names, row_count = _materialise(
        filename,
        content,
        sheet=sheet,
        header_row=header_row,
        columns=columns,
        delimiter=delimiter,
        keep_columns=keep_columns,
    )
    table_name = sanitize_table_name(database)
    upsert_dataset(
        name=database,
        filename=filename,
        table_name=table_name,
        row_count=row_count,
        content=payload,
    )

    connection: dict[str, Any] = {
        "type": "file",
        "database": database,
        "filename": filename,
        "sheet": sheet,
        "delimiter": delimiter,
        "header_row": int(header_row),
        "columns": column_names,
        "table": table_name,
        "row_count": row_count,
        "source_path": source_path,
    }
    try:
        return service.create_connection(connection=connection)
    except Exception:
        # A failed create must not leave an orphaned blob behind.
        delete_dataset(database)
        raise


def replace_file_dataset(
    database_name: str,
    *,
    filename: str,
    content: bytes,
    sheet: str | None = None,
    header_row: int = 0,
    columns: Sequence[str] | None = None,
    delimiter: str | None = None,
    keep_columns: Sequence[int] | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    """Replace a file connection's data and re-ingest it.

    The shape is re-materialised and the catalog rebuilt: renaming a column or
    choosing a different header row changes every column the catalog knows, so
    an update that skipped ingestion would leave the old schema queryable.
    """
    stored = service._stored_connection(database_name)
    if stored is None:
        raise LookupError(f"No connection found for database {database_name!r}")
    if str(stored.get("type") or "") != "file":
        raise ValueError(f"Connection {database_name!r} is not a file connection")

    delimiter = normalize_delimiter(delimiter)
    payload, column_names, row_count = _materialise(
        filename,
        content,
        sheet=sheet,
        header_row=header_row,
        columns=columns,
        delimiter=delimiter,
        keep_columns=keep_columns,
    )
    table_name = sanitize_table_name(database_name)
    upsert_dataset(
        name=database_name,
        filename=filename,
        table_name=table_name,
        row_count=row_count,
        content=payload,
    )

    connection: dict[str, Any] = {
        **stored,
        "filename": filename,
        "sheet": sheet,
        "delimiter": delimiter,
        "header_row": int(header_row),
        "columns": column_names,
        "table": table_name,
        "row_count": row_count,
        "source_path": source_path,
    }
    updated = service.update_connection(
        database_name=database_name, connection=connection
    )
    # ``update_connection`` re-ingests only when the schema/table filters moved;
    # here the *data* changed, so the catalog has to be rebuilt either way.
    trigger_ingest(updated)
    return updated


def create_file_connection_from_path(
    *,
    path: str,
    database: str,
    sheet: str | None = None,
    header_row: int = 0,
    columns: Sequence[str] | None = None,
    delimiter: str | None = None,
    keep_columns: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Create a file connection by reading a file from a shared folder."""
    source, _, _ = _resolve_source_path(path)
    filename, content = _read_source_file(path)
    return create_file_connection(
        filename=filename,
        content=content,
        database=database,
        sheet=sheet,
        header_row=header_row,
        columns=columns,
        delimiter=delimiter,
        keep_columns=keep_columns,
        source_path=str(source),
    )


def replace_file_dataset_from_path(
    database_name: str,
    *,
    path: str,
    sheet: str | None = None,
    header_row: int = 0,
    columns: Sequence[str] | None = None,
    delimiter: str | None = None,
    keep_columns: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Replace a file connection's rows from a shared-folder file."""
    source, _, _ = _resolve_source_path(path)
    filename, content = _read_source_file(path)
    return replace_file_dataset(
        database_name,
        filename=filename,
        content=content,
        sheet=sheet,
        header_row=header_row,
        columns=columns,
        delimiter=delimiter,
        keep_columns=keep_columns,
        source_path=str(source),
    )
