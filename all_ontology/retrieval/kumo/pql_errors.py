# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Classify KumoRFM predict/explain errors and decide what is worth retrying."""

from __future__ import annotations


# Markers for a transient infra/server hiccup (not a problem with the query). The PQL has already passed
# validate_pql, so retrying the SAME query is right (e.g. the DuckDB mirror "closed pending query result"
# race clears on retry, and KumoRFM 5xx/timeouts are transient).
_TRANSIENT_EXEC_MARKERS = (
    "closed pending query result",
    "internal server error",
    "an unexpected exception occurred",
    "model inference fail",
    "service unavailable",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "502",
    "503",
    "504",
    "429",
)

# Markers for a KumoRFM context/GPU-capacity failure (a wide graph like gpu_fleet lands ~27MB of context,
# right at the SDK's 30MB ceiling). The GPU errors (CUDA "illegal memory access" / OOM) are INTERMITTENT —
# the same full-neighbourhood request that fails one moment can succeed on retry — so they are retried at
# FULL accuracy first (see _predict_resilient). The "context size exceeds" rejection is the exception: it is
# DETERMINISTIC (same query -> same oversize context), so it steps straight down to a smaller neighbourhood
# rather than re-hitting the same wall 3 times (see _retry_at_full_neighbourhood). Shrinking the
# neighbourhood is the last resort to salvage *a* prediction when full settings cannot complete.
#
# The SDK's per-table row cap ("... contains 32,000 rows, exceeding the 10,000-row limit",
# kumo_relational_engine.rfm.payload.MAX_TABLE_ROWS) is the same kind of DETERMINISTIC rejection: it is raised
# client-side while serializing the request, before anything is sent, and the row count is a direct
# product of the neighbourhood (FAST samples 1,000 context anchors x 32 first-hop neighbours = 32,000
# rows in one related table), so only a smaller neighbourhood clears it. Without this marker the
# rejection escapes _predict_resilient into the regenerate loop, which burns the whole PQL repair
# budget rewriting a query that was never the problem.
_CONTEXT_CAPACITY_MARKERS = (
    "cuda",
    "illegal memory access",
    "out of memory",
    "context size exceeds",
    "-row limit",
)

# A parse error at PREDICT time is spurious: the query already passed validate_pql (the cheap parse) moments
# earlier, so a parse failure during predict is the KumoRFM server in a degraded state (observed right after a
# transient 5xx, alongside gRPC GOAWAY). Retry the SAME call rather than discard a known-valid query — link
# prediction in particular recovers within a couple of retries once the server settles.
_SPURIOUS_PREDICT_PARSE_MARKERS = (
    "failed to parse query",
    "could not process the text",
)

_EMPTY_CONTEXT_MARKERS = (
    "failed to collect any context examples",
    "too restrictive",
)


def _is_transient_exec_error(message: str) -> bool:
    """True if a predict error is a transient infra/server hiccup."""
    return any(marker in message.lower() for marker in _TRANSIENT_EXEC_MARKERS)


def _is_context_capacity_error(message: str) -> bool:
    """True if a predict error is a KumoRFM context/GPU-capacity failure."""
    return any(marker in message.lower() for marker in _CONTEXT_CAPACITY_MARKERS)


def _is_context_size_limit_error(message: str) -> bool:
    """True for the DETERMINISTIC context-too-big rejections: the total 'context size exceeds the limit'
    and the SDK's per-table '...-row limit'. In both the SDK builds the context, measures it, and rejects it
    for being over a ceiling, so the identical query yields the identical oversize context every time —
    retrying the same neighbourhood cannot help, only a smaller one can."""
    lowered = message.lower()
    return "context size exceeds" in lowered or "-row limit" in lowered


