# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Progress and cancellation primitives shared by the pipeline and worker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from all_ontology.parsing.pipeline.errors import ParsingCancelledError


@dataclass(frozen=True)
class ParsingProgress:
    """One update from a running pipeline.

    ``total`` is in the stage's own unit: pages for decode/layout, blocks for
    recognize, and 1 for assemble. The worker turns that into a durable
    percentage; the browser shows the stage name and the unit.
    """

    stage: str
    done: int
    total: int
    page: int | None = None


ProgressCallback = Callable[[ParsingProgress], Awaitable[None]]


async def notify(
    callback: ProgressCallback | None,
    stage: str,
    done: int,
    total: int,
    *,
    page: int | None = None,
) -> None:
    if callback is not None:
        await callback(
            ParsingProgress(
                stage=stage, done=max(0, done), total=max(0, total), page=page
            )
        )


def raise_if_cancelled(event: asyncio.Event | None) -> None:
    if event is not None and event.is_set():
        raise ParsingCancelledError("任务已取消")
