# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fetch tabular rows from a REST endpoint.

Backs the "REST API" connection type: the settings UI names a URL (plus
headers/params/body/auth), fetches it once for a preview, and the chosen shape
is stored like an uploaded file. The API is therefore read on demand —
creation, an explicit Refresh, or a re-ingest — never on every query, so a
slow or rate-limited endpoint cannot sit in the path of answering a question.
"""

from __future__ import annotations

import io
import json
import logging
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import httpx

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_METHODS = ("GET", "POST")
#: Keys that hold the row array in the usual REST wrappers. Used only when the
#: caller does not name a ``records_path``.
_RECORD_KEYS = ("data", "items", "results", "rows", "records", "value", "values")
#: Response bodies larger than this are refused rather than parsed.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
#: Rows shown by the preview.
PREVIEW_ROW_LIMIT = 20


class ApiSourceError(ValueError):
    """The endpoint could not be read as a table."""


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    """Accept a JSON object or its text form (the form sends textareas)."""
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiSourceError(f"{field} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ApiSourceError(f"{field} must be a JSON object")
        return {str(key): item for key, item in parsed.items()}
    raise ApiSourceError(f"{field} must be a JSON object")


def _as_body(value: Any) -> Any:
    """Accept a JSON body as an object or its text form."""
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ApiSourceError(f"body is not valid JSON: {exc}") from exc
    raise ApiSourceError("body must be a JSON value")


def normalize_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalise the request settings stored on a connection."""
    url = str(raw.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ApiSourceError("URL must start with http:// or https://")

    method = str(raw.get("method") or "GET").strip().upper()
    if method not in SUPPORTED_METHODS:
        raise ApiSourceError(f"Method must be one of {', '.join(SUPPORTED_METHODS)}")

    auth_type = str(raw.get("auth_type") or "none").strip().lower()
    if auth_type not in ("none", "bearer", "basic"):
        raise ApiSourceError("Auth must be none, bearer, or basic")

    timeout = raw.get("timeout_s", 30)
    try:
        timeout_s = max(1, min(int(timeout), 300))
    except (TypeError, ValueError) as exc:
        raise ApiSourceError("Timeout must be a number of seconds") from exc

    body = _as_body(raw.get("body"))
    if method == "GET" and body is not None:
        # A GET body is legal HTTP but almost always a mistake in this form.
        raise ApiSourceError("A GET request cannot carry a body; use POST")

    return {
        "url": url,
        "method": method,
        "headers": _as_mapping(raw.get("headers"), "headers"),
        "params": _as_mapping(raw.get("params"), "params"),
        "body": body,
        "records_path": str(raw.get("records_path") or "").strip(),
        "auth_type": auth_type,
        "token": str(raw.get("token") or ""),
        "user": str(raw.get("user") or ""),
        "password": str(raw.get("password") or ""),
        "timeout_s": timeout_s,
    }


def _walk(payload: Any, path: str) -> Any:
    target = payload
    for part in path.split("."):
        if not isinstance(target, Mapping) or part not in target:
            raise ApiSourceError(
                f"records_path {path!r} does not exist in the response"
            )
        target = target[part]
    return target


def _find_records(payload: Any, path: str = "", depth: int = 0) -> list[Any]:
    """The row array in *payload*, following *path* or the usual wrapper keys.

    Wrappers nest in practice (``{"data": {"items": [...]}}``), so a mapping
    found under a wrapper key is searched one or two levels deeper before the
    payload is treated as a single row.
    """
    target = _walk(payload, path) if path else payload
    if isinstance(target, list):
        return target
    if isinstance(target, Mapping):
        for key in _RECORD_KEYS:
            value = target.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, Mapping) and depth < 2:
                nested = _find_records(value, "", depth + 1)
                if nested:
                    return nested
        # One object with scalar fields is one row.
        return [target] if depth == 0 else []
    raise ApiSourceError(
        "The response is not a JSON object or array; name a records_path "
        "that points at the rows"
    )


