# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persisted LLM endpoint settings written by Settings > LLM Settings.

The frontend owns the ``configurations`` table. The Python services apply these
overrides before importing modules that build their LLM clients at import time,
so a saved endpoint/key/model supersedes the equivalent environment variables
without changing embedding or reranking settings.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping

import psycopg

from all_ontology.infra.postgres import FRONTEND_SCHEMA, get_postgres_connection_string

logger = logging.getLogger(__name__)

LLM_BASE_URL_KEY = "llm_base_url"
LLM_API_KEY_KEY = "llm_api_key"
LLM_MODEL_KEY = "llm_model"

_SETTING_KEYS = (LLM_BASE_URL_KEY, LLM_API_KEY_KEY, LLM_MODEL_KEY)

# The conversational model is used through both the reasoning and
# non-reasoning triplets. Embedding and reranking keep their own environment
# configuration; a chat-model endpoint is not a valid embedding endpoint.
_TARGET_PREFIXES = ("REASONING", "NON_REASONING")


def read_llm_settings() -> dict[str, str]:
    """Read the persisted overrides, or return an empty mapping if unreadable."""
    try:
        with psycopg.connect(
            get_postgres_connection_string(), connect_timeout=3
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT key, value FROM {FRONTEND_SCHEMA}.configurations "
                    "WHERE key IN (%s, %s, %s)",
                    _SETTING_KEYS,
                )
                return {str(row[0]): str(row[1]) for row in cur.fetchall()}
    except Exception:
        # Settings are best-effort: a first boot before the frontend migration,
        # or a transient DB failure, must not stop the service from starting.
        logger.exception("Failed to read persisted LLM settings; using environment")
        return {}


def apply_llm_settings(settings: Mapping[str, str] | None = None) -> None:
    """Overlay persisted LLM settings onto the process environment.

    Empty values are ignored, so clearing a field in the UI restores the
    environment/default resolution for that field.
    """
    values = read_llm_settings() if settings is None else settings
    base_url = str(values.get(LLM_BASE_URL_KEY, "")).strip()
    api_key = str(values.get(LLM_API_KEY_KEY, "")).strip()
    model = str(values.get(LLM_MODEL_KEY, "")).strip()

    for prefix in _TARGET_PREFIXES:
        if base_url:
            os.environ[f"{prefix}_ENDPOINT"] = base_url
        if api_key:
            os.environ[f"{prefix}_API_KEY"] = api_key
        if model:
            os.environ[f"{prefix}_MODEL"] = model

    if base_url or api_key or model:
        logger.info(
            "Applied persisted LLM settings (endpoint=%s, model=%s, api_key=%s)",
            base_url or "environment",
            model or "environment",
            "saved" if api_key else "environment",
        )
