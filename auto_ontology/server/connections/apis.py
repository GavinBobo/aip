# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connections whose table is fetched from a REST endpoint.

The endpoint is read when the connection is created and again on an explicit
refresh; the rows are stored exactly like an uploaded file, so querying,
cataloguing, and the text-to-SQL path are shared with "Excel / CSV".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from auto_ontology.dal.uploads import delete_dataset, upsert_dataset
from auto_ontology.server.connections import service
from auto_ontology.server.connections.files import validate_name
from auto_ontology.utils.api_source import (
    ApiSourceError,
    apply_column_names,
    fetch_frame,
    normalize_config,
    preview_api,
)
from auto_ontology.utils.tabular_files import frame_to_parquet, sanitize_table_name

logger = logging.getLogger(__name__)


def _fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _materialise(
    config: Mapping[str, Any],
    columns: Sequence[Mapping[str, Any]] | None,
) -> tuple[bytes, list[dict[str, str]], int]:
    frame = fetch_frame(config)
    frame, pairs = apply_column_names(frame, columns)
    return frame_to_parquet(frame), pairs, len(frame)


def _store_dataset(
    database: str, config: Mapping[str, Any], payload: bytes, rows: int
) -> None:
    upsert_dataset(
        name=database,
        filename=f"{config['method']} {config['url']}",
        table_name=sanitize_table_name(database),
        row_count=rows,
        content=payload,
    )


def preview_api_connection(raw_config: Mapping[str, Any]) -> dict[str, Any]:
    """Fetch the endpoint once and describe its rows for the wizard."""
    return preview_api(normalize_config(raw_config))


def create_api_connection(
    *,
    database: str,
    config: Mapping[str, Any],
    columns: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch the endpoint and register the result as a connection."""
    database = validate_name(database)
    if service._database_already_connected(database):
        raise ValueError(f"A connection for database {database!r} already exists")

    normalized = normalize_config(config)
    # The rename map may arrive as its own argument (the router) or inside the
    # posted connection object (a caller handing over the whole form).
    payload, pairs, rows = _materialise(
        normalized, columns if columns is not None else config.get("columns")
    )
    _store_dataset(database, normalized, payload, rows)

    connection: dict[str, Any] = {
        "type": "api",
        "database": database,
        **normalized,
        "columns": pairs,
        "row_count": rows,
        "fetched_at": _fetched_at(),
    }
    try:
        return service.create_connection(connection=connection)
    except Exception:
        delete_dataset(database)
        raise


def refresh_api_connection(
    database_name: str,
    *,
    config: Mapping[str, Any] | None = None,
    columns: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-fetch a REST connection's rows (optionally with edited settings).

    Serving a question never calls the endpoint: the stored snapshot is what
    queries run against, and this is the one operation that advances it. The
    catalog is rebuilt because the columns may have moved with the data.
    """
    stored = service._stored_connection(database_name)
    if stored is None:
        raise LookupError(f"No connection found for database {database_name!r}")
    if str(stored.get("type") or "") != "api":
        raise ValueError(f"Connection {database_name!r} is not an API connection")

    merged = {**stored, **(config or {})}
    normalized = normalize_config(merged)
    # Blank secrets in an edit keep the stored ones; the UI never receives them.
    for secret in ("token", "password"):
        if not str(normalized.get(secret) or "") and stored.get(secret):
            normalized[secret] = stored[secret]

    payload, pairs, rows = _materialise(
        normalized, columns if columns is not None else stored.get("columns")
    )
    _store_dataset(database_name, normalized, payload, rows)

    connection: dict[str, Any] = {
        **stored,
        **normalized,
        "columns": pairs,
        "row_count": rows,
        "fetched_at": _fetched_at(),
    }
    updated = service.update_connection(
        database_name=database_name, connection=connection
    )
    # The data moved even if the connection's filters did not, so the catalog
    # has to be rebuilt.
    from auto_ontology.server.ingestion.proxy import trigger_ingest

    trigger_ingest(updated)
    return updated


__all__ = [
    "ApiSourceError",
    "create_api_connection",
    "preview_api_connection",
    "refresh_api_connection",
]