# Markers for a TERMINAL backend failure: the generated *shape* is not serveable for this dataset, so neither
# retrying the same call nor regenerating a similar query will help. Unlike the (intermittent) capacity errors
# above, these are deterministic, so we fail fast with a clear message instead of burning the repair budget
# and the neighbourhood backoff re-hitting the same wall.
#   * "device-side assert" — a deterministic KumoRFM CUDA assertion hit by degenerate parent→immediate-child
#     existence targets (e.g. COUNT(order_lines.*) FOR EACH sales_orders); stepping the neighbourhood down
#     does not help (it is the data/shape, not the context size).
# NOTE: link-prediction's "Unsupported cast from list<item: string> to utf8" is NOT here — it is fixed at the
# source by the LIST_DISTINCT string-dtype compatibility shim in kumo_client, so recommendations now run.
_UNSUPPORTED_SHAPE_MARKERS = ("device-side assert",)


def _is_unsupported_shape_error(message: str) -> bool:
    """True if a predict error is a deterministic, unrecoverable 'this shape is not serveable' failure."""
    return any(marker in message.lower() for marker in _UNSUPPORTED_SHAPE_MARKERS)


def _is_empty_context_error(message: str) -> bool:
    """True if a predict/explain error is an empty entity set (WHERE matched no learnable entity)."""
    return any(marker in message.lower() for marker in _EMPTY_CONTEXT_MARKERS)


def _friendly_empty_context_message() -> str:
    """A user-facing explanation for an empty-entity-set failure, with the concrete next step."""
    return (
        "KumoRFM found no entity matching the prediction's filter, so it could not gather any context "
        "examples. The WHERE clause likely references an id that does not exist (or a placeholder). Pass a "
        "real entity id taken from a prediction ranking or an rfm__sql_query result, not a placeholder."
    )


def _friendly_backend_unavailable_message() -> str:
    """User-facing explanation for a KumoRFM backend failure on a query that is itself valid."""
    return (
        "The KumoRFM prediction service returned an internal error, so the prediction could "
        "not be computed. The query itself was accepted and validated — this is a backend "
        "fault, not a problem with the question. Please retry; if it persists, the KumoRFM "
        "deployment (KUMO_RFM_API_URL) needs attention."
    )


def _is_spurious_predict_parse_error(message: str) -> bool:
    """True if a PREDICT-time parse error is the spurious kind (the query already passed validate_pql)."""
    return any(marker in message.lower() for marker in _SPURIOUS_PREDICT_PARSE_MARKERS)


def _friendly_unsupported_message(pql: str, raw_error: str) -> str:
    """A user-facing explanation (no raw backend stack text) for a terminal unsupported-shape failure, with a
    concrete next step the agent can take."""
    return (
        "KumoRFM could not compute this prediction shape for this dataset — the parent→child relationship "
        "is not learnable as a generic existence/count prediction. Predict a specific outcome instead "
        "(e.g. a late/slip status with a WHERE filter on the event table), or use rfm__sql_query for a "
        "historical count."
    )


def _is_retryable_exec_error(message: str) -> bool:
    """True if a predict error is worth retrying the SAME call: transient infra hiccups, the (intermittent)
    capacity errors, AND a spurious post-validate parse error (server degradation). Retrying capacity errors at
    the FULL neighbourhood is what preserves accuracy — we never reduce the model's context unless full settings
    persistently fail. A terminal unsupported-shape error is never retried (it is deterministic), even if it
    mentions CUDA."""
    if _is_unsupported_shape_error(message):
        return False
    return (
        _is_transient_exec_error(message)
        or _is_context_capacity_error(message)
        or _is_spurious_predict_parse_error(message)
    )


def _retry_at_full_neighbourhood(message: str) -> bool:
    """Which errors to retry at the FULL neighbourhood before stepping down. Same as the general retry rule
    but EXCLUDES the deterministic context-size-limit rejection: retrying the identical query at the same
    neighbourhood just re-hits the same oversize context, so step straight down to a smaller one. Transient
    infra/GPU (CUDA/OOM) and spurious post-validate parse errors are still retried at full to keep accuracy."""
    return _is_retryable_exec_error(message) and not _is_context_size_limit_error(
        message
    )
