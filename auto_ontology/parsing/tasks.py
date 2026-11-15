# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""In-process store for asynchronous parse jobs.

Ported from OXR's ``oxr/server/queue/memory_store.py`` with one addition: every
payload records the process that owns it.

**This store does not survive a restart and is not shared between replicas.**
That is the same trade-off OXR makes, and it is acceptable here because a parse
job is short-lived and the browser polls the same backend that accepted it. The
moment that stops being true — several API pods behind one Service, or jobs that
must outlive a deploy — this has to become a table. ``instance`` exists so the
query endpoint can say "that job belonged to another process" instead of
silently 404-ing.
"""

from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

#: Identifies the process that owns a job. Pod name in Kubernetes, host name
#: locally; nothing depends on its exact value beyond equality.
INSTANCE_ID = os.environ.get("HOSTNAME") or socket.gethostname()


def _build_task_payload(task_id: str, file_name: str | None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "instance": INSTANCE_ID,
        "status": "queuing",
        "file_name": file_name,
        "result": None,
        "error": None,
        "metadata": {},
    }


class MemoryTaskStore:
    """A tiny asyncio-guarded dict of task payloads."""

    def __init__(self, max_jobs: int = 200) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_jobs = max(1, int(max_jobs))

    async def create(self, task_id: str, file_name: str | None = None) -> None:
        async with self._lock:
            # Nothing calls ``forget`` in normal use, so a finished job would
            # otherwise hold its parsed outputs for the lifetime of the process.
            # Drop the oldest *finished* entries first; a queued or running job
            # is never evicted just to make room.
            while len(self._store) >= self._max_jobs:
                finished = next(
                    (
                        key
                        for key, payload in self._store.items()
                        if payload["status"] in {"success", "failed"}
                    ),
                    None,
                )
                if finished is None:
                    break
                del self._store[finished]
            self._store[task_id] = _build_task_payload(task_id, file_name)

    async def set_processing(self, task_id: str) -> None:
        async with self._lock:
            if task_id in self._store:
                self._store[task_id]["status"] = "processing"

    async def set_success(self, task_id: str, result: dict[str, Any]) -> None:
        async with self._lock:
            if task_id in self._store:
                self._store[task_id].update(
                    status="success",
                    file_name=result.get("file_name")
                    or self._store[task_id].get("file_name"),
                    result=result.get("result"),
                    metadata=result.get("metadata", {}),
                    error=None,
                )

    async def set_failed(self, task_id: str, error: str) -> None:
        async with self._lock:
            if task_id in self._store:
                self._store[task_id].update(status="failed", error=error)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            payload = self._store.get(task_id)
            return dict(payload) if payload is not None else None

    async def forget(self, task_id: str) -> None:
        async with self._lock:
            self._store.pop(task_id, None)


#: Process-wide store; the router and the background runner share it.
task_store = MemoryTaskStore()
