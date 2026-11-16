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

import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from all_ontology.parsing import service
from all_ontology.parsing import settings as parsing_settings
from all_ontology.parsing.tasks import INSTANCE_ID, task_store
from all_ontology.server.responses import (
    ParsingBackendStatusResponse,
    ParsingCapabilitiesResponse,
    ParsingDocumentResponse,
    ParsingInstanceListResponse,
    ParsingInstanceResponse,
    ParsingJobResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Upload cap. A 200-page scan is ~40 MB; beyond this the pipeline's memory use
#: is the caller's problem, so it is refused up front with a readable message
#: rather than an OOM halfway through page 180.
MAX_UPLOAD_BYTES = int(
    os.environ.get("PARSING_MAX_UPLOAD_BYTES", str(64 * 1024 * 1024))
)


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
