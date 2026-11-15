# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime model backend settings shared by the server and Settings UI."""

from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


BackendMode = Literal["none", "local", "vllm"]


def _validate_http_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an absolute http:// or https:// URL")
    return value


class LocalModelSettings(BaseModel):
    """A local transformers gateway managed by the OXR server on demand."""

    model_config = ConfigDict(validate_assignment=True)

    model_dir: str = "models/OXR-1.0"
    python: Optional[str] = None
    host: str = "127.0.0.1"
    port: int = Field(default=8080, gt=0, le=65535)
    threads: int = Field(default=0, ge=0)
    dtype: Literal["float32", "bfloat16"] = "float32"
    startup_timeout: int = Field(default=900, gt=0)
    max_tokens: int = Field(default=8192, gt=0)

    @field_validator("model_dir")
    @classmethod
    def _model_dir_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_dir must not be empty")
        return value.strip()

    @field_validator("host")
    @classmethod
    def _host_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("host must not be empty")
        return value.strip()


class VLLMModelSettings(BaseModel):
    """An OpenAI-compatible vLLM endpoint."""

    model_config = ConfigDict(validate_assignment=True)

    url: str = "http://127.0.0.1:8080/v1"
    model_name: str = "oxr"
    api_key: Optional[str] = None
    max_concurrency: int = Field(default=16, gt=0)
    timeout: int = Field(default=300, gt=0)
    connect_timeout: int = Field(default=10, gt=0)
    retry_times: int = Field(default=2, gt=0)

    _validate_url = field_validator("url")(_validate_http_url)

    @field_validator("model_name")
    @classmethod
    def _model_name_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_name must not be empty")
        return value.strip()


class LayoutServiceSettings(BaseModel):
    """The separate D-FINE layout-analysis HTTP service."""

    model_config = ConfigDict(validate_assignment=True)

    url: str = "http://127.0.0.1:8081"
    batch_size: int = Field(default=8, gt=0)
    max_concurrency: int = Field(default=2, gt=0)
    timeout: int = Field(default=120, gt=0)
    retry_times: int = Field(default=3, gt=0)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    nms_iou_threshold: Optional[float] = Field(default=0.6, ge=0.0, le=1.0)
    provides_reading_order: bool = False

    _validate_url = field_validator("url")(_validate_http_url)


class ModelBackendSettings(BaseModel):
    """Persisted choice of the active recognition backend."""

    model_config = ConfigDict(validate_assignment=True)

    mode: BackendMode = "none"
    local: LocalModelSettings = Field(default_factory=LocalModelSettings)
    vllm: VLLMModelSettings = Field(default_factory=VLLMModelSettings)
    layout: LayoutServiceSettings = Field(default_factory=LayoutServiceSettings)
