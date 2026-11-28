# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document-parsing request handling, without the HTTP layer.

This is OXR's ``oxr/server/routes.py`` split in two: the option parsing below is
that file almost verbatim (it is pure validation, and its Chinese error strings
are the product's), while the orchestration around it is rewritten for this
service — no ``api_key`` form field, an ``{"data": …}`` envelope supplied by the
router, and settings that come from the database instead of a JSON file.

Keeping the validators byte-for-byte compatible matters: the frontend renders
their messages, and a user who has used the OXR demo should get the same
complaints about the same inputs.
"""

from __future__ import annotations

import asyncio
import mimetypes
import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from all_ontology.parsing import settings as parsing_settings
from all_ontology.parsing.config.settings import DEFAULT_IMAGE_VLM_PROMPT, settings
from all_ontology.parsing.image_understanding import understand_result_images
from all_ontology.parsing.model.backend import model_backend
from all_ontology.parsing.pipeline.errors import (
    ParsingCancelledError,
    get_error_status_code,
    get_public_error_message,
)
from all_ontology.parsing.pipeline.orchestrator import process_document
from all_ontology.parsing.pipeline.postprocess.picture_postprocess import document_slug
from all_ontology.parsing.tasks import task_store
from all_ontology.parsing.utils.pdf import pdf_to_images

logger = logging.getLogger(__name__)

#: Characters Windows and POSIX disagree on, plus control bytes. Replaced rather
#: than rejected: an uploaded file's name is the user's, not ours to refuse.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: One parse run. Sortable as text (so a plain directory listing is
#: newest-last), unique enough for concurrent uploads, and safe as a path
#: segment — the asset route and the instance routes both use it verbatim.
_RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


@dataclass(frozen=True)
class Instance:
    """One parse run: the source file, its answer, and where they live.

    A folder per run rather than per document: re-uploading a corrected invoice
    must not silently replace the answer a colleague is still reading. The
    id is ``<document>/<run>``, which is also the URL path.
    """

    document: str
    run: str
    directory: Path
    source: Path

    @property
    def id(self) -> str:
        return f"{self.document}/{self.run}"

    @property
    def result_path(self) -> Path:
        return self.directory / "result.json"


DEFAULT_OUTPUT_FORMATS = ["markdown", "json"]
SUPPORTED_OUTPUT_FORMATS = {"markdown", "json"}
DEFAULT_ELEMENT_FORMATS = {
    "image": "url",
    "formula": "latex",
    "table": "html",
    "cs": "smiles",
}
SUPPORTED_ELEMENT_FORMATS = {
    "image": {"url", "base64", "none", "file"},
    "formula": {"latex", "mathml", "ascii"},
    "table": {"html", "markdown", "image"},
    "cs": {"smiles", "image"},
}
FUNCTIONAL_ELEMENT_FORMATS = {
    "image": {"url", "base64", "none"},
    "formula": {"latex"},
    "table": {"html", "markdown"},
    "cs": {"smiles", "image"},
}
FEATURE_CONFIG_SUPPORTED_KEYS = {
    "keep_header_footer",
    "image_understanding",
    "image_min_area_px",
    "image_prompt",
    "image_max_tokens",
}
MODEL_OPTION_RANGES = {
    "temperature": (0.0, 2.0, True),
    "top_p": (0.0, 1.0, True),
    "repetition_penalty": (0.0, None, False),
}


@dataclass
class ParseOptions:
    output_formats: list[str] = field(
        default_factory=lambda: DEFAULT_OUTPUT_FORMATS.copy()
    )
    keep_header_footer: bool = False
    model_options: dict[str, float] = field(default_factory=dict)
    element_formats: dict[str, str] = field(
        default_factory=lambda: DEFAULT_ELEMENT_FORMATS.copy()
    )
    image_vlm_enabled: bool = True
    image_vlm_min_area_px: int = 200_000
    image_vlm_prompt: str = DEFAULT_IMAGE_VLM_PROMPT
    image_vlm_max_tokens: int = 1024
    warnings: list[str] = field(default_factory=list)


def _format_issues(prefix: str, issues: list[str]) -> str:
    return f"{prefix}: " + "；".join(issues)


def _parse_output_formats(
    output_formats: list[str] | None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    formats = output_formats or DEFAULT_OUTPUT_FORMATS
    normalized = [item.strip().lower() for item in formats if item and item.strip()]
    if not normalized:
        return DEFAULT_OUTPUT_FORMATS.copy(), errors

    invalid = [item for item in normalized if item not in SUPPORTED_OUTPUT_FORMATS]
    for item in invalid:
        if item == "zip":
            errors.append(
                "output_formats=zip is not supported by open-source OXR; "
                "zip packaging is not implemented."
            )
        else:
            errors.append(
                f"output_formats={item} is invalid; supported values are markdown and json."
            )
    return [item for item in normalized if item in SUPPORTED_OUTPUT_FORMATS], errors


def _parse_model_option(config: dict[str, Any], key: str) -> float | None:
    if key not in config:
        return None

    value = config[key]
    if isinstance(value, bool):
        raise ValueError(f"extra.{key} must be a number.")

    try:
        parsed_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"extra.{key} must be a number.") from exc

    minimum, maximum, include_minimum = MODEL_OPTION_RANGES[key]
    if include_minimum:
        if parsed_value < minimum:
            raise ValueError(f"extra.{key} must be between {minimum} and {maximum}.")
    elif parsed_value <= minimum:
        raise ValueError(f"extra.{key} must be greater than {minimum}.")

    if maximum is not None and parsed_value > maximum:
        raise ValueError(f"extra.{key} must be between {minimum} and {maximum}.")

    return parsed_value


def _parse_feature_config(
    feature_config: str | None,
) -> tuple[bool, dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    if not feature_config:
        return False, {}, warnings, errors
    try:
        config = json.loads(feature_config)
    except json.JSONDecodeError:
        errors.append("feature_config must be a JSON object.")
        return False, {}, warnings, errors

    if not isinstance(config, dict):
        errors.append("feature_config must be a JSON object.")
        return False, {}, warnings, errors

    keep_header_footer = config.get("keep_header_footer", False)
    if not isinstance(keep_header_footer, bool):
        errors.append("feature_config.keep_header_footer must be a boolean.")
        keep_header_footer = False

    image: dict[str, Any] = {}
    if "image_understanding" in config:
        value = config["image_understanding"]
        if not isinstance(value, bool):
            errors.append("feature_config.image_understanding must be a boolean.")
        else:
            image["enabled"] = value
    if "image_min_area_px" in config:
        value = config["image_min_area_px"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(
                "feature_config.image_min_area_px must be a non-negative integer."
            )
        else:
            image["min_area_px"] = value
    if "image_prompt" in config:
        value = config["image_prompt"]
        if not isinstance(value, str) or not value.strip():
            errors.append("feature_config.image_prompt must be a non-empty string.")
        else:
            image["prompt"] = value.strip()
    if "image_max_tokens" in config:
        value = config["image_max_tokens"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            errors.append("feature_config.image_max_tokens must be a positive integer.")
        else:
            image["max_tokens"] = value

    for key, value in sorted(config.items()):
        if key in FEATURE_CONFIG_SUPPORTED_KEYS:
            continue
        if not isinstance(value, bool):
            errors.append(f"feature_config.{key} must be a boolean.")
        elif value:
            warnings.append(
                f"feature_config.{key}=true is accepted but ignored; open-source OXR "
                "only implements feature_config.keep_header_footer."
            )
    return keep_header_footer, image, warnings, errors


def _parse_extra(extra: str | None) -> tuple[dict[str, float], list[str]]:
    errors: list[str] = []
    if not extra:
        return {}, errors
    try:
        config = json.loads(extra)
    except json.JSONDecodeError:
        errors.append("extra must be a JSON object.")
        return {}, errors

    if not isinstance(config, dict):
        errors.append("extra must be a JSON object.")
        return {}, errors

    allowed_keys = set(MODEL_OPTION_RANGES)
    extra_keys = set(config) - allowed_keys
    for key in sorted(extra_keys):
        supported_keys = ", ".join(sorted(allowed_keys))
        errors.append(
            f"extra.{key} is unsupported; supported extra keys are {supported_keys}."
        )

    model_options: dict[str, float] = {}
    for key in MODEL_OPTION_RANGES:
        try:
            value = _parse_model_option(config, key)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if value is not None:
            model_options[key] = value
    return model_options, errors


def _parse_element_formats(
    element_formats: str | None,
) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    parsed = DEFAULT_ELEMENT_FORMATS.copy()
    if not element_formats:
        return parsed, errors

    try:
        config = json.loads(element_formats)
    except json.JSONDecodeError:
        errors.append("element_formats must be a JSON object.")
        return parsed, errors

    if not isinstance(config, dict):
        errors.append("element_formats must be a JSON object.")
        return parsed, errors

    for key, value in sorted(config.items()):
        if key not in SUPPORTED_ELEMENT_FORMATS:
            supported_keys = ", ".join(sorted(SUPPORTED_ELEMENT_FORMATS))
            errors.append(
                f"element_formats.{key} is invalid; supported keys are {supported_keys}."
            )
            continue
        if not isinstance(value, str):
            errors.append(f"element_formats.{key} must be a string.")
            continue

        normalized = value.strip().lower()
        if normalized not in SUPPORTED_ELEMENT_FORMATS[key]:
            supported_values = ", ".join(sorted(SUPPORTED_ELEMENT_FORMATS[key]))
            errors.append(
                f"element_formats.{key}={normalized} is invalid; "
                f"supported values are {supported_values}."
            )
            continue

        if normalized not in FUNCTIONAL_ELEMENT_FORMATS[key]:
            if key == "image" and normalized == "file":
                errors.append(
                    "element_formats.image=file is not supported by open-source OXR "
                    "because output_formats=zip is not implemented."
                )
            elif key == "formula":
                errors.append(
                    f"element_formats.formula={normalized} is not supported by "
                    "open-source OXR; use element_formats.formula=latex."
                )
            elif key == "table" and normalized == "image":
                errors.append(
                    "element_formats.table=image is not supported by open-source OXR; "
                    "use element_formats.table=html or markdown."
                )
            continue

        parsed[key] = normalized

    return parsed, errors


def build_options(
    output_formats: list[str] | None,
    feature_config: str | None,
    extra: str | None,
    element_formats: str | None,
) -> tuple[ParseOptions | None, list[str]]:
    """Validate a request's options; ``None`` when any of them is unusable."""
    errors: list[str] = []
    parsed_output_formats, output_errors = _parse_output_formats(output_formats)
    element_format_options, element_errors = _parse_element_formats(element_formats)
    keep_header_footer, image_config, feature_warnings, feature_errors = (
        _parse_feature_config(feature_config)
    )
    model_options, extra_errors = _parse_extra(extra)
    errors.extend(output_errors)
    errors.extend(element_errors)
    errors.extend(feature_errors)
    errors.extend(extra_errors)
    if errors:
        return None, errors
    return (
        ParseOptions(
            output_formats=parsed_output_formats,
            keep_header_footer=keep_header_footer,
            model_options=model_options,
            element_formats=element_format_options,
            image_vlm_enabled=bool(
                image_config.get("enabled", settings.pipeline.image_vlm_enabled)
            ),
            image_vlm_min_area_px=int(
                image_config.get("min_area_px", settings.pipeline.image_vlm_min_area_px)
            ),
            image_vlm_prompt=str(
                image_config.get("prompt", settings.pipeline.image_vlm_prompt)
            ),
            image_vlm_max_tokens=int(
                image_config.get("max_tokens", settings.pipeline.image_vlm_max_tokens)
            ),
            warnings=feature_warnings,
        ),
        errors,
    )


def _raise_for_options(errors: list[str]) -> None:
    raise HTTPException(status_code=422, detail=_format_issues("参数错误", errors))


def create_instance(file_bytes: bytes, file_name: str) -> Instance | None:
    """Write the upload into a fresh run folder and describe it.

    OXR parsed straight from memory and threw the bytes away, which made "what
    exactly did this answer come from?" unanswerable a minute later. Here every
    parse gets ``<upload_dir>/<document>/<run>/`` holding the source and, once it
    finishes, ``result.json``.

    Failure to write is not fatal — a read-only volume should not stop parsing —
    so the caller gets ``None`` and the run simply leaves no trace on disk.
    """
    document = document_slug(file_name)
    run = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    directory = Path(settings.pipeline.upload_dir) / document / run
    safe_name = (
        _UNSAFE_FILENAME.sub("_", Path(file_name).name).strip(". ") or "document"
    )
    try:
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / safe_name
        source.write_bytes(file_bytes)
        return Instance(document=document, run=run, directory=directory, source=source)
    except OSError:
        logger.warning(
            "Could not store the uploaded file under %s", directory, exc_info=True
        )
        return None


def write_result(instance: Instance, result: dict[str, Any]) -> Path | None:
    """Persist one run's answer beside its source, for the instances list.

    Best effort: the directory was writable moments ago, and the caller is
    holding the answer either way.
    """
    record = {
        "id": instance.id,
        "document": instance.document,
        "run": instance.run,
        "file_name": result.get("file_name") or instance.source.name,
        "source_name": instance.source.name,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "outputs": result.get("outputs", {}),
        "metadata": result.get("metadata", {}),
        "images": result.get("images") or [],
    }
    markdown = str((result.get("outputs") or {}).get("markdown") or "")
    markdown_path = instance.directory / "result.md"
    if markdown:
        try:
            markdown_path.write_text(markdown, encoding="utf-8")
        except OSError:
            logger.warning(
                "Could not write Markdown for %s", instance.id, exc_info=True
            )
            markdown_path = None
    else:
        markdown_path = None
    try:
        instance.result_path.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        logger.warning(
            "Could not write the parse result for %s", instance.id, exc_info=True
        )
    return markdown_path


def list_instances(limit: int = 50) -> list[dict[str, Any]]:
    """Recent runs, newest first, without their (potentially large) outputs."""
    root = Path(settings.pipeline.upload_dir)
    if not root.is_dir():
        return []

    found: list[tuple[float, Path]] = []
    # Two levels: <document>/<run>/result.json. A directory walk with a cap is
    # cheaper than maintaining a second index that can disagree with the disk.
    for result_path in root.glob("*/*/result.json"):
        try:
            found.append((result_path.stat().st_mtime, result_path))
        except OSError:
            continue
    found.sort(reverse=True)

    instances: list[dict[str, Any]] = []
    for _, result_path in found[: max(0, limit)]:
        try:
            record = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metadata = record.get("metadata") or {}
        instances.append(
            {
                "id": record.get("id"),
                "file_name": record.get("file_name"),
                "source_name": record.get("source_name"),
                "created": record.get("created"),
                "page_num": metadata.get("page_num"),
                "processing_time_ms": metadata.get("processing_time_ms"),
                "has_markdown": bool((record.get("outputs") or {}).get("markdown")),
            }
        )
    return instances


def _instance_or_404(document: str, run: str) -> Instance:
    if not document_slug(document) == document or not _RUN_ID.match(run):
        raise HTTPException(status_code=404, detail="Instance not found")
    directory = Path(settings.pipeline.upload_dir) / document / run
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="Instance not found")
    sources = [
        p for p in directory.iterdir() if p.is_file() and p.name != "result.json"
    ]
    source = sources[0] if sources else directory / "source"
    return Instance(document=document, run=run, directory=directory, source=source)


