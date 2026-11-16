# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persisted LLM settings overlay the environment before model clients load."""

from __future__ import annotations

import os

from pytest import MonkeyPatch

from all_ontology.infra import model_settings


def test_saved_values_override_only_the_conversational_triplets(
    monkeypatch: MonkeyPatch,
) -> None:
    for prefix in ("REASONING", "NON_REASONING"):
        for field in ("ENDPOINT", "API_KEY", "MODEL"):
            monkeypatch.delenv(f"{prefix}_{field}", raising=False)
    monkeypatch.delenv("EMBED_ENDPOINT", raising=False)
    monkeypatch.delenv("RERANK_ENDPOINT", raising=False)

    model_settings.apply_llm_settings(
        {
            model_settings.LLM_BASE_URL_KEY: "https://llm.example/v1",
            model_settings.LLM_API_KEY_KEY: "sk-new",
            model_settings.LLM_MODEL_KEY: "vendor/model",
        }
    )

    for prefix in ("REASONING", "NON_REASONING"):
        assert os.environ[f"{prefix}_ENDPOINT"] == "https://llm.example/v1"
        assert os.environ[f"{prefix}_API_KEY"] == "sk-new"
        assert os.environ[f"{prefix}_MODEL"] == "vendor/model"
    # A chat endpoint is not necessarily an embedding/rerank endpoint.
    assert "EMBED_ENDPOINT" not in os.environ
    assert "RERANK_ENDPOINT" not in os.environ


def test_blank_saved_fields_leave_the_environment_alone(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("REASONING_ENDPOINT", "https://env.example/v1")
    monkeypatch.setenv("REASONING_MODEL", "env/model")
    monkeypatch.setenv("REASONING_API_KEY", "env-key")

    model_settings.apply_llm_settings(
        {
            model_settings.LLM_BASE_URL_KEY: "",
            model_settings.LLM_API_KEY_KEY: "",
            model_settings.LLM_MODEL_KEY: " ",
        }
    )

    assert os.environ["REASONING_ENDPOINT"] == "https://env.example/v1"
    assert os.environ["REASONING_MODEL"] == "env/model"
    assert os.environ["REASONING_API_KEY"] == "env-key"
