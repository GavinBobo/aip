# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resilient KumoRFM execution: retries, neighbourhood backoff, and batching."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from all_ontology.retrieval.kumo.pql_errors import (
    _is_context_capacity_error,
    _is_context_size_limit_error,
    _is_empty_context_error,
    _is_retryable_exec_error,
    _is_transient_exec_error,
    _is_unsupported_shape_error,
    _retry_at_full_neighbourhood,
)

logger = logging.getLogger(__name__)


_REFLECTION_FUNCTION_NAME = "__reflection__"


def _emit_retry_note(text: str) -> None:
    """Surface a tool-internal retry as a collapsible trace note on the running predict node, via NAT's
    intermediate-step pipeline, so the UI shows that an attempt failed and is being retried rather than an
    endless spinner. No-op without an active NAT context (CLI / tests); never raises into the predict path."""
    try:
        import uuid

        from nat.builder.context import Context
        from nat.data_models.intermediate_step import IntermediateStepPayload
        from nat.data_models.intermediate_step import IntermediateStepType
        from nat.data_models.intermediate_step import StreamEventData

        manager = getattr(Context.get(), "intermediate_step_manager", None)
        if manager is None:
            return
        step_id = str(uuid.uuid4())
        # Unique step name so each note stays its own trace step (folded under the running predict),
        # matching the side-channel note convention instead of merging into one.
        name = f"{_REFLECTION_FUNCTION_NAME}:{step_id[:8]}"
        manager.push_intermediate_step(
            IntermediateStepPayload(
                UUID=step_id,
                event_type=IntermediateStepType.FUNCTION_START,
                name=name,
                data=StreamEventData(input=name),
            )
        )
        manager.push_intermediate_step(
            IntermediateStepPayload(
                UUID=step_id,
                event_type=IntermediateStepType.FUNCTION_END,
                name=name,
                data=StreamEventData(input=name, output=text),
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("retry trace note failed", exc_info=True)


def _predict_with_retry(
    call: Callable[[], Any],
    *,
    retries: int,
    backoff: float = 1.5,
    retryable: Callable[[str], bool] = _is_retryable_exec_error,
) -> Any:
    """Run *call* (a no-arg predict), retrying the SAME query while *retryable* matches the error.

    Used only after ``validate_pql`` has passed, so a failure here is an execution error — a transient or
    intermittent-capacity one is retried as-is rather than discarding a valid query. ``retryable`` selects
    which errors to retry (default: transient + capacity); callers that want to react to capacity errors
    differently (e.g. explain, which steps down hops) pass a narrower predicate.
    """
    last_exc: Exception | None = None
    for i in range(retries + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - classified by message; re-raised below
            last_exc = exc
            if i == retries or not retryable(str(exc)):
                raise
            logger.info(
                "Predict error (retry %d/%d, same query): %s",
                i + 1,
                retries,
                str(exc)[:160],
            )
            if i == 0:
                _emit_retry_note(
                    "A prediction attempt failed (transient model or capacity error). Retrying."
                )
            time.sleep(backoff * (i + 1))
    raise last_exc  # pragma: no cover - loop always returns or raises


# How hard to retry at the FULL (accuracy-preserving) neighbourhood before stepping down. One retry rides
# through a single transient KumoRFM hiccup (a 5xx is often followed by a spurious parse error before it
# settles); beyond that, dropping to a smaller context escapes a persistent GPU/capacity fault faster than
# repeating the same heavy request. Tier 1 is therefore 2 attempts.
_FULL_NEIGHBORHOOD_RETRIES = 1

# Entity ceiling for a grouped prediction: high enough to score whole dimension populations (customers,
# products, suppliers) so per-group totals are complete, but bounded so a grouping over a huge event entity
# (e.g. every sales_order) can't explode — past this the totals are flagged partial.
_GROUP_BY_MAX_ENTITIES = 10_000

_PREDICT_BATCH_SIZE = 1000

# Last-resort fallbacks if the full neighbourhood persistently hits a capacity error. None = the SDK default
# for the run mode (full accuracy). The fallbacks step DOWN gradually (the SDK FAST default is [32, 32]) so
# we keep as much of the model's receptive field as possible while still fitting under the GPU ceiling; the
# final [8, 8] (~1-2MB context) is the smallest field worth salvaging a result with when larger ones fault.
_CONTEXT_BACKOFF_NEIGHBORS: tuple[list[int] | None, ...] = (
    None,
    [24, 24],
    [16, 16],
    [8, 8],
)


class _NeighbourhoodMemo:
    """Remembers ladder rungs already proven too big for the graph in THIS run.

    The SDK's size rejections (total context size and the per-table row cap) are
    DETERMINISTIC given the graph and the neighbourhood, and the row count is driven by
    anchors x neighbours rather than by the query text — so a rung that overflowed on one
    PQL attempt overflows on the next one too. Without this memo every regenerate attempt
    re-walks the ladder from full and re-pays the identical rejected serializations
    (observed: 3 wasted rejections per attempt across 5 attempts on a 3.7M-row table).

    Only the deterministic size errors raise the floor. Intermittent CUDA/OOM faults must
    NOT — the same full-neighbourhood request often succeeds on retry, and the design is
    accuracy-first, so those keep starting from the top.
    """

    __slots__ = ("floor",)

    def __init__(self) -> None:
        self.floor = 0

    def note_too_big(self, index: int) -> None:
        self.floor = max(self.floor, index + 1)


def _predict_resilient(
    predict_fn: Callable[[list[int] | None], Any],
    *,
    device_assert_terminal: bool = True,
    memo: "_NeighbourhoodMemo | None" = None,
) -> Any:
    """Run ``predict_fn(num_neighbors)`` accuracy-first.

    Predict at the FULL neighbourhood and retry it hard on intermittent infra/GPU errors — the same
    full-accuracy request usually succeeds on retry, so we never silently trade accuracy for a smaller
    context. ONLY if the full neighbourhood keeps hitting a context/GPU-capacity error after those retries
    do we step down to a smaller neighbourhood, purely to salvage *a* correct prediction rather than fail.
    Non-capacity errors propagate (to the regenerate loop).

    A CUDA ``device-side assert`` is deterministic ONLY for the degenerate existence-count shape
    (``device_assert_terminal=True`` → propagate immediately); for any other shape it is an INTERMITTENT
    fault (large-batch predicts hit it ~1-in-5), so it is retried and stepped down like a capacity error.
    """

    def _retryable(message: str) -> bool:
        if _is_unsupported_shape_error(message):
            return not device_assert_terminal
        return _retry_at_full_neighbourhood(message)

    last_exc: Exception | None = None
    # Skip rungs a previous attempt in this run already proved too big (see _NeighbourhoodMemo).
    # Never skip the whole ladder: the last rung is always tried, so a wrong memo costs accuracy
    # rather than the result.
    start = min(memo.floor, len(_CONTEXT_BACKOFF_NEIGHBORS) - 1) if memo else 0
    if start:
        logger.info(
            "Starting at neighbourhood %s — larger ones already overflowed this run.",
            _CONTEXT_BACKOFF_NEIGHBORS[start],
        )
    for index in range(start, len(_CONTEXT_BACKOFF_NEIGHBORS)):
        num_neighbors = _CONTEXT_BACKOFF_NEIGHBORS[index]
        # Retry hard at the FIRST rung actually used, not merely at the full one: when the memo
        # starts the ladder lower, that rung is now the accuracy-preserving choice and deserves
        # the same protection against a single transient hiccup.
        retries = _FULL_NEIGHBORHOOD_RETRIES if index == start else 0
        try:
            return _predict_with_retry(
                lambda nn=num_neighbors: predict_fn(nn),
                retries=retries,
                retryable=_retryable,
            )
        except Exception as exc:  # noqa: BLE001 - classified by message; re-raised below
            last_exc = exc
            assert_err = _is_unsupported_shape_error(str(exc))
            if assert_err and device_assert_terminal:
                raise
            if not (assert_err or _is_context_capacity_error(str(exc))):
                raise
            if memo is not None and _is_context_size_limit_error(str(exc)):
                memo.note_too_big(index)
            if num_neighbors is None:
                logger.warning(
                    "Full neighbourhood hit a KumoRFM capacity/assert error; falling back to a smaller "
                    "neighbourhood to salvage a prediction (reduced context). Error: %s",
                    str(exc)[:160],
                )
                _emit_retry_note(
                    "The prediction kept failing at full context. Retrying with a smaller context window to "
                    "recover a result."
                )
            else:
                logger.info(
                    "Capacity/assert error at neighbourhood %s; shrinking further.",
                    num_neighbors,
                )
                _emit_retry_note(
                    f"Still over capacity at neighbourhood {num_neighbors}. Shrinking the context further and retrying."
                )
    raise last_exc  # pragma: no cover - loop always returns or raises


def _predict_in_batches(
    indices: list[Any] | None,
    predict_call: Callable[[list[Any] | None, list[int] | None], Any],
    *,
    device_assert_terminal: bool = True,
    memo: "_NeighbourhoodMemo | None" = None,
) -> Any:
    """Run the resilient predict over ``indices`` in ordered chunks of at most ``_PREDICT_BATCH_SIZE``.

    The KumoRFM server raises a CUDA device-side assert on a single very large per-entity batch, so a
    whole-population prediction (thousands of entities) is split into chunks that each stay under the
    server's ceiling and the per-chunk frames are concatenated. A small scope (or ``None`` for a single
    entity / the SDK default) runs in one call. Each chunk goes through :func:`_predict_resilient`
    independently; since each entity's prediction depends only on its own subgraph, the concatenated result
    is equivalent to scoring the whole scope at once.
    """
    if not indices or len(indices) <= _PREDICT_BATCH_SIZE:
        return _predict_resilient(
            lambda nn: predict_call(indices, nn),
            device_assert_terminal=device_assert_terminal,
            memo=memo,
        )
    import pandas as pd

    frames = []
    for start in range(0, len(indices), _PREDICT_BATCH_SIZE):
        chunk = indices[start : start + _PREDICT_BATCH_SIZE]
        frames.append(
            _predict_resilient(
                lambda nn, c=chunk: predict_call(c, nn),
                device_assert_terminal=device_assert_terminal,
                memo=memo,
            )
        )
    return pd.concat(frames, ignore_index=True)


_EXPLAIN_BACKOFF_NEIGHBORS: tuple[list[int] | None, ...] = (None, [16], [8])


def _explain_resilient(explain_fn: Callable[[list[int] | None], Any]) -> Any:
    """Run ``explain_fn(num_neighbors)`` for one entity, accuracy-first: retry hard at the FULL neighbourhood
    before stepping the depth DOWN to salvage the call.

    Stepping down is not free for an explanation the way it is for a plain prediction: a shallow neighbourhood
    starves the gradient attribution and the per-cell scores collapse to zero, so the "top drivers" — the
    whole point of explain — silently vanish. KumoRFM's intermittent CUDA ``device-side assert`` fires in
    bursts (the same query that fails one moment succeeds the next), so we ride those out at full depth
    (``_FULL_NEIGHBORHOOD_RETRIES``) and only shrink as a last resort. First success wins; an empty entity set
    (bad/placeholder id) is terminal — a shallower neighbourhood cannot populate an empty filter.
    """
    last_exc: Exception | None = None
    for num_neighbors in _EXPLAIN_BACKOFF_NEIGHBORS:
        retries = _FULL_NEIGHBORHOOD_RETRIES if num_neighbors is None else 1
        try:
            return _predict_with_retry(
                lambda nn=num_neighbors: explain_fn(nn),
                retries=retries,
                retryable=_is_transient_exec_error,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _is_empty_context_error(str(exc)):
                logger.info(
                    "Explain hit an empty entity set (bad/placeholder id); not stepping the "
                    "neighbourhood down (it cannot help an empty filter)."
                )
                raise
            logger.info(
                "Explain failed at neighbourhood %s (%s); trying a shallower one.",
                num_neighbors or "default",
                str(exc)[:140],
            )
    raise last_exc  # pragma: no cover
