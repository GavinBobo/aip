# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Durable index for parsing tasks, runs, and block edits.

The parser writes the expensive artifacts (source, page JSON, Markdown, JSON,
images) to the filesystem. This module owns the small, queryable state that
makes those artifacts usable: what was submitted, which worker owns it, how far
it got, where its result lives, and what a reviewer changed.

Only the API/worker use this layer. The pipeline itself stays free of database
imports, so its unit tests still run without Postgres.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from all_ontology.dal.session import store, write_transaction

TERMINAL_DOCUMENT_STATUSES = {"succeeded", "failed", "cancelled"}

#: Presets are intentionally small and product-facing. A profile is a named
#: bundle of pipeline knobs, not a second model configuration page.
DEFAULT_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "name": "fast",
        "description": "快速预览：更低 DPI、优先使用 PDF 文本层，适合先看结构",
        "options": {
            "dpi": 110,
            "max_pages": 20,
            "prefer_text_layer": True,
            "layout_batch_size": 16,
            "recognition_retries": 1,
        },
    },
    {
        "name": "standard",
        "description": "标准：兼顾速度与准确率，适合日常文档",
        "options": {
            "dpi": 150,
            "max_pages": 500,
            "prefer_text_layer": True,
            "layout_batch_size": 8,
            "recognition_retries": 2,
        },
    },
    {
        "name": "accurate",
        "description": "高精度：更高 DPI、更多重试，适合扫描件与复杂表格",
        "options": {
            "dpi": 200,
            "max_pages": 500,
            "prefer_text_layer": False,
            "layout_batch_size": 4,
            "recognition_retries": 4,
        },
    },
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("options", "model_snapshot", "layout_snapshot", "quality"):
        if key in out:
            out[key] = _loads(out[key], {})
    return out


def ensure_profiles() -> None:
    """Insert the three built-in profiles once; never overwrite an edit."""
    with write_transaction():
        for index, profile in enumerate(DEFAULT_PROFILES):
            store().query_write(
                text(
                    """
                    INSERT INTO parsing_profile (id, name, description, options, is_default)
                    VALUES (:id, :name, :description, CAST(:options AS jsonb), :is_default)
                    ON CONFLICT (name) DO NOTHING
                    """
                ),
                {
                    "id": _new_id(),
                    "name": profile["name"],
                    "description": profile["description"],
                    "options": _json(profile["options"]),
                    "is_default": profile["name"] == "standard",
                },
            )


def list_profiles() -> list[dict[str, Any]]:
    ensure_profiles()
    rows = store().query_read(
        text(
            "SELECT id, name, description, options, is_default "
            "FROM parsing_profile ORDER BY is_default DESC, name"
        )
    )
    return [
        {
            **{key: value for key, value in row.items() if key != "options"},
            "options": _loads(row.get("options"), {}),
        }
        for row in rows
    ]


def resolve_profile(name: str) -> dict[str, Any]:
    for profile in list_profiles():
        if profile["name"] == name:
            return profile
    return next(profile for profile in list_profiles() if profile["name"] == "standard")


