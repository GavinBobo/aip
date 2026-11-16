# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Where the document-parsing model settings live, and how they take effect.

OXR persists its backend choice to ``data/model-settings.json``. Here the choice
lives in the same ``frontend.configurations`` table as every other setting this
product has, so it is covered by the existing backup, the existing admin page and
the existing permission (`catalog: edit`) — one place to look, one place to
audit.

A request picks up a changed setting within :data:`CACHE_TTL_S` without a
restart: the values are re-read, compared by fingerprint, and only a real change
triggers ``model_backend.activate`` (which stops a running local gateway before
switching). That matters because the alternative — "restart the API so it picks
up the new endpoint" — is the thing people forget, and the failure looks like a
broken parser rather than a stale process.

The JSON file is still written, to a temp directory, purely because
``ModelBackendManager`` persists there; nothing reads it back. The database is
the source of truth.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import psycopg

from all_ontology.infra.postgres import FRONTEND_SCHEMA, get_postgres_connection_string
from all_ontology.parsing.config.model_settings import (
    LayoutServiceSettings,
    LocalModelSettings,
    ModelBackendSettings,
    VLLMModelSettings,
)
from all_ontology.parsing.config.settings import PipelineConfig
from all_ontology.parsing.config.settings import settings
from all_ontology.parsing.model.backend import model_backend
from all_ontology.parsing.tasks import INSTANCE_ID

logger = logging.getLogger(__name__)

#: How long a read is trusted before the table is consulted again.
CACHE_TTL_S = 5.0

#: ``configurations`` keys owned by the parsing feature. Every one is optional:
#: a missing row means "use the field default", which is what OXR's
#: ``ModelBackendSettings()`` would have produced from an empty file.
KEYS = {
    "mode": "parsing_mode",
    "vllm_url": "parsing_vllm_url",
    "vllm_model": "parsing_vllm_model",
    "vllm_api_key": "parsing_vllm_api_key",
    "vllm_concurrency": "parsing_vllm_concurrency",
    "vllm_timeout": "parsing_vllm_timeout",
    "local_model_dir": "parsing_local_model_dir",
    "local_host": "parsing_local_host",
    "local_port": "parsing_local_port",
    "local_threads": "parsing_local_threads",
    "local_dtype": "parsing_local_dtype",
    "local_startup_timeout": "parsing_local_startup_timeout",
    "layout_url": "parsing_layout_url",
    "layout_batch_size": "parsing_layout_batch_size",
    "layout_concurrency": "parsing_layout_concurrency",
    "layout_timeout": "parsing_layout_timeout",
    "layout_retry_times": "parsing_layout_retry_times",
    "layout_score_threshold": "parsing_layout_score_threshold",
    "layout_nms_iou": "parsing_layout_nms_iou",
    "layout_provides_reading_order": "parsing_layout_provides_reading_order",
    # Where the parser keeps its files. Empty means "the default under logs/".
    "upload_dir": "parsing_upload_dir",
    "image_dir": "parsing_image_dir",
}

_lock = asyncio.Lock()
_fingerprint: str | None = None
_checked_at = 0.0
_initialized = False