def _stringify_nested(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn leftover arrays/objects into JSON text so Parquet can hold them."""
    for column in frame.columns:
        values = frame[column]
        if any(isinstance(value, (dict, list)) for value in values.head(200)):
            frame[column] = values.map(
                lambda value: (
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list))
                    else value
                )
            )
    return frame


def apply_column_names(
    frame: pd.DataFrame,
    columns: Sequence[Mapping[str, Any]] | None,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Rename columns by *source* name, ignoring sources the API dropped.

    Name-based rather than positional: a JSON key's position is not part of its
    contract, so a new field appearing first must not shift every rename.
    """
    wanted: dict[str, str] = {}
    for entry in columns or ():
        source = str(entry.get("source") or "").strip()
        name = str(entry.get("name") or "").strip()
        if source and name:
            wanted[source] = name

    renamed: dict[str, str] = {}
    seen: set[str] = set()
    for column in frame.columns:
        source = str(column)
        candidate = wanted.get(source) or source
        unique = candidate
        suffix = 2
        while unique.casefold() in seen:
            unique = f"{candidate}_{suffix}"
            suffix += 1
        seen.add(unique.casefold())
        renamed[column] = unique

    frame = frame.rename(columns=renamed)
    pairs = [{"source": str(source), "name": name} for source, name in renamed.items()]
    return frame, pairs


def fetch_frame(config: Mapping[str, Any]) -> pd.DataFrame:
    """Call the endpoint and return its rows as a DataFrame."""
    import pandas as pd

    headers = dict(config.get("headers") or {})
    auth = None
    if config.get("auth_type") == "bearer":
        token = str(config.get("token") or "")
        if not token:
            raise ApiSourceError("A bearer token is required")
        headers["Authorization"] = f"Bearer {token}"
    elif config.get("auth_type") == "basic":
        user = str(config.get("user") or "")
        password = str(config.get("password") or "")
        if not user:
            raise ApiSourceError("A username is required for basic auth")
        auth = (user, password)

    url = str(config["url"])
    method = str(config.get("method") or "GET")
    logger.info("Fetching API source %s %s", method, url)

    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            params=dict(config.get("params") or {}),
            json=config.get("body"),
            auth=auth,
            timeout=float(config.get("timeout_s") or 30),
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ApiSourceError(f"Could not reach the API: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:300].strip()
        raise ApiSourceError(
            f"The API returned HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
        )

    content = response.content
    if len(content) > MAX_RESPONSE_BYTES:
        raise ApiSourceError(
            f"The response is larger than the "
            f"{MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )

    content_type = response.headers.get("content-type", "").lower()
    if "csv" in content_type:
        try:
            frame = pd.read_csv(io.BytesIO(content))
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422
            raise ApiSourceError(f"Could not read the CSV response: {exc}") from exc
    else:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiSourceError(
                "The response is not JSON or CSV; check the URL and headers"
            ) from exc
        records = _find_records(payload, str(config.get("records_path") or ""))
        if not records:
            raise ApiSourceError("The API returned no rows")
        if all(isinstance(record, Mapping) for record in records):
            frame = pd.json_normalize(records, max_level=2)
        else:
            frame = pd.DataFrame({"value": records})

    if frame.empty:
        raise ApiSourceError("The API returned no rows")
    return _stringify_nested(frame)


def preview_api(
    config: Mapping[str, Any], *, row_limit: int = PREVIEW_ROW_LIMIT
) -> dict[str, Any]:
    """Describe the endpoint's rows for the rename step of the wizard."""
    import pandas as pd

    frame = fetch_frame(config)
    frame, pairs = apply_column_names(frame, None)

    rows: list[list[str | None]] = []
    for _, row in frame.head(row_limit).iterrows():
        rows.append(
            [
                None
                if value is None or (isinstance(value, float) and pd.isna(value))
                else str(value)
                for value in row
            ]
        )

    return {
        "rows": rows,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": pairs,
        "url": config["url"],
        "method": config["method"],
    }


__all__ = [
    "ApiSourceError",
    "MAX_RESPONSE_BYTES",
    "PREVIEW_ROW_LIMIT",
    "SUPPORTED_METHODS",
    "apply_column_names",
    "fetch_frame",
    "normalize_config",
    "preview_api",
]
