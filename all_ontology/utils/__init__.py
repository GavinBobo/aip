# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared utilities used across server, ingestion, and dev tools.

Names are resolved on first access rather than imported here. Many callers need
only ``sample_values`` (a JSON helper), and importing that submodule used to
execute this package's ``__init__`` first, which pulled in the embedding client
and pandas for every caller. ``__getattr__`` keeps the public API while loading
only the module behind the name actually requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "get_embed_params",
    "get_data_objects_retriever",
    "get_semantic_objects_retriever",
    "sample_values_edit_error",
    "sample_values_editable",
    "dump_sample_values",
    "parse_sample_values",
    "render_sample_value",
    "stringify_sample_values",
]

_LAZY: dict[str, tuple[str, str]] = {
    "sample_values_edit_error": (
        "all_ontology.utils.column_types",
        "sample_values_edit_error",
    ),
    "sample_values_editable": (
        "all_ontology.utils.column_types",
        "sample_values_editable",
    ),
    "get_embed_params": ("all_ontology.utils.embedding", "get_embed_params"),
    "get_data_objects_retriever": (
        "all_ontology.utils.retriever",
        "get_data_objects_retriever",
    ),
    "get_semantic_objects_retriever": (
        "all_ontology.utils.retriever",
        "get_semantic_objects_retriever",
    ),
    "dump_sample_values": (
        "all_ontology.utils.sample_values",
        "dump_sample_values",
    ),
    "parse_sample_values": (
        "all_ontology.utils.sample_values",
        "parse_sample_values",
    ),
    "render_sample_value": (
        "all_ontology.utils.sample_values",
        "render_sample_value",
    ),
    "stringify_sample_values": (
        "all_ontology.utils.sample_values",
        "stringify_sample_values",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
