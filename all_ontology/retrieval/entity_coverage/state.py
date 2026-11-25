# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Payload type for the entity-coverage pipeline.

Reuses ``AgentState`` and question helpers from text-to-sql.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

# Annotations only: a caller that needs DEFAULT_MAX_DISTANCE must not pay for
# the retriever/embedding stack the type names come from.
if TYPE_CHECKING:
    from all_ontology.connectors.base import SQLDatabase
    from all_ontology.utils.retriever import Retriever

DEFAULT_MAX_DISTANCE = 0.75


class EntityCoveragePayload(TypedDict):
    """Payload for the entity-coverage agent flow."""

    question: str
    data_retriever: "Retriever"
    semantic_retriever: NotRequired["Retriever"]
    path_state: NotRequired[dict]
    connectors: NotRequired[list["SQLDatabase"]]
    acronyms: NotRequired[list[dict[str, str]]]
    custom_prompts: NotRequired[str]
    target_db: NotRequired[str]
    max_distance: NotRequired[float]
    return_uncovered_entities: NotRequired[bool]
    allowed_table_ids: NotRequired[list[str] | None]


__all__ = [
    "DEFAULT_MAX_DISTANCE",
    "EntityCoveragePayload",
]
