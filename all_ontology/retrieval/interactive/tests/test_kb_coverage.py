# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import all_ontology.retrieval.interactive.kb_coverage as kb
from all_ontology.retrieval.interactive.kb_coverage import _inject_descendants


def entry(name: str) -> str:
    return f"- {name}\n  Description: {name}"


def test_descendants_stop_at_three_levels_and_cap_each_parent() -> None:
    children_map = {
        "root": [entry(f"child{index}") for index in range(7)],
        "child0": [entry("grand0")],
        "grand0": [entry("great0")],
        "great0": [entry("too_deep")],
    }
    seen: set[str] = set()
    lines: list[str] = []

    _inject_descendants("root", children_map, seen, lines)

    names = [line.splitlines()[0][2:] for line in lines]
    # Depth-first, document order, at most five children per parent, three levels.
    assert names == [
        "child0",
        "grand0",
        "great0",
        "child1",
        "child2",
        "child3",
        "child4",
    ]
    assert "too_deep" not in names


def test_covered_parent_pulls_its_descendants(monkeypatch) -> None:
    formatted_kb = "\n".join([entry("Root"), entry("Child"), entry("Grand")])
    children_map = {
        "Root": [entry("Child")],
        "Child": [entry("Grand")],
        "Grand": [entry("Great")],
        "Great": [entry("TooDeep")],
    }
    monkeypatch.setattr(
        kb, "safe_invoke_text_nr", lambda prompt: "alpha: YES ;; Root"
    )

    covered, text, mapping = kb._filter_covered_by_external_knowledge(
        ["alpha"], formatted_kb, children_map=children_map
    )

    assert covered == {"alpha"}
    assert mapping == {"root": ["alpha"]}
    for name in ("Root", "Child", "Grand", "Great"):
        assert name in text
    assert "TooDeep" not in text
