# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``with_row_limit`` must stay a no-op for every dialect but T-SQL."""

from __future__ import annotations

import pytest

from auto_ontology.utils.sql_limits import with_row_limit


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "snowflake", "sqlite", None])
def test_limit_clause_is_appended_for_limit_style_dialects(
    dialect: str | None,
) -> None:
    assert with_row_limit("SELECT 1", 10, dialect) == "SELECT 1 LIMIT 10"


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "sqlite", None])
def test_existing_limit_is_not_duplicated(dialect: str | None) -> None:
    sql = "SELECT * FROM t LIMIT 5"

    assert with_row_limit(sql, 100, dialect) == sql


def test_tsql_uses_top_because_it_has_no_limit_clause() -> None:
    assert with_row_limit("SELECT * FROM [dbo].[t]", 1000, "tsql") == (
        "SELECT TOP 1000 * FROM [dbo].[t]"
    )


def test_tsql_rewrites_an_existing_limit_instead_of_keeping_it() -> None:
    # Profiling hands over queries that already carry LIMIT; T-SQL would reject
    # that clause outright, so the rewrite has to replace it, not skip it.
    assert with_row_limit(
        "SELECT DISTINCT [name] FROM [dbo].[t] LIMIT 6", 6, "tsql"
    ) == ("SELECT DISTINCT TOP 6 [name] FROM [dbo].[t]")


def test_tsql_keeps_an_explicit_top() -> None:
    assert with_row_limit("SELECT TOP 5 * FROM t", 1000, "tsql") == (
        "SELECT TOP 5 * FROM t"
    )


def test_tsql_statement_sqlglot_cannot_parse_is_left_alone() -> None:
    sql = "SELECT FROM WHERE"

    assert with_row_limit(sql, 10, "tsql") == sql
