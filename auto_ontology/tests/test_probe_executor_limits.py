# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The probe executor bounds its statements in the target dialect's syntax."""

from __future__ import annotations

from typing import Any

import pandas as pd

from auto_ontology.retrieval.text_to_sql.db_probe.executor import ProbeExecutor


class _RecordingConnector:
    def __init__(self, dialect: str) -> None:
        self.dialect = dialect
        self.statements: list[str] = []

    def execute(self, sql: str, **_kwargs: Any) -> pd.DataFrame:
        self.statements.append(sql)
        return pd.DataFrame({"value": [1]})


def test_probe_limit_is_spelled_limit_for_postgres() -> None:
    connector = _RecordingConnector("postgres")
    executor = ProbeExecutor(connector=connector, max_rows=100)

    result = executor.run("SELECT value FROM public.t", purpose="test")

    assert result["ok"] is True
    assert connector.statements == ["SELECT value FROM public.t LIMIT 100"]


def test_probe_limit_becomes_top_for_sql_server() -> None:
    connector = _RecordingConnector("tsql")
    executor = ProbeExecutor(connector=connector, max_rows=100)

    result = executor.run("SELECT value FROM [dbo].[t]", purpose="test")

    assert result["ok"] is True
    assert connector.statements == ["SELECT TOP 100 value FROM [dbo].[t]"]
