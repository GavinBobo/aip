# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import normalisation: a hand-edited document must not 500 the endpoint."""

from __future__ import annotations

import pytest

from all_ontology.server.erd.import_export import _normalise_import_nodes


def test_bad_coordinates_become_zero_with_a_warning() -> None:
    warnings: list[str] = []

    nodes = _normalise_import_nodes(
        [{"name": "public.t", "x": "left", "y": None}], {}, warnings
    )

    assert nodes[0]["x"] == 0.0
    assert nodes[0]["y"] == 0.0
    assert any("is not a number" in warning for warning in warnings)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_coordinates_become_zero(value: str) -> None:
    warnings: list[str] = []

    nodes = _normalise_import_nodes([{"name": "public.t", "x": value}], {}, warnings)

    assert nodes[0]["x"] == 0.0
    assert any("is not finite" in warning for warning in warnings)


def test_a_string_where_columns_belong_is_dropped_not_stored() -> None:
    warnings: list[str] = []

    nodes = _normalise_import_nodes(
        [{"name": "public.t", "columns": "id int", "indexes": {}}], {}, warnings
    )

    assert nodes[0]["columns"] is None
    assert nodes[0]["indexes"] is None
    assert len([w for w in warnings if "must be a list" in w]) == 2


def test_a_well_formed_node_is_passed_through() -> None:
    warnings: list[str] = []
    columns = [{"name": "id", "data_type": "bigint"}]

    nodes = _normalise_import_nodes(
        [{"name": "public.t", "x": 12.5, "y": -3, "columns": columns}], {}, warnings
    )

    assert warnings == []
    assert nodes[0]["x"] == 12.5
    assert nodes[0]["y"] == -3.0
    assert nodes[0]["columns"] == columns
