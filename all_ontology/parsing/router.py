# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HTTP surface for document parsing.

Replaces OXR's ``oxr/server/routes.py``. The differences are all about who is
calling: OXR took an ``api_key`` form field per request because it was a
standalone service; here the caller is already authenticated by the Next.js BFF
(``withPermission({catalog: ['edit']})``), so the field is gone. The envelopes
are this product's ``{"data": …}`` rather than OXR's ``code/message/warnings``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from all_ontology.parsing import service
from all_ontology.parsing import settings as parsing_settings
from all_ontology.parsing import store
from all_ontology.parsing.tasks import INSTANCE_ID, task_store
from all_ontology.server.connections import files as connection_files
from all_ontology.server.identity import resolve_internal_user
from all_ontology.server.responses import (
    ParsingBackendStatusResponse,
    ParsingCapabilitiesResponse,
    ParsingDocumentResponse,
    ParsingHealthResponse,
    ParsingInstanceListResponse,
    ParsingInstanceResponse,
    ParsingJobResponse,
    ParsingProfileListResponse,
    ParsingRunListResponse,
    ParsingRunOptionalResponse,
    ParsingRunResponse,
    ParsingSourceListingResponse,
    ParsingSourceScanResponse,
    ParsingTaskListResponse,
    ParsingTaskResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Upload cap. A 200-page scan is ~40 MB; beyond this the pipeline's memory use
#: is the caller's problem, so it is refused up front with a readable message
#: rather than an OOM halfway through page 180.
MAX_UPLOAD_BYTES = int(
    os.environ.get("PARSING_MAX_UPLOAD_BYTES", str(64 * 1024 * 1024))
)
MAX_FILES_PER_TASK = int(os.environ.get("PARSING_MAX_FILES_PER_TASK", "50"))
MAX_SCAN_FILES = int(os.environ.get("PARSING_MAX_SCAN_FILES", "1000"))


class ParsingSourceScanBody(BaseModel):
    path: str


class ParsingFolderTaskBody(ParsingSourceScanBody):
    name: str | None = None
    profile: str = "standard"
    options: dict[str, Any] = Field(default_factory=dict)
    page_start: int | None = None
    page_end: int | None = None


#: Signatures the parser can actually decode. The extension is the user's; the
#: bytes are the fact. PDFs start with ``%PDF-``; the image types are checked
#: because a renamed executable must not become a TIFF decoder input.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "PDF"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"BM", "BMP"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
)


def _detect_kind(payload: bytes) -> str | None:
    for prefix, kind in _SIGNATURES:
        if payload.startswith(prefix):
            return kind
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "WEBP"
    return None


def _validate_payload(payload: bytes, name: str) -> None:
    kind = _detect_kind(payload)
    if kind is None:
        raise HTTPException(
            status_code=415,
            detail=f"{name} 不是支持的 PDF 或图片文件。",
        )


def _safe_json(raw: str | None, field: str) -> dict[str, Any]:
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=422, detail=f"{field} 不是有效的 JSON。"
        ) from error
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=f"{field} 必须是 JSON 对象。")
    return parsed


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in task.items() if key not in {"documents", "runs"}
    } | {
        "documents": task.get("documents") or [],
        "runs": task.get("runs") or [],
    }


def _instance_id_for_run(run: dict[str, Any]) -> str | None:
    return run.get("instance_id") or run.get("document_instance_id")


def _read_result(run: dict[str, Any]) -> dict[str, Any]:
    path = run.get("result_path")
    if not path:
        return {"outputs": {}, "metadata": {}}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"outputs": {}, "metadata": {}}


