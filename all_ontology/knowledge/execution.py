# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Safe action execution planning.

Tool execution belongs in an isolated execution service. This module builds and
persists the plan the executor would receive: bound object, mounted capability,
parameters, and related certified risks. It never calls an external tool.
"""

from __future__ import annotations

from typing import Any

from all_ontology.dal import knowledge as knowledge_dal


def prepare_action_execution(
    action_id: str,
    *,
    parameters: dict[str, Any],
    created_by: str | None,
) -> dict[str, Any]:
    action = knowledge_dal.get_action(action_id)
    if action is None:
        raise ValueError("Knowledge action not found.")
    definitions = [
        item for item in action.get("parameters") or [] if isinstance(item, dict)
    ]
    required = [
        str(item.get("name"))
        for item in definitions
        if item.get("name") and bool(item.get("required", False))
    ]
    missing = [name for name in required if parameters.get(name) in (None, "")]
    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(missing)}")

    network_id = str(action["network_id"])
    risks = [
        {
            "name": item["name"],
            "severity": item.get("severity"),
            "mitigation": item.get("mitigation"),
        }
        for item in knowledge_dal.list_risks(network_id)
        if item.get("status") in {"reviewed", "certified"}
        and item.get("related_concept_id") == action.get("bound_concept_id")
    ]
    capabilities = action.get("capabilities") or []
    capability = capabilities[0] if capabilities else None
    warnings: list[str] = []
    if capability is None:
        warnings.append(
            "The action has no mounted capability; only a plan can be produced, not executed."
        )
    if risks:
        warnings.append(
            "This action is linked to a certified risk; review the mitigation before executing."
        )

    plan = {
        "execution_mode": "dry_run",
        "action_id": action_id,
        "action_name": action["name"],
        "action_intent": action.get("action_intent"),
        "bound_concept_id": action.get("bound_concept_id"),
        "bound_concept_name": action.get("bound_concept_name"),
        "parameters": parameters,
        "capability": capability,
        "risks": risks,
        "warnings": warnings,
    }
    execution = knowledge_dal.create_action_execution(
        network_id=network_id,
        action_id=action_id,
        parameters=parameters,
        plan=plan,
        created_by=created_by,
    )
    return {**execution, "plan": plan}
