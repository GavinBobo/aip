# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request-option validation and the job store, without a model or a database.

The validators were carried over from OXR unchanged on purpose: the frontend
renders their messages, so a rewording here is a product change. These tests
pin the behaviour a caller sees, not the implementation.
"""

from __future__ import annotations

import asyncio

import pytest

from all_ontology.parsing import service
from all_ontology.parsing.tasks import MemoryTaskStore


def test_omitted_options_use_the_defaults() -> None:
    options, errors = service.build_options(None, None, None, None)
    assert errors == []
    assert options is not None
    assert options.output_formats == ["markdown", "json"]
    assert options.keep_header_footer is False
    assert options.element_formats == service.DEFAULT_ELEMENT_FORMATS


def test_an_unknown_output_format_is_rejected_by_name() -> None:
    options, errors = service.build_options(["markdown", "docx"], None, None, None)
    assert options is None
    assert any("docx" in error for error in errors)


def test_zip_says_why_it_is_missing() -> None:
    _, errors = service.build_options(["zip"], None, None, None)
    assert any("zip packaging is not implemented" in error for error in errors)


def test_model_options_are_range_checked() -> None:
    ok, errors = service.build_options(None, None, '{"temperature": 0.3}', None)
    assert errors == [] and ok is not None and ok.model_options == {"temperature": 0.3}

    too_hot, errors = service.build_options(None, None, '{"temperature": 3}', None)
    assert too_hot is None
    assert any("between" in error for error in errors)


def test_an_unsupported_extra_key_is_named() -> None:
    options, errors = service.build_options(None, None, '{"seed": 1}', None)
    assert options is None
    assert any("extra.seed" in error for error in errors)


def test_element_formats_reject_values_that_do_not_exist() -> None:
    options, errors = service.build_options(None, None, None, '{"table": "csv"}')
    assert options is None
    assert any("element_formats.table" in error for error in errors)


def test_keep_header_footer_is_read_from_the_feature_config() -> None:
    options, errors = service.build_options(
        None, '{"keep_header_footer": true}', None, None
    )
    assert errors == [] and options is not None
    assert options.keep_header_footer is True


def test_an_unimplemented_feature_flag_is_a_warning_not_an_error() -> None:
    options, errors = service.build_options(
        None, '{"strip_watermark": true}', None, None
    )
    assert errors == [] and options is not None
    assert any("strip_watermark" in warning for warning in options.warnings)


def test_the_job_store_records_the_lifecycle() -> None:
    async def scenario() -> None:
        store = MemoryTaskStore()
        await store.create("t1", "report.pdf")
        created = await store.get("t1")
        assert created is not None
        assert created["status"] == "queuing"
        assert created["instance"]

        await store.set_processing("t1")
        assert (await store.get("t1"))["status"] == "processing"

        await store.set_success(
            "t1",
            {
                "file_name": "report.pdf",
                "result": {"file_name": "report.pdf", "outputs": {"markdown": "# hi"}},
                "metadata": {"pages": 1},
            },
        )
        done = await store.get("t1")
        assert done is not None
        assert done["status"] == "success"
        assert done["result"]["outputs"]["markdown"] == "# hi"
        assert done["metadata"] == {"pages": 1}

        await store.set_failed("t1", "boom")
        failed = await store.get("t1")
        assert failed is not None and failed["status"] == "failed"
        assert failed["error"] == "boom"

        assert await store.get("missing") is None

    asyncio.run(scenario())


def test_an_unreachable_probe_is_never_reported_as_ok() -> None:
    """The browser reads ``ok``; HTTP 200 alone must not mean success."""
    result = service._with_ok(
        {"mode": "vllm", "reachable": False, "error": "connection refused"}
    )
    assert result["ok"] is False
    assert result["detail"] == "connection refused"


def test_a_started_job_is_referenced_until_it_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A background parse must not be garbage-collected mid-flight.

    ``asyncio.create_task`` keeps only a weak reference; a job that nothing else
    holds looks exactly like one stuck at "processing". ``start_job`` adds a
    strong reference and drops it when the task ends.
    """
    finished: list[str] = []

    async def fake_run_job(task_id: str, *_: object) -> None:
        await asyncio.sleep(0)
        finished.append(task_id)

    monkeypatch.setattr(service, "run_job", fake_run_job)

    async def scenario() -> None:
        service.start_job("t-1", b"", "a.png", service.ParseOptions())
        assert len(service._job_tasks) == 1
        await asyncio.sleep(0.05)
        assert finished == ["t-1"]
        assert len(service._job_tasks) == 0

    asyncio.run(scenario())
