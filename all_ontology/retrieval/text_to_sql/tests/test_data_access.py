# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.retrieval.text_to_sql.agents.sql_parse_validation import (
    denied_tables,
)


def test_unscoped_caller_denies_nothing() -> None:
    assert denied_tables(["t1", "t2"], None) == []


def test_allowed_tables_pass() -> None:
    assert denied_tables(["t1", "t1"], ["t1", "t2"]) == []


def test_out_of_scope_tables_are_reported_once() -> None:
    assert denied_tables(["t1", "secret", "secret"], ["t1"]) == ["secret"]


def test_an_empty_allow_list_denies_every_table() -> None:
    assert denied_tables(["t1"], []) == ["t1"]
