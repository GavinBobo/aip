# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.server.erd.import_export import _place_nodes


def test_positionless_import_starts_in_the_current_viewport() -> None:
    canvas = {
        "nodes": [],
        "viewport": {"x": -2000, "y": -1200, "zoom": 2},
    }
    nodes = [{"name": "public.customers"}, {"name": "public.orders"}]

    placed = _place_nodes(nodes, canvas)

    assert placed[0]["x"] >= 1000
    assert placed[0]["y"] >= 600


def test_positionless_import_keeps_an_existing_table_in_place() -> None:
    canvas = {
        "nodes": [{"name": "public.customers", "x": 55, "y": 66}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    nodes = [{"name": "public.customers"}, {"name": "public.orders"}]

    placed = _place_nodes(nodes, canvas)

    assert (placed[0]["x"], placed[0]["y"]) == (55, 66)
    assert placed[1]["x"] > placed[0]["x"] or placed[1]["y"] > placed[0]["y"]