def _as_int(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(KEYS[key], "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("parsing setting %s is not an integer: %r", KEYS[key], raw)
        return default


def _as_float(values: dict[str, str], key: str, default: float) -> float:
    raw = values.get(KEYS[key], "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("parsing setting %s is not a number: %r", KEYS[key], raw)
        return default


def _as_bool(values: dict[str, str], key: str, default: bool) -> bool:
    raw = values.get(KEYS[key], "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "on"}


def _as_text(values: dict[str, str], key: str, default: str = "") -> str:
    return values.get(KEYS[key], "").strip() or default


def build_config(values: dict[str, str]) -> ModelBackendSettings:
    """Turn stored strings into the settings model ``model_backend`` expects.

    Pydantic validates on construction, so a hand-edited row with a relative URL
    or a zero concurrency raises here rather than halfway through a parse. The
    caller treats that as "settings are unusable" and reports it on the page.
    """
    layout_defaults = LayoutServiceSettings()
    vllm_defaults = VLLMModelSettings()
    local_defaults = LocalModelSettings()

    mode = _as_text(values, "mode", "none").lower()
    if mode not in {"none", "local", "vllm"}:
        logger.warning("parsing mode %r is not recognised; using 'none'", mode)
        mode = "none"

    return ModelBackendSettings(
        mode=mode,
        vllm=VLLMModelSettings(
            url=_as_text(values, "vllm_url", vllm_defaults.url),
            model_name=_as_text(values, "vllm_model", vllm_defaults.model_name),
            api_key=_as_text(values, "vllm_api_key") or None,
            max_concurrency=_as_int(
                values, "vllm_concurrency", vllm_defaults.max_concurrency
            ),
            timeout=_as_int(values, "vllm_timeout", vllm_defaults.timeout),
        ),
        local=LocalModelSettings(
            model_dir=_as_text(values, "local_model_dir", local_defaults.model_dir),
            host=_as_text(values, "local_host", local_defaults.host),
            port=_as_int(values, "local_port", local_defaults.port),
            threads=_as_int(values, "local_threads", local_defaults.threads),
            dtype=_as_text(values, "local_dtype", local_defaults.dtype),
            startup_timeout=_as_int(
                values, "local_startup_timeout", local_defaults.startup_timeout
            ),
        ),
        layout=LayoutServiceSettings(
            url=_as_text(values, "layout_url", layout_defaults.url),
            batch_size=_as_int(values, "layout_batch_size", layout_defaults.batch_size),
            max_concurrency=_as_int(
                values, "layout_concurrency", layout_defaults.max_concurrency
            ),
            timeout=_as_int(values, "layout_timeout", layout_defaults.timeout),
            retry_times=_as_int(
                values, "layout_retry_times", layout_defaults.retry_times
            ),
            score_threshold=_as_float(
                values, "layout_score_threshold", layout_defaults.score_threshold
            ),
            nms_iou_threshold=_as_float(
                values, "layout_nms_iou", layout_defaults.nms_iou_threshold or 0.6
            ),
            provides_reading_order=_as_bool(
                values,
                "layout_provides_reading_order",
                layout_defaults.provides_reading_order,
            ),
        ),
    )


def apply_paths(values: dict[str, str]) -> None:
    """Point the pipeline's two output directories at the stored settings.

    Kept apart from :func:`build_config` because they are not part of the model
    backend: the recognition endpoint and the folder the answer lands in change
    independently. Relative paths are resolved against the process CWD, which is
    the repository root, so ``logs/parsing-assets`` means what it reads like.
    """
    upload_dir = _as_text(values, "upload_dir")
    image_dir = _as_text(values, "image_dir")
    settings.pipeline.upload_dir = upload_dir or PipelineConfig().upload_dir
    settings.pipeline.image_output_dir = image_dir or PipelineConfig().image_output_dir
    logger.debug(
        "Parsing paths: uploads=%s images=%s",
        settings.pipeline.upload_dir,
        settings.pipeline.image_output_dir,
    )


def read_stored() -> dict[str, str]:
    """Read the parsing rows, or an empty mapping when the table is unreadable.

    Best-effort on purpose: a first boot before the frontend migration must not
    make the API fail to start, and "no rows" is a valid state (backend
    unconfigured).
    """
    try:
        with (
            psycopg.connect(
                get_postgres_connection_string(), connect_timeout=3
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                f"SELECT key, value FROM {FRONTEND_SCHEMA}.configurations "
                "WHERE key = ANY(%s)",
                (list(KEYS.values()),),
            )
            return {str(row[0]): str(row[1]) for row in cur.fetchall()}
    except Exception:
        logger.warning("Failed to read parsing settings; using defaults", exc_info=True)
        return {}


def _fingerprint_of(values: dict[str, str]) -> str:
    material = json.dumps(values, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def ensure_current(*, force: bool = False) -> ModelBackendSettings:
    """Make ``model_backend`` reflect the stored settings; return them.

    Reads at most once per :data:`CACHE_TTL_S`, and re-activates only when the
    fingerprint actually changed — ``activate`` stops a running local gateway,
    which is not something to do on every parse request.
    """
    global _fingerprint, _checked_at, _initialized

    now = time.monotonic()
    if not force and _initialized and now - _checked_at < CACHE_TTL_S:
        return model_backend.config

    async with _lock:
        now = time.monotonic()
        if not force and _initialized and now - _checked_at < CACHE_TTL_S:
            return model_backend.config

        values = await asyncio.to_thread(read_stored)
        fingerprint = _fingerprint_of(values)
        # Paths are cheap and independent of the model backend, so they are
        # applied on every read rather than only when the backend changes.
        apply_paths(values)
        if not _initialized:
            # OXR's manager reads a JSON file on start; point that at a scratch
            # location so a stale file in a data directory cannot win.
            settings.model_settings_path = str(
                Path(tempfile.gettempdir())
                / "all-ontology-parsing"
                / "model-settings.json"
            )
            await model_backend.initialize()
            _initialized = True

        if fingerprint != _fingerprint:
            config = build_config(values)
            try:
                await model_backend.activate(config)
                _fingerprint = fingerprint
                logger.info(
                    "Applied parsing model settings (mode=%s, model=%s)",
                    config.mode,
                    getattr(config, config.mode).url
                    if config.mode in {"vllm"}
                    else config.mode,
                )
            except Exception:
                # Keep the previous backend working rather than leaving the
                # process with a half-applied configuration.
                logger.exception("Failed to apply parsing model settings")
        _checked_at = time.monotonic()
        return model_backend.config


async def status() -> dict[str, Any]:
    """The capabilities the settings page and the parse form both need."""
    await ensure_current()
    described = await model_backend.status()
    described["ready"] = bool(
        settings.oxr_model.url and settings.layout_analyze_model.url
    )
    described["model_url"] = settings.oxr_model.url
    described["layout_url"] = settings.layout_analyze_model.url
    described["instance"] = INSTANCE_ID
    described["paths"] = {
        "upload_dir": str(Path(settings.pipeline.upload_dir).resolve()),
        "image_dir": str(Path(settings.pipeline.image_output_dir).resolve()),
        "image_url_prefix": settings.pipeline.image_url_prefix,
    }

    # The browser edits these fields, but it must never receive the stored
    # credential: the form shows "saved — leave blank to keep" instead, exactly
    # like the LLM settings page does.
    vllm = described.get("vllm")
    if isinstance(vllm, dict) and vllm.get("api_key"):
        vllm["api_key"] = None
        vllm["api_key_configured"] = True
    elif isinstance(vllm, dict):
        vllm["api_key_configured"] = False
    return described
