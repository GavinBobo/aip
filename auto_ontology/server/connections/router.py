# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for UI-managed database connections."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, TypedDict

from fastapi import APIRouter, File, Form, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from auto_ontology.dal.connections import list_connections as _list_connections
from auto_ontology.server.connections import apis, files, service
from auto_ontology.server.responses import (
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    SsoFederationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionBody(BaseModel):
    connection: dict[str, Any]


class ConnectionTestBody(ConnectionBody):
    replacing: str | None = None


class ApiPreviewBody(ConnectionBody):
    replacing: str | None = None


class FileSourcePreviewBody(BaseModel):
    """A file already present in one of the server's shared folders."""

    path: str
    sheet: str | None = None
    delimiter: str | None = None


class FileSourceSettings(FileSourcePreviewBody):
    header_row: int = 0
    columns: list[str] | None = None


class FileSourceBody(FileSourceSettings):
    database: str


class FilePreviewResponse(BaseModel):
    """What the header/rename step needs to draw the upload."""

    filename: str
    format: str
    sheets: list[str]
    sheet: str | None
    #: Separator actually used for a delimited file; null for workbooks/Parquet.
    delimiter: str | None
    rows: list[list[str | None]]
    row_count: int
    column_count: int
    column_names: list[str]
    detected_header_row: int
    supports_header_row: bool


class ApiPreviewResponse(BaseModel):
    """What the rename step needs to draw a REST response."""

    rows: list[list[str | None]]
    row_count: int
    column_count: int
    columns: list[dict[str, str]]
    url: str
    method: str


class PublicConnection(TypedDict):
    database_name: str
    connection: dict[str, Any]


def _serialize_connection(connection: dict[str, Any]) -> PublicConnection:
    """Shape a connection object into a credential-free public payload."""
    public_connection = {
        key: value
        for key, value in connection.items()
        if key not in service.SECRET_FIELDS
    }
    return {
        "database_name": str(connection.get("database") or ""),
        "connection": public_connection,
    }


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Read an upload, rejecting oversized bodies before parsing them."""
    filename = file.filename or "upload"
    if file.size is not None and file.size > files.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"The file is larger than the "
                f"{files.MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
            ),
        )
    return filename, await file.read()


def _parse_columns(raw: str | None) -> list[str] | None:
    """Decode the ``columns`` form field, a JSON array of names."""
    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="columns must be a JSON array of names"
        ) from exc
    if not isinstance(value, list):
        raise HTTPException(
            status_code=422, detail="columns must be a JSON array of names"
        )
    return [str(item) for item in value]


@router.get("/connections/source", response_model=bool)
def is_env_source() -> bool:
    """Report whether connections are managed via the ``CONNECTION_STRINGS`` env."""
    connection_strings = os.environ.get("CONNECTION_STRINGS", "")
    connection_strings_exists = [
        cs.strip() for cs in connection_strings.split(",") if cs.strip()
    ]
    return bool(connection_strings_exists)


@router.get("/connections", response_model=ConnectionListResponse)
def list_connections() -> dict:
    """List every configured database connection, credential-free.

    Credentials — passwords, private keys and the Kyuubi truststore password —
    are stripped from each connection object, so the payload is safe to render
    in the UI. ``database_name`` doubles as the connection's identity in the
    other routes here.
    """
    rows = [_serialize_connection(conn) for conn in _list_connections()]
    return {"data": rows, "count": len(rows)}


@router.post("/connections/test", response_model=ConnectionTestResponse)
def test_connection(body: ConnectionTestBody) -> dict:
    """Validate a connection and return its schemas (for the schema picker).

    Set ``replacing`` to the ``database_name`` of the connection an edit is
    about to overwrite. Without it the test rejects the connection for already
    existing, and blank credentials stay blank instead of being taken from the
    stored connection the way ``PUT /connections/{database_name}`` would.
    """
    try:
        schemas = service.test_connection(body.connection, replacing=body.replacing)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Connection test failed: {exc}",
        ) from exc
    return {"success": True, "schemas": schemas}


@router.post("/connections/file/preview", response_model=FilePreviewResponse)
async def preview_file_upload(
    file: UploadFile = File(description="Spreadsheet, delimited file, or Parquet"),
    sheet: str | None = Form(default=None, description="Sheet to read, for Excel"),
    delimiter: str | None = Form(
        default=None,
        description=(
            "Separator for a delimited file; omit to detect it. One character."
        ),
    ),
) -> dict:
    """Preview an uploaded table so the operator can choose its shape.

    Returns the first rows verbatim (no header applied), the detected header
    row, and the workbook's sheet names. Nothing is stored: the same file is
    uploaded again with the chosen header row and column names when the
    connection is created.
    """
    filename, content = await _read_upload(file)
    try:
        # Parsing a workbook is CPU-bound and can take seconds; the threadpool
        # keeps it off the event loop so other requests keep being served.
        return await run_in_threadpool(
            files.preview_file,
            filename,
            content,
            sheet=sheet,
            delimiter=delimiter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not preview the file: {exc}"
        ) from exc


@router.get("/connections/file/browse")
def browse_file_source(path: str | None = Query(default=None)) -> dict:
    """List shared-folder directories and supported files for the path picker.

    Only paths below ``FILE_SOURCE_ROOTS`` (or ``./shared`` by default) are
    visible. Symlinks are resolved first, so a link cannot escape the roots.
    """
    try:
        return files.browse_source_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/connections/file/preview-path", response_model=FilePreviewResponse)
def preview_file_source(body: FileSourcePreviewBody) -> dict:
    """Preview a file read from a configured server-side shared folder."""
    try:
        return files.preview_source_file(
            body.path, sheet=body.sheet, delimiter=body.delimiter
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not preview the file: {exc}"
        ) from exc


@router.post("/connections/file", status_code=201, response_model=ConnectionResponse)
async def create_file_connection(
    file: UploadFile = File(description="Spreadsheet, delimited file, or Parquet"),
    database: str = Form(description="Connection name, also the catalog key"),
    sheet: str | None = Form(default=None, description="Sheet to read, for Excel"),
    delimiter: str | None = Form(
        default=None, description="Separator for a delimited file; omit to detect"
    ),
    header_row: int = Form(default=0, description="Zero-based header row"),
    columns: str | None = Form(
        default=None, description="JSON array of column names, in order"
    ),
) -> dict:
    """Create a connection from an uploaded file.

    The file is materialised once (Parquet) and stored with the catalog, then
    ingested like any other connection. ``columns`` renames the header row's
    columns positionally; blank names fall back to the file's own header.
    """
    column_names = _parse_columns(columns)
    filename, content = await _read_upload(file)
    try:
        row = await run_in_threadpool(
            files.create_file_connection,
            filename=filename,
            content=content,
            database=database,
            sheet=sheet,
            delimiter=delimiter,
            header_row=header_row,
            columns=column_names,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to create connection: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.post(
    "/connections/file-path", status_code=201, response_model=ConnectionResponse
)
def create_file_connection_from_path(body: FileSourceBody) -> dict:
    """Create a connection from a file in a configured shared folder."""
    try:
        row = files.create_file_connection_from_path(
            path=body.path,
            database=body.database,
            sheet=body.sheet,
            header_row=body.header_row,
            columns=body.columns,
            delimiter=body.delimiter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to create connection: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.post("/connections/api/preview", response_model=ApiPreviewResponse)
def preview_api_source(body: ApiPreviewBody) -> dict:
    """Fetch a REST endpoint once and describe its rows.

    Runs on the threadpool (it is a blocking HTTP call) and stores nothing —
    the same settings are submitted again when the connection is created.
    """
    connection = body.connection
    if body.replacing:
        # Editing: the UI never receives the stored token/password, so a blank
        # secret here means "use the stored one", exactly as on save.
        stored = service._stored_connection(body.replacing)
        if stored is not None:
            connection = service._with_stored_secrets(connection, stored)
    try:
        return apis.preview_api_connection(connection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not read the API: {exc}"
        ) from exc


@router.post("/connections/api", status_code=201, response_model=ConnectionResponse)
def create_api_connection(body: ConnectionBody) -> dict:
    """Create a connection by fetching a REST endpoint.

    ``columns`` renames the response's fields by source name; the rows are
    stored as a snapshot and queried through DuckDB, exactly like an uploaded
    file. Use ``POST /connections/{name}/refresh`` to fetch again.
    """
    connection = body.connection
    try:
        row = apis.create_api_connection(
            database=str(connection.get("database") or ""),
            config=connection,
            columns=connection.get("columns"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to create connection: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.post("/connections", status_code=201, response_model=ConnectionResponse)
def create_connection(body: ConnectionBody) -> dict:
    """Register a database connection and return it credential-free.

    The connection is validated on the way in; anything the driver rejects comes
    back as 422 with the failure message rather than a 500. Call
    ``POST /connections/test`` first to check credentials and list the schemas
    available for the picker.
    """
    try:
        row = service.create_connection(connection=body.connection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to create connection: {exc}",
        ) from exc

    return {"data": _serialize_connection(row)}


@router.put("/connections/{database_name}/file", response_model=ConnectionResponse)
async def replace_file_dataset(
    file: UploadFile = File(description="Replacement file"),
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
    sheet: str | None = Form(default=None),
    delimiter: str | None = Form(default=None),
    header_row: int = Form(default=0),
    columns: str | None = Form(default=None),
) -> dict:
    """Replace a file connection's data, keeping its name.

    Used by the edit form: the connection's identity is fixed, but the file,
    header row, and column names can all change. The catalog is rebuilt.
    """
    column_names = _parse_columns(columns)
    filename, content = await _read_upload(file)
    try:
        row = await run_in_threadpool(
            files.replace_file_dataset,
            database_name,
            filename=filename,
            content=content,
            sheet=sheet,
            delimiter=delimiter,
            header_row=header_row,
            columns=column_names,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to replace the data: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.put("/connections/{database_name}/file-path", response_model=ConnectionResponse)
def replace_file_dataset_from_path(
    body: FileSourceSettings,
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Replace a file connection's data with a shared-folder file."""
    try:
        row = files.replace_file_dataset_from_path(
            database_name,
            path=body.path,
            sheet=body.sheet,
            header_row=body.header_row,
            columns=body.columns,
            delimiter=body.delimiter,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to replace the data: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.put("/connections/{database_name}/api", response_model=ConnectionResponse)
def update_api_connection(
    body: ConnectionBody,
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Rewrite a REST connection's settings and fetch it again.

    Credentials left blank keep their stored value, as everywhere else.
    """
    connection = body.connection
    try:
        row = apis.refresh_api_connection(
            database_name,
            config=connection,
            columns=connection.get("columns"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to update connection: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.post("/connections/{database_name}/refresh", response_model=ConnectionResponse)
def refresh_connection(
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Fetch a REST connection again and rebuild its catalog.

    Only API connections have something to fetch; a file connection's rows are
    replaced by uploading a new file instead.
    """
    try:
        row = apis.refresh_api_connection(database_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Failed to refresh the data: {exc}"
        ) from exc
    return {"data": _serialize_connection(row)}


@router.put("/connections/{database_name}", response_model=ConnectionResponse)
def update_connection(
    body: ConnectionBody,
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Rewrite a connection's settings and return it credential-free.

    ``database`` and ``type`` are the connection's identity and cannot change —
    sending different ones is a 422. Credentials left blank keep their stored
    value, since the UI is never given them to send back. Re-ingest is
    triggered only when the ``schemas`` allowlist changed.

    404 when no connection carries that ``database_name``.
    """
    try:
        row = service.update_connection(
            database_name=database_name, connection=body.connection
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to update connection: {exc}",
        ) from exc

    return {"data": _serialize_connection(row)}


class SsoFederationBody(BaseModel):
    enabled: bool


@router.patch(
    "/connections/{database_name}/sso-federation",
    response_model=SsoFederationResponse,
)
def set_sso_federation(
    body: SsoFederationBody,
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Toggle whether chat runs this connection's SQL as the signed-in user."""
    try:
        row = service.set_sso_federation(
            database_name=database_name, enabled=body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to update connection: {exc}",
        ) from exc

    return {"data": row}


@router.delete("/connections/{database_name}", response_model=ConnectionResponse)
def delete_connection(
    database_name: str = Path(
        description=(
            "Catalog database name, which doubles as the connection's identity."
        )
    ),
) -> dict:
    """Remove a connection, echoing the database name it tore down.

    404 when no connection carries that ``database_name``. The connection
    record is removed synchronously, but deleting the data already ingested
    from it is handed to the ingestion service and is best-effort — a 200 means
    the connection is gone, not that its graph is.
    """
    try:
        row = service.delete_connection(database_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to delete connection: {exc}",
        ) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    return {"data": row}
