# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Background worker for queued parsing documents.

The HTTP side only writes a durable row and returns. This loop claims rows with
``FOR UPDATE SKIP LOCKED``, runs the existing pipeline, and writes progress,
result paths, and the model/option snapshot back to Postgres. It starts inside
the API process by default; the same class can be run from a dedicated process
without changing the code path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from all_ontology.parsing import service
from all_ontology.parsing import settings as parsing_settings
from all_ontology.parsing import store
from all_ontology.parsing.pipeline.errors import ParsingCancelledError
from all_ontology.parsing.pipeline.progress import ParsingProgress
from all_ontology.version import get_app_version

logger = logging.getLogger(__name__)


def _snapshot(described: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    model = {
        "mode": described.get("mode"),
        "model_url": described.get("model_url"),
        "model_name": (described.get("status") or {}).get("model_name"),
        "vllm_model": (described.get("vllm") or {}).get("model_name"),
    }
    layout = {
        "url": described.get("layout_url"),
        **(described.get("layout") or {}),
    }
    return model, layout


class ParsingWorker:
    """One or more claim/process loops sharing a process-wide identity."""

    def __init__(self, concurrency: int | None = None) -> None:
        self.concurrency = max(
            1,
            int(
                concurrency
                if concurrency is not None
                else os.environ.get("PARSING_WORKER_CONCURRENCY", "1")
            ),
        )
        self.worker_id = f"{os.environ.get('HOSTNAME', 'local')}:{os.getpid()}"
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        await asyncio.to_thread(store.recover_stale)
        self._tasks = [
            asyncio.create_task(self._loop(index), name=f"parsing-worker-{index}")
            for index in range(self.concurrency)
        ]
        logger.info(
            "Parsing worker started (id=%s, concurrency=%s)",
            self.worker_id,
            self.concurrency,
        )

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _loop(self, index: int) -> None:
        while not self._stop.is_set():
            try:
                document = await asyncio.to_thread(
                    store.claim_next_document, self.worker_id
                )
            except Exception:
                logger.exception("Parsing worker could not claim a document")
                await asyncio.sleep(2)
                continue
            if document is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self._process(document)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Parsing worker failed outside the pipeline (document=%s)",
                    document.get("id"),
                )
                await asyncio.to_thread(
                    store.finish_run_failure,
                    run_id="",
                    task_id=document["task_id"],
                    document_id=document["id"],
                    error_code="INTERNAL_ERROR",
                    error_message="解析进程异常，请重试",
                )

    async def _process(self, document: dict[str, Any]) -> None:
        task_id = document["task_id"]
        document_id = document["id"]
        task = await asyncio.to_thread(store.get_task, task_id)
        if task is None or task["status"] == "cancelled":
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id="",
                task_id=task_id,
                document_id=document_id,
                error_code="CANCELLED",
                error_message="任务已取消",
                cancelled=True,
            )
            return

        profile = await asyncio.to_thread(store.resolve_profile, task["profile"])
        options = task.get("options") or {}
        parsed_options, errors = service.build_options(
            options.get("output_formats"),
            json.dumps({"keep_header_footer": bool(options.get("keep_header_footer"))}),
            json.dumps(options.get("model_options") or {}),
            json.dumps(options.get("element_formats") or {}),
        )
        if parsed_options is None:
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id="",
                task_id=task_id,
                document_id=document_id,
                error_code="INVALID_OPTIONS",
                error_message="；".join(errors),
            )
            return

        instance_id = document.get("instance_id")
        if not instance_id:
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id="",
                task_id=task_id,
                document_id=document_id,
                error_code="SOURCE_MISSING",
                error_message="找不到该文件的源文件",
            )
            return
        instance = await asyncio.to_thread(service.instance_from_id, instance_id)
        if not instance.source.is_file():
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id="",
                task_id=task_id,
                document_id=document_id,
                error_code="SOURCE_MISSING",
                error_message="源文件已被移动或删除",
            )
            return

        described = await parsing_settings.status()
        model_snapshot, layout_snapshot = _snapshot(described)
        pipeline_version = get_app_version()
        profile_options = profile.get("options") or {}
        merged = {**profile_options, **options}
        dpi = int(merged.get("dpi") or 150)
        page_start = document.get("page_start")
        page_end = document.get("page_end")
        if page_start is None and page_end is None:
            max_pages = merged.get("max_pages")
            if max_pages:
                page_start, page_end = 1, int(max_pages)
        page_range = (
            (int(page_start), int(page_end))
            if page_start is not None and page_end is not None
            else None
        )

        run = await asyncio.to_thread(
            store.create_run,
            task_id=task_id,
            document_id=document_id,
            attempt=int(document.get("attempt") or 1),
            profile=task["profile"],
            options={**options, "dpi": dpi, "page_range": page_range},
            model_snapshot=model_snapshot,
            layout_snapshot=layout_snapshot,
            pipeline_version=pipeline_version,
            instance_id=instance.id,
            result_path=str(instance.result_path),
            blocks_path=str(instance.directory / "blocks.json"),
        )
        run_id = run["id"]
        cancel_event = asyncio.Event()
        finished = asyncio.Event()
        progress_state: dict[str, Any] = {"at": 0.0, "last": None}

        async def on_progress(progress: ParsingProgress) -> None:
            # A block-level update for every block would be a write per model
            # call. Keep the first, terminal, and at most one update per 700 ms.
            now = time.monotonic()
            terminal = progress.total > 0 and progress.done >= progress.total
            if not terminal and now - progress_state["at"] < 0.7:
                return
            progress_state["at"] = now
            await asyncio.to_thread(
                store.update_progress,
                run_id,
                document_id,
                progress.stage,
                progress.done,
                progress.total,
            )

        async def watch_cancel() -> None:
            while not finished.is_set():
                status = await asyncio.to_thread(store.get_task_status, task_id)
                if status == "cancelled":
                    cancel_event.set()
                    return
                try:
                    await asyncio.wait_for(finished.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

        watcher = asyncio.create_task(watch_cancel())
        try:
            result = await service.parse_now(
                await asyncio.to_thread(instance.source.read_bytes),
                document["file_name"],
                parsed_options,
                instance,
                dpi=dpi,
                page_range=page_range,
                progress_cb=on_progress,
                cancel_event=cancel_event,
                extra_metadata={
                    "run_id": run_id,
                    "task_id": task_id,
                    "profile": task["profile"],
                    "model_snapshot": model_snapshot,
                    "layout_snapshot": layout_snapshot,
                    "pipeline_version": pipeline_version,
                    "dpi": dpi,
                    "page_range": page_range,
                },
            )
            metadata = result.get("metadata") or {}
            await asyncio.to_thread(
                store.finish_run_success,
                run_id=run_id,
                task_id=task_id,
                document_id=document_id,
                page_count=int(metadata.get("page_num") or 0),
                quality=metadata.get("quality") or {},
                processing_time_ms=metadata.get("processing_time_ms"),
            )
        except (ParsingCancelledError, asyncio.CancelledError):
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id=run_id,
                task_id=task_id,
                document_id=document_id,
                error_code="CANCELLED",
                error_message="任务已取消",
                cancelled=True,
            )
        except Exception as error:  # noqa: BLE001 - the run row is the reporter
            code = service.error_code_for(error)
            message = (
                str(getattr(error, "detail", "")) or str(error) or "解析失败，请重试"
            )
            logger.warning(
                "Parsing failed (run=%s, document=%s, code=%s)",
                run_id,
                document_id,
                code,
                exc_info=code
                not in {
                    "BACKEND_UNAVAILABLE",
                    "INVALID_DOCUMENT",
                    "INVALID_OPTIONS",
                    "TIMEOUT",
                },
            )
            await asyncio.to_thread(
                store.finish_run_failure,
                run_id=run_id,
                task_id=task_id,
                document_id=document_id,
                error_code=code,
                error_message=message,
            )
        finally:
            finished.set()
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


_worker: ParsingWorker | None = None
_worker_lock = asyncio.Lock()


async def start_worker() -> ParsingWorker | None:
    global _worker
    if os.environ.get("PARSING_WORKER_ENABLED", "true").lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    async with _worker_lock:
        if _worker is None:
            _worker = ParsingWorker()
            await _worker.start()
        return _worker


async def stop_worker() -> None:
    global _worker
    async with _worker_lock:
        if _worker is not None:
            await _worker.stop()
            _worker = None


def main() -> None:
    """Run only the parsing worker (useful when the API should not execute jobs)."""
    from all_ontology.env import load_env

    load_env()

    async def run_forever() -> None:
        await start_worker()
        await asyncio.Event().wait()

    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