def create_task(
    *,
    name: str,
    created_by: str | None,
    profile: str,
    options: dict[str, Any],
    documents: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Create a task and its queued documents in one transaction."""
    task_id = _new_id()
    docs = list(documents)
    with write_transaction():
        store().query_write(
            text(
                """
                INSERT INTO parsing_task
                    (id, name, created_by, status, profile, options, total_documents)
                VALUES
                    (:id, :name, :created_by, 'queued', :profile,
                     CAST(:options AS jsonb), :total)
                """
            ),
            {
                "id": task_id,
                "name": name,
                "created_by": created_by,
                "profile": profile,
                "options": _json(options),
                "total": len(docs),
            },
        )
        for document in docs:
            store().query_write(
                text(
                    """
                    INSERT INTO parsing_document
                        (id, task_id, file_name, source_name, source_path,
                         instance_id, sha256, size_bytes, page_start, page_end)
                    VALUES
                        (:id, :task_id, :file_name, :source_name, :source_path,
                         :instance_id, :sha256, :size_bytes, :page_start, :page_end)
                    """
                ),
                {
                    "id": document["id"],
                    "task_id": task_id,
                    "file_name": document["file_name"],
                    "source_name": document.get("source_name"),
                    "source_path": document.get("source_path"),
                    "instance_id": document.get("instance_id"),
                    "sha256": document.get("sha256"),
                    "size_bytes": document.get("size_bytes"),
                    "page_start": document.get("page_start"),
                    "page_end": document.get("page_end"),
                },
            )
    return get_task(task_id) or {"id": task_id}


def get_task(task_id: str) -> dict[str, Any] | None:
    task = _row(
        next(
            iter(
                store().query_read(
                    text("SELECT * FROM parsing_task WHERE id = :id"), {"id": task_id}
                )
            ),
            None,
        )
    )
    if task is None:
        return None
    documents = store().query_read(
        text(
            "SELECT * FROM parsing_document WHERE task_id = :id "
            "ORDER BY created, file_name"
        ),
        {"id": task_id},
    )
    task["documents"] = [
        {key: value for key, value in document.items() if key != "source_path"}
        for document in documents
    ]
    runs = store().query_read(
        text(
            "SELECT id, document_id, attempt, status, progress_done, progress_total, "
            "result_path, error_code, error_message, created, finished "
            "FROM parsing_run WHERE task_id = :id ORDER BY created"
        ),
        {"id": task_id},
    )
    task["runs"] = [
        {key: value for key, value in run.items() if key != "result_path"}
        for run in runs
    ]
    return task


def list_tasks(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if query:
        clauses.append("name ILIKE :query")
        params["query"] = f"%{query}%"
    where = " AND ".join(clauses)
    total = store().query_read(
        text(f"SELECT count(*) AS total FROM parsing_task WHERE {where}"), params
    )[0]["total"]
    rows = store().query_read(
        text(
            f"SELECT * FROM parsing_task WHERE {where} "
            "ORDER BY created DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [_row(row) or {} for row in rows], int(total)


def claim_next_document(worker_id: str) -> dict[str, Any] | None:
    """Atomically take one queued document from a live task."""
    now = _now()
    with write_transaction():
        row = next(
            iter(
                store().query_write(
                    text(
                        """
                        WITH candidate AS (
                            SELECT d.id
                            FROM parsing_document d
                            JOIN parsing_task t ON t.id = d.task_id
                            WHERE d.status = 'queued'
                              AND t.status IN ('queued', 'running')
                            ORDER BY d.created, d.id
                            FOR UPDATE OF d SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE parsing_document d
                        SET status = 'running',
                            started = COALESCE(d.started, :now),
                            attempt = d.attempt + 1,
                            error_code = NULL,
                            error_message = NULL
                        FROM candidate c
                        WHERE d.id = c.id
                        RETURNING d.*
                        """
                    ),
                    {"now": now},
                )
            ),
            None,
        )
        if row is None:
            return None
        store().query_write(
            text(
                "UPDATE parsing_task SET status = 'running', "
                "started = COALESCE(started, :now) "
                "WHERE id = :id AND status = 'queued'"
            ),
            {"now": now, "id": row["task_id"]},
        )
        row["worker_id"] = worker_id
        return dict(row)


def get_task_status(task_id: str) -> str | None:
    row = next(
        iter(
            store().query_read(
                text("SELECT status FROM parsing_task WHERE id = :id"), {"id": task_id}
            )
        ),
        None,
    )
    return row["status"] if row else None


def get_document(document_id: str) -> dict[str, Any] | None:
    return _row(
        next(
            iter(
                store().query_read(
                    text("SELECT * FROM parsing_document WHERE id = :id"),
                    {"id": document_id},
                )
            ),
            None,
        )
    )


def create_run(
    *,
    task_id: str,
    document_id: str,
    attempt: int,
    profile: str,
    options: dict[str, Any],
    model_snapshot: dict[str, Any],
    layout_snapshot: dict[str, Any],
    pipeline_version: str,
    instance_id: str | None,
    result_path: str | None,
    blocks_path: str | None,
) -> dict[str, Any]:
    run_id = _new_id()
    store().query_write(
        text(
            """
            INSERT INTO parsing_run
                (id, task_id, document_id, attempt, profile, options,
                 model_snapshot, layout_snapshot, pipeline_version,
                 instance_id, result_path, blocks_path, status, started)
            VALUES
                (:id, :task_id, :document_id, :attempt, :profile,
                 CAST(:options AS jsonb), CAST(:model_snapshot AS jsonb),
                 CAST(:layout_snapshot AS jsonb), :pipeline_version,
                 :instance_id, :result_path, :blocks_path, 'running', :started)
            """
        ),
        {
            "id": run_id,
            "task_id": task_id,
            "document_id": document_id,
            "attempt": attempt,
            "profile": profile,
            "options": _json(options),
            "model_snapshot": _json(model_snapshot),
            "layout_snapshot": _json(layout_snapshot),
            "pipeline_version": pipeline_version,
            "instance_id": instance_id,
            "result_path": result_path,
            "blocks_path": blocks_path,
            "started": _now(),
        },
    )
    return get_run(run_id) or {"id": run_id}


def update_progress(
    run_id: str, document_id: str, stage: str, done: int, total: int
) -> None:
    store().query_write(
        text(
            "UPDATE parsing_run SET stage = :stage, progress_done = :done, "
            "progress_total = :total "
            "WHERE id = :run_id AND status = 'running'"
        ),
        {"stage": stage, "done": done, "total": total, "run_id": run_id},
    )
    store().query_write(
        text(
            "UPDATE parsing_document SET stage = :stage, progress_done = :done, "
            "progress_total = :total "
            "WHERE id = :document_id AND status = 'running'"
        ),
        {
            "stage": stage,
            "done": done,
            "total": total,
            "document_id": document_id,
        },
    )


def _refresh_task(task_id: str) -> None:
    counts = store().query_read(
        text(
            "SELECT "
            "count(*) FILTER (WHERE status = 'succeeded') AS succeeded, "
            "count(*) FILTER (WHERE status = 'failed') AS failed, "
            "count(*) FILTER (WHERE status = 'cancelled') AS cancelled, "
            "count(*) FILTER (WHERE status NOT IN "
            "('succeeded', 'failed', 'cancelled')) AS active "
            "FROM parsing_document WHERE task_id = :id"
        ),
        {"id": task_id},
    )[0]
    task = next(
        iter(
            store().query_read(
                text("SELECT status FROM parsing_task WHERE id = :id"), {"id": task_id}
            )
        ),
        None,
    )
    if task is None:
        return
    status = task["status"]
    if status != "cancelled":
        if int(counts["active"]) > 0:
            status = "running"
        elif int(counts["failed"]) > 0:
            status = "failed"
        elif int(counts["cancelled"]) > 0:
            status = "cancelled"
        else:
            status = "succeeded"
    store().query_write(
        text(
            "UPDATE parsing_task SET status = :status, "
            "completed_documents = :succeeded, failed_documents = :failed, "
            "finished = CASE WHEN :terminal THEN COALESCE(finished, :now) "
            "ELSE finished END WHERE id = :id"
        ),
        {
            "status": status,
            "succeeded": int(counts["succeeded"]),
            "failed": int(counts["failed"]),
            "terminal": status in {"succeeded", "failed", "cancelled"},
            "now": _now(),
            "id": task_id,
        },
    )


def finish_run_success(
    *,
    run_id: str,
    task_id: str,
    document_id: str,
    page_count: int,
    quality: dict[str, Any],
    processing_time_ms: int | None = None,
) -> None:
    with write_transaction():
        store().query_write(
            text(
                "UPDATE parsing_run SET status = 'succeeded', "
                "progress_done = :pages, progress_total = :pages, stage = 'done', "
                "quality = CAST(:quality AS jsonb), finished = :now "
                "WHERE id = :run_id"
            ),
            {
                "pages": page_count,
                "quality": _json(quality),
                "now": _now(),
                "run_id": run_id,
            },
        )
        store().query_write(
            text(
                "UPDATE parsing_document SET status = 'succeeded', "
                "page_count = :pages, processing_time_ms = :elapsed, "
                "progress_done = :pages, progress_total = :pages, stage = 'done', "
                "finished = :now, error_code = NULL, error_message = NULL "
                "WHERE id = :document_id"
            ),
            {
                "pages": page_count,
                "elapsed": processing_time_ms,
                "now": _now(),
                "document_id": document_id,
            },
        )
        _refresh_task(task_id)


def finish_run_failure(
    *,
    run_id: str,
    task_id: str,
    document_id: str,
    error_code: str,
    error_message: str,
    cancelled: bool = False,
) -> None:
    status = "cancelled" if cancelled else "failed"
    with write_transaction():
        if run_id:
            store().query_write(
                text(
                    "UPDATE parsing_run SET status = :status, stage = :status, "
                    "error_code = :error_code, "
                    "error_message = :error_message, finished = :now WHERE id = :run_id"
                ),
                {
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                    "now": _now(),
                    "run_id": run_id,
                },
            )
        store().query_write(
            text(
                "UPDATE parsing_document SET status = :status, stage = :status, "
                "error_code = :error_code, "
                "error_message = :error_message, finished = :now WHERE id = :document_id"
            ),
            {
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "now": _now(),
                "document_id": document_id,
            },
        )
        _refresh_task(task_id)


def cancel_task(task_id: str) -> bool:
    with write_transaction():
        rows = store().query_write(
            text(
                "UPDATE parsing_task SET status = 'cancelled', finished = :now "
                "WHERE id = :id AND status IN ('queued', 'running') RETURNING id"
            ),
            {"now": _now(), "id": task_id},
        )
        if not rows:
            return False
        store().query_write(
            text(
                "UPDATE parsing_document SET status = 'cancelled', "
                "error_code = 'CANCELLED', error_message = '任务已取消', "
                "finished = :now WHERE task_id = :id AND status = 'queued'"
            ),
            {"now": _now(), "id": task_id},
        )
        _refresh_task(task_id)
        return True


def retry_document(document_id: str) -> bool:
    document = get_document(document_id)
    if document is None or document["status"] not in {"failed", "cancelled"}:
        return False
    with write_transaction():
        store().query_write(
            text(
                "UPDATE parsing_document SET status = 'queued', progress_done = 0, "
                "progress_total = 0, stage = NULL, "
                "error_code = NULL, error_message = NULL, "
                "started = NULL, finished = NULL WHERE id = :id"
            ),
            {"id": document_id},
        )
        store().query_write(
            text(
                "UPDATE parsing_task SET status = 'running', finished = NULL "
                "WHERE id = :id AND status IN ('failed', 'cancelled')"
            ),
            {"id": document["task_id"]},
        )
        _refresh_task(document["task_id"])
    return True


def get_run(run_id: str) -> dict[str, Any] | None:
    row = _row(
        next(
            iter(
                store().query_read(
                    text(
                        "SELECT r.*, d.file_name, d.source_name, d.source_path, "
                        "d.instance_id AS document_instance_id, d.page_count "
                        "FROM parsing_run r "
                        "JOIN parsing_document d ON d.id = r.document_id "
                        "WHERE r.id = :id"
                    ),
                    {"id": run_id},
                )
            ),
            None,
        )
    )
    if row is None:
        return None
    row["edits"] = get_block_edits(run_id)
    return row


def previous_run(run_id: str) -> dict[str, Any] | None:
    """The newest successful run of the same file bytes, before this one.

    Reparse creates a new document row, so identity is the content hash rather
    than the document id. That also makes comparison work after a task is
    deleted and re-uploaded.
    """
    current = get_run(run_id)
    if current is None:
        return None
    document = get_document(current["document_id"])
    if document is None or not document.get("sha256"):
        return None
    row = next(
        iter(
            store().query_read(
                text(
                    "SELECT r.id FROM parsing_run r "
                    "JOIN parsing_document d ON d.id = r.document_id "
                    "WHERE d.sha256 = :sha AND r.id <> :run_id "
                    "AND r.status = 'succeeded' "
                    "ORDER BY r.created DESC LIMIT 1"
                ),
                {"sha": document["sha256"], "run_id": run_id},
            )
        ),
        None,
    )
    return get_run(row["id"]) if row else None


def list_runs(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    query: str | None = None,
    reviewed: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        clauses.append("r.status = :status")
        params["status"] = status
    if reviewed is not None:
        clauses.append("r.reviewed = :reviewed")
        params["reviewed"] = reviewed
    if query:
        clauses.append("(d.file_name ILIKE :query OR t.name ILIKE :query)")
        params["query"] = f"%{query}%"
    where = " AND ".join(clauses)
    total = store().query_read(
        text(
            "SELECT count(*) AS total FROM parsing_run r "
            "JOIN parsing_document d ON d.id = r.document_id "
            "JOIN parsing_task t ON t.id = r.task_id "
            f"WHERE {where}"
        ),
        params,
    )[0]["total"]
    rows = store().query_read(
        text(
            "SELECT r.id, r.task_id, r.document_id, r.attempt, r.profile, "
            "r.status, r.stage, r.progress_done, r.progress_total, r.quality, "
            "r.error_code, r.error_message, r.reviewed, r.created, r.finished, "
            "d.file_name, d.source_name, d.page_count, d.processing_time_ms, "
            "t.name AS task_name "
            "FROM parsing_run r "
            "JOIN parsing_document d ON d.id = r.document_id "
            "JOIN parsing_task t ON t.id = r.task_id "
            f"WHERE {where} "
            "ORDER BY r.created DESC, r.id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [_row(row) or {} for row in rows], int(total)


def get_block_edits(run_id: str) -> dict[str, dict[str, Any]]:
    rows = store().query_read(
        text(
            "SELECT page, idx, content, format, edited_by, edited_at "
            "FROM parsing_block_edit WHERE run_id = :run_id"
        ),
        {"run_id": run_id},
    )
    return {
        f"{row['page']}:{row['idx']}": {
            "content": row["content"],
            "format": row["format"],
            "edited_by": row["edited_by"],
            "edited_at": row["edited_at"].isoformat()
            if isinstance(row["edited_at"], datetime)
            else row["edited_at"],
        }
        for row in rows
    }


def save_block_edits(
    run_id: str, edits: Iterable[dict[str, Any]], edited_by: str | None
) -> int:
    saved = 0
    with write_transaction():
        for edit in edits:
            store().query_write(
                text(
                    """
                    INSERT INTO parsing_block_edit
                        (run_id, page, idx, content, format, edited_by, edited_at)
                    VALUES
                        (:run_id, :page, :idx, :content, :format, :edited_by, :now)
                    ON CONFLICT (run_id, page, idx) DO UPDATE SET
                        content = EXCLUDED.content,
                        format = EXCLUDED.format,
                        edited_by = EXCLUDED.edited_by,
                        edited_at = EXCLUDED.edited_at
                    """
                ),
                {
                    "run_id": run_id,
                    "page": int(edit["page"]),
                    "idx": int(edit["idx"]),
                    "content": str(edit["content"]),
                    "format": edit.get("format"),
                    "edited_by": edited_by,
                    "now": _now(),
                },
            )
            saved += 1
    return saved


def set_reviewed(
    run_id: str, *, reviewed: bool, reviewed_by: str | None, note: str | None
) -> bool:
    rows = store().query_write(
        text(
            "UPDATE parsing_run SET reviewed = :reviewed, reviewed_by = :reviewed_by, "
            "reviewed_at = :now, review_note = :note WHERE id = :id RETURNING id"
        ),
        {
            "reviewed": reviewed,
            "reviewed_by": reviewed_by,
            "now": _now() if reviewed else None,
            "note": note,
            "id": run_id,
        },
    )
    return bool(rows)


def recover_stale(lease: timedelta = timedelta(minutes=20)) -> int:
    """Return documents abandoned by a dead API process to the queue."""
    cutoff = _now() - lease
    with write_transaction():
        runs = store().query_write(
            text(
                "UPDATE parsing_run SET status = 'failed', "
                "error_code = 'WORKER_LOST', "
                "error_message = '解析进程中断，任务已重新排队', finished = :now "
                "WHERE status = 'running' AND started < :cutoff RETURNING id"
            ),
            {"now": _now(), "cutoff": cutoff},
        )
        docs = store().query_write(
            text(
                "UPDATE parsing_document SET status = 'queued', progress_done = 0, "
                "progress_total = 0, started = NULL, finished = NULL "
                "WHERE status = 'running' AND started < :cutoff RETURNING id"
            ),
            {"cutoff": cutoff},
        )
        store().query_write(
            text(
                "UPDATE parsing_document d SET status = 'cancelled', "
                "error_code = 'CANCELLED', error_message = '任务已取消', "
                "finished = :now FROM parsing_task t "
                "WHERE d.task_id = t.id AND t.status = 'cancelled' "
                "AND d.status IN ('queued', 'running')"
            ),
            {"now": _now()},
        )
        tasks = store().query_write(
            text(
                "UPDATE parsing_task SET status = 'running', finished = NULL "
                "WHERE status = 'running' AND id IN "
                "(SELECT task_id FROM parsing_document WHERE status = 'queued') "
                "RETURNING id"
            )
        )
    return max(len(runs), len(docs), len(tasks))


def delete_run(run_id: str) -> str | None:
    """Delete one run row and return its instance id for filesystem cleanup."""
    row = next(
        iter(
            store().query_write(
                text("DELETE FROM parsing_run WHERE id = :id RETURNING instance_id"),
                {"id": run_id},
            )
        ),
        None,
    )
    return row["instance_id"] if row else None


def delete_task(task_id: str) -> list[str]:
    """Delete a task and every run/file row; return instance ids to clean up."""
    instance_ids = [
        row["instance_id"]
        for row in store().query_read(
            text(
                "SELECT instance_id FROM parsing_document "
                "WHERE task_id = :id AND instance_id IS NOT NULL"
            ),
            {"id": task_id},
        )
    ]
    store().query_write(
        text("DELETE FROM parsing_task WHERE id = :id"), {"id": task_id}
    )
    return instance_ids