def read_instance(document: str, run: str) -> dict[str, Any]:
    """One stored run, outputs included."""
    instance = _instance_or_404(document, run)
    try:
        return json.loads(instance.result_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="This run has no stored result"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=500, detail="The stored result could not be read"
        ) from error


def instance_from_id(instance_id: str) -> Instance:
    """Resolve the ``<document>/<run>`` id stored on a parsing document."""
    document, _, run = instance_id.partition("/")
    if not document or not run:
        raise HTTPException(status_code=404, detail="Instance not found")
    return _instance_or_404(document, run)


def instance_source(document: str, run: str) -> Instance:
    """The stored source of one run, for the ``/source`` download route."""
    return _instance_or_404(document, run)


def render_page(instance: Instance, page_index: int) -> tuple[bytes, str]:
    """Render one source page to a browser-displayable image.

    The block overlay needs pixels and the JSON's ``page_size`` in the same
    coordinate space. PDF pages are therefore rendered at the same 150 DPI the
    pipeline uses by default; an image source is returned as-is.
    """
    suffix = instance.source.suffix.lower()
    if suffix != ".pdf":
        media_type = mimetypes.guess_type(instance.source.name)[0] or "image/png"
        return instance.source.read_bytes(), media_type
    import cv2

    images = pdf_to_images(
        instance.source.read_bytes(),
        dpi=150,
        page_range=(page_index + 1, page_index + 1),
    )
    if not images:
        raise HTTPException(status_code=404, detail="Page not found")
    ok, encoded = cv2.imencode(".png", images[0])
    if not ok:
        raise HTTPException(status_code=500, detail="Could not render the page")
    return encoded.tobytes(), "image/png"


