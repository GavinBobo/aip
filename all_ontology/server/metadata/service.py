# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Orchestration for ``question-entity-coverage``.

``entity_coverage`` runs a fast LangGraph that extracts entities, retrieves
semantic candidates, and returns a deterministic coverage grade.

The pipeline shares retriever/connector state and is not safe to run in parallel
(the same constraint that makes chat single-slot), so runs are serialized here.
"""

from __future__ import annotations

import logging
import threading

from all_ontology.retrieval.entity_coverage.state import (
    DEFAULT_MAX_DISTANCE,
    EntityCoveragePayload,
)
from all_ontology.server.chat.settings_dal import fetch_acronyms, fetch_custom_prompts

logger = logging.getLogger(__name__)

# Retrieval runs share retriever/connector state and a single LLM budget and are
# not safe to run in parallel; serialize like the chat pool's single slot.
_run_lock = threading.Lock()


class PredictionFlowError(RuntimeError):
    """The prediction flow could not produce a result for the question."""


def _build_coverage_payload(
    question: str,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    allowed_table_ids: list[str] | None = None,
) -> EntityCoveragePayload:
    """Assemble the payload for the entity-coverage pipeline."""
    from all_ontology.connectors.registry import get_connectors
    from all_ontology.utils.retriever import (
        get_data_objects_retriever,
        get_semantic_objects_retriever,
    )

    connectors = get_connectors()
    if not connectors:
        raise PredictionFlowError("No database connection is configured.")
    custom_prompts = fetch_custom_prompts()
    return {
        "question": question,
        "data_retriever": get_data_objects_retriever(),
        "semantic_retriever": get_semantic_objects_retriever(),
        "connectors": connectors,
        "acronyms": fetch_acronyms(),
        "custom_prompts": custom_prompts,
        "max_distance": max_distance,
        "allowed_table_ids": allowed_table_ids,
    }


def entity_coverage(
    question: str,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    allowed_table_ids: list[str] | None = None,
) -> dict:
    """Return ranked semantic candidates and a 0–1 entity coverage grade.

    Raises :class:`PredictionFlowError` when the flow cannot produce a result.
    """
    from all_ontology.retrieval.entity_coverage.main import (
        coverage_llm_client,
        get_coverage_response,
    )

    if coverage_llm_client() is None:
        raise PredictionFlowError("LLM client is not configured.")
    with _run_lock:
        try:
            return get_coverage_response(
                _build_coverage_payload(
                    question,
                    max_distance=max_distance,
                    allowed_table_ids=allowed_table_ids,
                )
            )
        except (ValueError, RuntimeError) as exc:
            raise PredictionFlowError(str(exc)) from exc
