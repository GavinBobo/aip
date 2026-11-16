# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Zone-scoped pair mode's metadata-only relationship candidates."""

from __future__ import annotations

from all_ontology.server.exploration import service


def _column(table_id: str, name: str, data_type: str = "VARCHAR") -> dict[str, str]:
    return {
        "id": f"{table_id}:{name}",
        "table_id": table_id,
        "name": name,
        "data_type": data_type,
    }


def test_date_columns_become_a_candidate_relationship() -> None:
    candidate = service._column_candidate(
        _column("a", "日期", "TIMESTAMP"),
        _column("b", "订单日期", "TIMESTAMP"),
    )

    assert candidate is not None
    assert candidate["match"] == "contains"
    assert candidate["source_column"] == "日期"
    assert candidate["target_column"] == "订单日期"


def test_two_measure_columns_are_not_treated_as_a_join() -> None:
    assert (
        service._column_candidate(
            _column("a", "数量", "BIGINT"),
            _column("b", "数量", "BIGINT"),
        )
        is None
    )


def test_candidates_skip_pairs_that_already_have_a_confirmed_edge() -> None:
    nodes = [{"id": "a"}, {"id": "b"}]
    columns = [
        _column("a", "客户ID"),
        _column("b", "客户"),
    ]

    suggestions = service._candidate_suggestions(
        nodes, columns, existing_pairs={("a", "b")}
    )

    assert suggestions == []