def delete_instance(document: str, run: str) -> None:
    """Remove one run's folder (source, answer and images)."""
    instance = _instance_or_404(document, run)
    try:
        shutil.rmtree(instance.directory)
    except OSError as error:
        raise HTTPException(
            status_code=500, detail="The run could not be removed"
        ) from error


async def ensure_ready() -> None:
    """Fail fast, with the same public wording OXR uses, when no backend works."""
    await parsing_settings.ensure_current()
    try:
        await model_backend.ensure_ready()
    except Exception as error:  # noqa: BLE001 - translated to a 503 below
        logger.warning("Parsing backend is not ready: %s", type(error).__name__)
        raise HTTPException(
            status_code=get_error_status_code(error, 503),
            detail=get_public_error_message(error),
        ) from error


async def parse_now(
    file_bytes: bytes,
    file_name: str,
    options: ParseOptions,
    instance: Instance | None = None,
    *,
    dpi: int = 150,
    page_range: tuple[int, int] | None = None,
    progress_cb: Any = None,
    cancel_event: asyncio.Event | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse one document in the request; returns ``{file_name, outputs, metadata}``.

    ``instance`` is where :func:`create_instance` put the source. When it is
    given the answer is written beside that source as well, so the instances
    list can show the run after the request that produced it has ended.
    """
    await ensure_ready()
    try:
        result = await process_document(
            file_bytes,
            file_name,
            options.output_formats,
            keep_header_footer=options.keep_header_footer,
            model_options=options.model_options,
            element_formats=options.element_formats,
            dpi=dpi,
            page_range=page_range,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
    except (ParsingCancelledError, asyncio.CancelledError):
        raise
    except Exception as error:  # noqa: BLE001 - translated to an HTTP status
        logger.warning(
            "Document parsing failed (file=%s, error_type=%s)",
            file_name,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=get_error_status_code(error, 500),
            detail=get_public_error_message(error),
        ) from error
    metadata = result["metadata"]
    if extra_metadata:
        metadata.update(extra_metadata)
    images: list[dict[str, Any]] = []
    if instance is not None:
        images = await understand_result_images(
            result,
            prompt=options.image_vlm_prompt,
            min_area_px=options.image_vlm_min_area_px,
            enabled=options.image_vlm_enabled,
            max_tokens=options.image_vlm_max_tokens,
            model_options=options.model_options,
        )
        metadata["image_count"] = len(images)
        metadata["images_interpreted"] = sum(
            1 for image in images if image.get("vlm_status") == "succeeded"
        )
    if instance is not None:
        metadata["instance_id"] = instance.id
        metadata["stored_path"] = str(instance.source)
        markdown_path = write_result(
            instance,
            {
                "file_name": result["file_name"],
                "outputs": result["outputs"],
                "metadata": metadata,
                "images": images,
            },
        )
        if markdown_path is not None:
            metadata["parsed_md_path"] = str(markdown_path)
    return {
        "file_name": result["file_name"],
        "outputs": result["outputs"],
        "metadata": metadata,
        "images": images,
    }


async def submit_job(file_bytes: bytes, file_name: str, options: ParseOptions) -> str:
    """Queue a parse; the work runs in the background on this process."""
    await ensure_ready()
    task_id = str(uuid.uuid4())
    await task_store.create(task_id, file_name)
    return task_id


#: Strong references to in-flight job tasks. ``asyncio.create_task`` leaves only
#: a weak reference in the event loop, so a task nothing else references may be
#: garbage-collected mid-flight — which looks exactly like a job stuck at
#: "processing" that never reaches the model. This set is that reference.
_job_tasks: set[asyncio.Task[None]] = set()


def start_job(
    task_id: str,
    file_bytes: bytes,
    file_name: str,
    options: ParseOptions,
    instance: Instance | None = None,
) -> None:
    """Run :func:`run_job` in the background, keeping it alive until it ends."""
    task = asyncio.create_task(
        run_job(task_id, file_bytes, file_name, options, instance)
    )
    _job_tasks.add(task)
    task.add_done_callback(_job_tasks.discard)


async def run_job(
    task_id: str,
    file_bytes: bytes,
    file_name: str,
    options: ParseOptions,
    instance: Instance | None = None,
) -> None:
    """Background body of :func:`submit_job`. Never raises."""
    await task_store.set_processing(task_id)
    try:
        result = await parse_now(file_bytes, file_name, options, instance)
        await task_store.set_success(
            task_id,
            {
                "file_name": result["file_name"],
                "result": {
                    "file_name": result["file_name"],
                    "outputs": result["outputs"],
                },
                "metadata": result["metadata"],
            },
        )
    except HTTPException as error:
        await task_store.set_failed(task_id, str(error.detail))
    except Exception:  # noqa: BLE001 - the job record is the only reporter
        logger.exception("Document parsing job failed (task_id=%s)", task_id)
        await task_store.set_failed(
            task_id, "Unable to process this document. Please try again later."
        )


async def capabilities() -> dict[str, Any]:
    """What the form needs: the backend state and the accepted option values."""
    described = await parsing_settings.status()
    # ``model_backend.describe()`` nests the state one level down
    # (``status.state``); the form wants it flat, and only the flat shape is
    # declared in ``ParsingCapabilities``.
    state = described.get("status") or {}
    return {
        "mode": described.get("mode", "none"),
        "state": state.get("state", "unknown"),
        "detail": state.get("detail"),
        "error": state.get("error"),
        "model_url": described.get("model_url"),
        "layout_url": described.get("layout_url"),
        "ready": bool(described.get("ready")),
        "output_formats": sorted(SUPPORTED_OUTPUT_FORMATS),
        "element_formats": {
            key: sorted(values) for key, values in FUNCTIONAL_ELEMENT_FORMATS.items()
        },
        "element_format_defaults": DEFAULT_ELEMENT_FORMATS,
        "model_options": sorted(MODEL_OPTION_RANGES),
        "image_understanding": described.get("image_understanding")
        or {
            "enabled": settings.pipeline.image_vlm_enabled,
            "min_area_px": settings.pipeline.image_vlm_min_area_px,
            "prompt": settings.pipeline.image_vlm_prompt,
            "max_tokens": settings.pipeline.image_vlm_max_tokens,
            "concurrency": settings.pipeline.image_vlm_concurrency,
        },
    }


async def test_backend(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe the recognition backend, optionally with unsaved settings."""
    if config is None:
        await parsing_settings.ensure_current()
        result = await model_backend.test()
    else:
        result = await model_backend.test(_model_config_from(config))
    return _with_ok(result)


async def test_layout(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe the D-FINE layout service."""
    if config is None:
        await parsing_settings.ensure_current()
        result = await model_backend.test_layout()
    else:
        result = await model_backend.test_layout(_layout_config_from(config))
    return _with_ok(result)


def _with_ok(result: dict[str, Any]) -> dict[str, Any]:
    """Make the success flag explicit.

    These probes answer 200 even when the service is down; the browser used to
    read that as success. ``ok`` is the single field it can trust.
    """
    result = dict(result)
    result["ok"] = bool(result.get("reachable"))
    if not result["ok"]:
        result.setdefault("detail", result.get("error") or "Connection failed")
    return result


async def health() -> dict[str, Any]:
    """A combined, user-triggered readiness probe for the parsing page."""
    backend = await test_backend()
    layout = await test_layout()
    return {
        "ok": bool(backend.get("ok") and layout.get("ok")),
        "backend": backend,
        "layout": layout,
    }


def error_code_for(error: Exception) -> str:
    """Stable code for the UI; details stay in the server log."""
    from all_ontology.parsing.pipeline.errors import PipelineError

    if isinstance(error, asyncio.CancelledError):
        return "CANCELLED"
    if isinstance(error, HTTPException):
        if error.status_code == 422:
            return "INVALID_OPTIONS"
        if error.status_code == 413:
            return "FILE_TOO_LARGE"
        if error.status_code == 415:
            return "UNSUPPORTED_FILE"
        if error.status_code == 503:
            return "BACKEND_UNAVAILABLE"
    if isinstance(error, PipelineError):
        if error.status_code == 503:
            return "BACKEND_UNAVAILABLE"
        if "decode" in str(error).lower() or "page images" in str(error).lower():
            return "INVALID_DOCUMENT"
        if "timeout" in str(error).lower():
            return "TIMEOUT"
    if isinstance(error, TimeoutError):
        return "TIMEOUT"
    return "PARSE_FAILED"


def _model_config_from(config: dict[str, Any]):
    from all_ontology.parsing.config.model_settings import ModelBackendSettings

    return ModelBackendSettings.model_validate(config)


def _layout_config_from(config: dict[str, Any]):
    from all_ontology.parsing.config.model_settings import LayoutServiceSettings

    return LayoutServiceSettings.model_validate(config)
