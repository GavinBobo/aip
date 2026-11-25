# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Knowledge retrieval evals over a network's question set."""

from __future__ import annotations

from typing import Any

from all_ontology.dal import knowledge as knowledge_dal
from all_ontology.knowledge.context import retrieve_knowledge_context


def run_evals(network_id: str, *, created_by: str | None = None) -> dict[str, Any]:
    cases = knowledge_dal.list_eval_cases(network_id)
    details: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        context = retrieve_knowledge_context(
            str(case["question"]), network_id=network_id, limit=20
        )
        folded = context.casefold()
        expected_concepts = [
            str(item).strip()
            for item in case.get("expected_concepts") or []
            if str(item).strip()
        ]
        expected_facts = [
            str(item).strip()
            for item in case.get("expected_facts") or []
            if str(item).strip()
        ]
        missing_concepts = [
            item for item in expected_concepts if item.casefold() not in folded
        ]
        missing_facts = [
            item for item in expected_facts if item.casefold() not in folded
        ]
        case_passed = not missing_concepts and not missing_facts
        passed += int(case_passed)
        details.append(
            {
                "case_id": case["id"],
                "question": case["question"],
                "passed": case_passed,
                "missing_concepts": missing_concepts,
                "missing_facts": missing_facts,
                "context_chars": len(context),
            }
        )
    return knowledge_dal.save_eval_run(
        network_id=network_id,
        total=len(cases),
        passed=passed,
        details=details,
        created_by=created_by,
    )
