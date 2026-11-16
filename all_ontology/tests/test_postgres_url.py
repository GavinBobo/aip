# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The connection URL the app builds, and the one asyncpg needs.

A company-hosted Postgres usually mandates TLS while the bundled development one
does not, so ``POSTGRES_SSLMODE`` is the single switch. It has to land as
``sslmode=`` for libpq/psycopg/Prisma and as ``ssl=`` for asyncpg — the two
drivers disagree, and getting it wrong fails at connect time rather than here.
"""

from __future__ import annotations

import pytest

from all_ontology.infra.postgres import get_postgres_connection_string
from all_ontology.vdb.postgres import _to_async_url


@pytest.fixture(autouse=True)
def postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "svc_all_ontology")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DATABASE", "all_ontology")
    monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)


def test_the_url_has_no_tls_parameter_by_default() -> None:
    assert (
        get_postgres_connection_string()
        == "postgresql://svc_all_ontology:secret@db.internal:5433/all_ontology"
    )


def test_the_tls_mode_is_appended_when_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_SSLMODE", " verify-full ")
    assert get_postgres_connection_string().endswith("?sslmode=verify-full")


def test_asyncpg_gets_the_ssl_spelling() -> None:
    url = "postgresql://u:p@h:5432/db?sslmode=require"
    assert _to_async_url(url) == "postgresql+asyncpg://u:p@h:5432/db?ssl=require"


def test_asyncpg_url_is_left_alone_without_tls() -> None:
    url = "postgresql://u:p@h:5432/db"
    assert _to_async_url(url) == "postgresql+asyncpg://u:p@h:5432/db"


def test_an_already_async_url_keeps_its_scheme() -> None:
    url = "postgresql+asyncpg://u:p@h:5432/db?sslmode=require"
    assert _to_async_url(url) == "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