def _apply_edits(
    outputs: dict[str, Any], edits: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Apply block edits to the JSON output and re-render Markdown.

    The stored result stays untouched; edits are an overlay. This makes a
    correction reversible by deleting its row and keeps the original answer
    available for comparison.
    """
    if not edits:
        return outputs
    outputs = json.loads(json.dumps(outputs))
    json_output = outputs.get("json")
    if not isinstance(json_output, dict):
        return outputs
    pages = json_output.get("pages")
    if not isinstance(pages, list):
        return outputs
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_num = page.get("page_num", 0)
        for block in page.get("blocks") or []:
            key = f"{page_num}:{block.get('idx')}"
            edit = edits.get(key)
            if edit is None:
                continue
            block["content"] = edit["content"]
            if edit.get("format"):
                block["format"] = edit["format"]
            block["edited"] = True
    outputs["markdown"] = _markdown_from_json(pages)
    return outputs


def _markdown_from_json(pages: list[dict[str, Any]]) -> str:
    """A small renderer for edited results, matching the pipeline's shape.

    It is deliberately not a second full Markdown renderer: tables are emitted
    as their stored HTML and formulas as ``$$`` blocks, which is exactly what
    the pipeline's own blocks-to-markdown path does for those types.
    """
    from all_ontology.parsing.pipeline.assembler import assemble_markdown
    from all_ontology.parsing.pipeline.models import Block, BlockType, ContentFormat

    rendered: list[list[Block]] = []
    for page in pages:
        blocks: list[Block] = []
        for item in page.get("blocks") or []:
            raw_type = str(item.get("type") or "Text")
            try:
                block_type = BlockType(raw_type)
            except ValueError:
                block_type = BlockType.TEXT
            try:
                block_format = ContentFormat(str(item.get("format") or "text"))
            except ValueError:
                block_format = ContentFormat.TEXT
            blocks.append(
                Block(
                    idx=int(item.get("idx") or 0),
                    type=block_type,
                    bbox=list(item.get("bbox") or [0, 0, 0, 0]),
                    content=str(item.get("content") or ""),
                    format=block_format,
                )
            )
        rendered.append(blocks)
    return assemble_markdown(rendered)


def _run_detail(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    record = _read_result(run)
    outputs = _apply_edits(record.get("outputs") or {}, run.get("edits") or {})
    detail = {
        **run,
        "file_name": record.get("file_name") or run.get("file_name"),
        "source_name": record.get("source_name") or run.get("source_name"),
        "outputs": outputs,
        "metadata": record.get("metadata") or {},
        "instance_id": _instance_id_for_run(run),
    }
    for key in ("source_path", "result_path", "blocks_path"):
        detail.pop(key, None)
    return detail


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限，"
                "请拆分后再上传。"
            ),
        )
    if not payload:
        raise HTTPException(status_code=422, detail="上传的文件是空的。")
    name = (file.filename or "document").strip() or "document"
    _validate_payload(payload, name)
    return payload, name


@router.get("/parsing/capabilities", response_model=ParsingCapabilitiesResponse)
async def parsing_capabilities() -> dict:
    """Backend state plus the option values the form may offer."""
    return {"data": await service.capabilities()}


#: Asset paths the parser writes: ``<image_output_dir>/<document>/<kind>/<file>``.
#: Restricted to the two segments the pipeline produces, so a request cannot walk
#: out of the asset directory even before the realpath check below.
_ASSET_DOCUMENT = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_ASSET_KIND = re.compile(r"^(imgs|tables)$")
_ASSET_FILE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.png$")


@router.get("/parsing/assets/{document}/{kind}/{name}")
def parsing_asset(document: str, kind: str, name: str) -> FileResponse:
    """Serve one extracted picture, for the Markdown ``![]()`` links to resolve.

    The parser writes crops to a directory and puts a link to them in the
    Markdown. Without this route those links only worked when the reader had the
    server's filesystem; now the same ``/api/parsing/assets/...`` path works in
    the app's preview, behind a reverse proxy, and in any client that can reach
    this API.
    """
    if not (
        _ASSET_DOCUMENT.match(document)
        and _ASSET_KIND.match(kind)
        and _ASSET_FILE.match(name)
    ):
        raise HTTPException(status_code=404, detail="Asset not found")

    root = Path(parsing_settings.settings.pipeline.image_output_dir).resolve()
    target = (root / document / kind / name).resolve()
    if root not in target.parents:
        # `..` cannot appear in the names above, but a symlinked directory could
        # still point outside; resolving both sides is what makes this a check
        # rather than a hope.
        raise HTTPException(status_code=404, detail="Asset not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(target, media_type="image/png")


@router.get("/parsing/settings", response_model=ParsingBackendStatusResponse)
async def get_parsing_settings() -> dict:
    """The effective parsing settings, for the 模型设置 page.

    Returned in the shape ``model_backend.describe()`` produces — mode, the
    three groups, and a flattened state — with the vLLM credential removed and
    reported as ``api_key_configured`` instead.
    """
    return {"data": await parsing_settings.status()}


@router.get("/parsing/health", response_model=ParsingHealthResponse)
async def parsing_health() -> dict:
    """Probe both model services so the page can say "healthy", not just "set"."""
    return {"data": await service.health()}


@router.get("/parsing/profiles", response_model=ParsingProfileListResponse)
async def parsing_profiles() -> dict:
    """The built-in fast/standard/accurate presets."""
    profiles = store.list_profiles()
    return {"data": profiles, "count": len(profiles)}


@router.get("/parsing/sources", response_model=ParsingSourceListingResponse)
def browse_parsing_sources(path: str | None = None) -> dict:
    """Browse the same allowlisted shared folders as the connection wizard."""
    try:
        return {"data": connection_files.browse_source_path(path)}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/parsing/sources/scan", response_model=ParsingSourceScanResponse)
def scan_parsing_sources(body: ParsingSourceScanBody) -> dict:
    """Recursively list PDFs below a selected shared folder."""
    try:
        found = connection_files.scan_shared_files(
            body.path,
            suffixes={".pdf"},
            max_files=MAX_SCAN_FILES,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "data": {
            "path": body.path,
            "count": len(found),
            "files": found,
            "limit": MAX_SCAN_FILES,
        }
    }


@router.post(
    "/parsing/tasks/from-folder",
    response_model=ParsingTaskResponse,
    status_code=202,
)
async def create_parsing_task_from_folder(
    request: Request, body: ParsingFolderTaskBody
) -> dict:
    """Create one durable task from every PDF below a shared folder.

    The source files are copied into the parsing upload directory, so the
    result survives the shared folder being renamed or disconnected. Each file
    still gets its own document row and run, which is what makes per-PDF
    progress and later comparison possible.
    """
    options_data = body.options or {}
    parsed_options, errors = service.build_options(
        options_data.get("output_formats"),
        json.dumps(
            {"keep_header_footer": bool(options_data.get("keep_header_footer"))}
        ),
        json.dumps(options_data.get("model_options") or {}),
        json.dumps(options_data.get("element_formats") or {}),
    )
    if parsed_options is None:
        raise HTTPException(status_code=422, detail="参数错误: " + "；".join(errors))
    if body.page_start is not None and body.page_start < 1:
        raise HTTPException(status_code=422, detail="起始页必须从 1 开始。")
    if (
        body.page_end is not None
        and body.page_start is not None
        and body.page_end < body.page_start
    ):
        raise HTTPException(status_code=422, detail="结束页不能小于起始页。")

    try:
        found = connection_files.scan_shared_files(
            body.path,
            suffixes={".pdf"},
            max_files=MAX_SCAN_FILES,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not found:
        raise HTTPException(status_code=422, detail="该文件夹下没有找到 PDF 文件。")

    await parsing_settings.ensure_current()
    store.resolve_profile(body.profile)
    documents: list[dict[str, Any]] = []
    stored_instances: list[service.Instance] = []
    try:
        for item in found:
            try:
                source, payload = connection_files.read_shared_bytes(
                    item["path"], max_bytes=MAX_UPLOAD_BYTES
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            _validate_payload(payload, source.name)
            display_name = item["relative"].replace("\\", "/")
            instance = service.create_instance(payload, display_name)
            if instance is None:
                raise HTTPException(
                    status_code=503,
                    detail="无法保存共享文件夹中的文件，请检查解析存储目录是否可写。",
                )
            stored_instances.append(instance)
            documents.append(
                {
                    "id": str(uuid.uuid4()),
                    "file_name": display_name,
                    "source_name": source.name,
                    "source_path": str(source),
                    "instance_id": instance.id,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "page_start": body.page_start,
                    "page_end": body.page_end,
                }
            )
        folder_name = Path(body.path).name or body.path
        task = store.create_task(
            name=(body.name or "").strip()
            or f"{folder_name} · {len(documents)} 个 PDF",
            created_by=resolve_internal_user(request, required=False),
            profile=body.profile,
            options=options_data,
            documents=documents,
        )
        return {"data": task}
    except Exception:
        for instance in stored_instances:
            try:
                service.delete_instance(instance.document, instance.run)
            except Exception:
                logger.warning("Could not clean up folder task upload", exc_info=True)
        raise


@router.post("/parsing/tasks", response_model=ParsingTaskResponse, status_code=202)
async def create_parsing_task(
    request: Request,
    files: list[UploadFile] = File(...),
    name: str | None = Form(None),
    profile: str = Form("standard"),
    options: str | None = Form(None),
    page_start: int | None = Form(None),
    page_end: int | None = Form(None),
) -> dict:
    """Create a durable batch task and store each source file.

    Nothing is parsed in this request: it validates, writes the sources, and
    returns a task id. The worker picks up the files and writes progress, which
    is what lets a refresh or an API restart keep the task.
    """
    if not files:
        raise HTTPException(status_code=422, detail="至少选择一个文件。")
    if len(files) > MAX_FILES_PER_TASK:
        raise HTTPException(
            status_code=422,
            detail=f"单次最多提交 {MAX_FILES_PER_TASK} 个文件，请分批上传。",
        )
    if page_start is not None and page_start < 1:
        raise HTTPException(status_code=422, detail="起始页必须从 1 开始。")
    if page_end is not None and page_start is not None and page_end < page_start:
        raise HTTPException(status_code=422, detail="结束页不能小于起始页。")

    options_data = _safe_json(options, "options")
    parsed_options, errors = service.build_options(
        options_data.get("output_formats"),
        json.dumps(
            {"keep_header_footer": bool(options_data.get("keep_header_footer"))}
        ),
        json.dumps(options_data.get("model_options") or {}),
        json.dumps(options_data.get("element_formats") or {}),
    )
    if parsed_options is None:
        raise HTTPException(status_code=422, detail="参数错误: " + "；".join(errors))
    # Apply the stored upload directory before anything is written.
    await parsing_settings.ensure_current()
    store.resolve_profile(profile)

    documents: list[dict[str, Any]] = []
    stored_instances: list[service.Instance] = []
    try:
        for upload in files:
            payload, file_name = await _read_upload(upload)
            instance = service.create_instance(payload, file_name)
            if instance is None:
                raise HTTPException(
                    status_code=503,
                    detail="无法保存上传文件，请检查解析存储目录是否可写。",
                )
            stored_instances.append(instance)
            documents.append(
                {
                    "id": str(uuid.uuid4()),
                    "file_name": file_name,
                    "source_name": instance.source.name,
                    "source_path": str(instance.source),
                    "instance_id": instance.id,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "page_start": page_start,
                    "page_end": page_end,
                }
            )
        task_name = (name or "").strip() or (
            f"{Path(files[0].filename or '解析任务').stem} 等 {len(files)} 份"
            if len(files) > 1
            else Path(files[0].filename or "解析任务").stem
        )
        task = store.create_task(
            name=task_name,
            created_by=resolve_internal_user(request, required=False),
            profile=profile,
            options=options_data,
            documents=documents,
        )
        return {"data": task}
    except Exception:
        for instance in stored_instances:
            try:
                service.delete_instance(instance.document, instance.run)
            except Exception:
                logger.warning("Could not clean up failed task upload", exc_info=True)
        raise


@router.get("/parsing/tasks", response_model=ParsingTaskListResponse)
async def list_parsing_tasks(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
) -> dict:
    """The task centre: durable, filterable, and independent of any one tab."""
    limit = max(1, min(limit, 200))
    tasks, total = store.list_tasks(
        limit=limit, offset=max(0, offset), status=status, query=q
    )
    return {"data": tasks, "count": len(tasks), "total": total}


@router.get("/parsing/tasks/{task_id}", response_model=ParsingTaskResponse)
async def get_parsing_task(task_id: str) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="解析任务不存在。")
    return {"data": task}


@router.post("/parsing/tasks/{task_id}/cancel", response_model=ParsingTaskResponse)
async def cancel_parsing_task(task_id: str) -> dict:
    if not store.cancel_task(task_id):
        raise HTTPException(status_code=409, detail="任务已经结束，无法取消。")
    task = store.get_task(task_id)
    return {"data": task or {"id": task_id}}


@router.delete("/parsing/tasks/{task_id}")
async def delete_parsing_task(task_id: str) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="解析任务不存在。")
    if task["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="任务仍在进行，请先取消。")
    instance_ids = store.delete_task(task_id)
    for instance_id in instance_ids:
        document, _, run = instance_id.partition("/")
        try:
            service.delete_instance(document, run)
        except HTTPException:
            pass
    return {"data": {"id": task_id}}


@router.post("/parsing/documents/{document_id}/retry")
async def retry_parsing_document(document_id: str) -> dict:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="解析文件不存在。")
    if not store.retry_document(document_id):
        raise HTTPException(status_code=409, detail="只有失败或取消的文件可以重试。")
    task = store.get_task(document["task_id"])
    return {"data": task or {"id": document["task_id"]}}


@router.get("/parsing/runs", response_model=ParsingRunListResponse)
async def list_parsing_runs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
    reviewed: bool | None = None,
) -> dict:
    """The result library, paginated and searchable."""
    limit = max(1, min(limit, 200))
    runs, total = store.list_runs(
        limit=limit,
        offset=max(0, offset),
        status=status,
        query=q,
        reviewed=reviewed,
    )
    return {"data": runs, "count": len(runs), "total": total}


@router.get("/parsing/runs/{run_id}", response_model=ParsingRunResponse)
async def get_parsing_run(run_id: str) -> dict:
    return {"data": _run_detail(run_id)}


@router.get(
    "/parsing/runs/{run_id}/previous", response_model=ParsingRunOptionalResponse
)
async def get_previous_parsing_run(run_id: str) -> dict:
    """The newest successful run of the same file, for side-by-side review."""
    previous = store.previous_run(run_id)
    return {"data": _run_detail(previous["id"]) if previous is not None else None}


@router.patch("/parsing/runs/{run_id}/blocks", response_model=ParsingRunResponse)
async def update_parsing_blocks(
    run_id: str, request: Request, body: dict[str, Any]
) -> dict:
    """Save block-level corrections as an overlay on the original result."""
    edits = body.get("blocks")
    if not isinstance(edits, list):
        raise HTTPException(status_code=422, detail="blocks 必须是数组。")
    for edit in edits:
        if not isinstance(edit, dict):
            raise HTTPException(status_code=422, detail="每个 block 必须是对象。")
        if not {"page", "idx", "content"} <= set(edit):
            raise HTTPException(
                status_code=422, detail="block 需要 page、idx 和 content。"
            )
    _run_detail(run_id)
    store.save_block_edits(
        run_id,
        edits,
        edited_by=resolve_internal_user(request, required=False),
    )
    return {"data": _run_detail(run_id)}


@router.post("/parsing/runs/{run_id}/review", response_model=ParsingRunResponse)
async def review_parsing_run(
    run_id: str, request: Request, body: dict[str, Any] | None = None
) -> dict:
    payload = body or {}
    reviewed = bool(payload.get("reviewed", True))
    if not store.set_reviewed(
        run_id,
        reviewed=reviewed,
        reviewed_by=resolve_internal_user(request, required=False),
        note=payload.get("note"),
    ):
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    return {"data": _run_detail(run_id)}


@router.post("/parsing/runs/{run_id}/reparse", response_model=ParsingTaskResponse)
async def reparse_parsing_run(run_id: str, request: Request) -> dict:
    """Re-run a stored source with the same options, as a new task."""
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    instance_id = _instance_id_for_run(run)
    if not instance_id:
        raise HTTPException(status_code=409, detail="这次解析没有保存源文件。")
    instance = service.instance_from_id(instance_id)
    if not instance.source.is_file():
        raise HTTPException(status_code=409, detail="源文件已被移动或删除。")
    payload = instance.source.read_bytes()
    new_instance = service.create_instance(payload, instance.source.name)
    if new_instance is None:
        raise HTTPException(status_code=503, detail="无法保存源文件副本。")
    document = {
        "id": str(uuid.uuid4()),
        "file_name": instance.source.name,
        "source_name": instance.source.name,
        "source_path": str(new_instance.source),
        "instance_id": new_instance.id,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    task = store.create_task(
        name=f"重跑 · {instance.source.name}",
        created_by=resolve_internal_user(request, required=False),
        profile=run.get("profile") or "standard",
        options=run.get("options") or {},
        documents=[document],
    )
    return {"data": task}


def _export_name(run: dict[str, Any]) -> str:
    stem = Path(str(run.get("file_name") or "document")).stem or "document"
    safe = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", stem).strip("-")
    return safe or "document"


@router.get("/parsing/runs/{run_id}/export")
def export_parsing_run(run_id: str) -> StreamingResponse:
    """Download the source, the corrected outputs, and the edit overlay."""
    detail = _run_detail(run_id)
    buffer = io.BytesIO()
    instance_id = detail.get("instance_id")
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if instance_id:
            instance = service.instance_from_id(instance_id)
            for path in instance.directory.rglob("*"):
                if path.is_file() and path.name != "result.json":
                    archive.write(path, path.relative_to(instance.directory))
        markdown = (detail.get("outputs") or {}).get("markdown")
        if isinstance(markdown, str):
            archive.writestr("markdown.md", markdown)
        archive.writestr(
            "result.json",
            json.dumps(
                {
                    "id": detail["id"],
                    "file_name": detail.get("file_name"),
                    "outputs": detail.get("outputs") or {},
                    "metadata": detail.get("metadata") or {},
                    "edits": detail.get("edits") or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    buffer.seek(0)
    filename = f"{_export_name(detail)}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/parsing/runs/{run_id}/page/{page_index}")
def parsing_run_page(run_id: str, page_index: int) -> Response:
    """One rendered source page, used by the bbox viewer."""
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    instance_id = _instance_id_for_run(run)
    if not instance_id:
        raise HTTPException(status_code=404, detail="这次解析没有保存源文件。")
    if page_index < 0:
        raise HTTPException(status_code=404, detail="Page not found")
    content, media_type = service.render_page(
        service.instance_from_id(instance_id), page_index
    )
    return Response(content=content, media_type=media_type)


@router.delete("/parsing/runs/{run_id}")
async def delete_parsing_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    if run.get("status") == "running":
        raise HTTPException(status_code=409, detail="解析仍在进行，暂不能删除。")
    instance_id = store.delete_run(run_id)
    if instance_id is None:
        raise HTTPException(status_code=404, detail="解析结果不存在。")
    try:
        document, _, run = instance_id.partition("/")
        service.delete_instance(document, run)
    except HTTPException:
        pass
    return {"data": {"id": run_id}}


@router.post("/parsing/documents", response_model=ParsingDocumentResponse)
async def parse_document(
    file: UploadFile = File(...),
    output_formats: list[str] | None = Form(None),
    feature_config: str | None = Form(None),
    extra: str | None = Form(None),
    element_formats: str | None = Form(None),
) -> dict:
    """Parse one document and wait for the result.

    Synchronous because the caller is a person watching a spinner: a 5-page PDF
    is a few seconds, and an async task would only add polling. Anything that
    might take minutes belongs on ``POST /parsing/jobs``.
    """
    options, errors = service.build_options(
        output_formats, feature_config, extra, element_formats
    )
    if options is None:
        raise HTTPException(
            status_code=422,
            detail="参数错误: " + "；".join(errors),
        )
    await service.ensure_ready()
    payload, name = await _read_upload(file)
    instance = service.create_instance(payload, name)
    parsed = await service.parse_now(payload, name, options, instance)
    return {"data": parsed}


@router.post("/parsing/jobs", response_model=ParsingJobResponse, status_code=202)
async def submit_parsing_job(
    file: UploadFile = File(...),
    output_formats: list[str] | None = Form(None),
    feature_config: str | None = Form(None),
    extra: str | None = Form(None),
    element_formats: str | None = Form(None),
) -> dict:
    """Queue a parse and return immediately.

    The job runs in this process. ``instance`` in the answer tells the poller
    which process owns it, so a replica that never saw the job can say so.
    """
    options, errors = service.build_options(
        output_formats, feature_config, extra, element_formats
    )
    if options is None:
        raise HTTPException(
            status_code=422,
            detail="参数错误: " + "；".join(errors),
        )
    await service.ensure_ready()
    payload, name = await _read_upload(file)
    instance = service.create_instance(payload, name)
    task_id = await service.submit_job(payload, name, options)
    # Fire and forget: the task store is the only observer, and a raised
    # exception inside is recorded there rather than dropped. `start_job` keeps
    # a strong reference so the task is not collected mid-flight.
    service.start_job(task_id, payload, name, options, instance)
    return {
        "data": {
            "task_id": task_id,
            "status": "queuing",
            "instance": INSTANCE_ID,
            "file_name": name,
        }
    }


#: Instance ids are two path segments; the regexes in the service are what keep
#: them from becoming a directory walk.
@router.get("/parsing/instances", response_model=ParsingInstanceListResponse)
async def list_parsing_instances(limit: int = 50) -> dict:
    """Recent parse runs, newest first, without their outputs.

    Disk is the register: one folder per run, written when the run finishes. A
    second index would be a second thing to keep consistent for no gain.
    """
    instances = service.list_instances(limit=limit)
    return {"data": instances, "count": len(instances)}


@router.get(
    "/parsing/instances/{document}/{run}", response_model=ParsingInstanceResponse
)
async def get_parsing_instance(document: str, run: str) -> dict:
    """One stored run, Markdown and JSON included."""
    return {"data": service.read_instance(document, run)}


@router.get("/parsing/instances/{document}/{run}/source")
def get_parsing_instance_source(document: str, run: str) -> FileResponse:
    """The file this run parsed, for the viewer's 原始文件 tab."""
    instance = service.instance_source(document, run)
    # The media type is guessed from the stored name: a run may hold a PDF, a
    # PNG or a TIFF, and the browser's viewer behaves differently per type.
    return FileResponse(instance.source, filename=instance.source.name)


@router.delete("/parsing/instances/{document}/{run}")
async def delete_parsing_instance(document: str, run: str) -> dict:
    """Remove one run: source, answer and extracted pictures."""
    service.delete_instance(document, run)
    return {"data": {"id": f"{document}/{run}"}}


@router.get("/parsing/jobs/{task_id}", response_model=ParsingJobResponse)
async def get_parsing_job(task_id: str) -> dict:
    """Poll a job. ``404`` means this process does not know it."""
    job = await task_store.get(task_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "任务不存在或已被清理。异步任务保存在接收它的进程内存里，"
                "重启服务或多副本部署时请改用同步解析接口。"
            ),
        )
    return {"data": job}


@router.post("/parsing/backends/test", response_model=ParsingBackendStatusResponse)
async def test_parsing_backend(body: dict[str, Any] | None = None) -> dict:
    """Probe the recognition backend, optionally with unsaved settings."""
    return {"data": await service.test_backend(body or None)}


@router.post("/parsing/layout/test", response_model=ParsingBackendStatusResponse)
async def test_parsing_layout(body: dict[str, Any] | None = None) -> dict:
    """Probe the D-FINE layout service, optionally with unsaved settings."""
    return {"data": await service.test_layout(body or None)}
