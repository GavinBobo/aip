# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import-direction guard: only the HTTP layer may depend on the HTTP layer."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_non_server_packages_do_not_import_server() -> None:
    violations: list[str] = []
    for path in _ROOT.rglob("*.py"):
        relative = path.relative_to(_ROOT)
        if relative.parts[0] == "server" or "tests" in relative.parts:
            continue
        for module in _imported_modules(path):
            if module == "all_ontology.server" or module.startswith(
                "all_ontology.server."
            ):
                violations.append(f"{relative}: {module}")

    assert not violations, "Non-server packages import the HTTP layer:\n" + "\n".join(
        violations
    )


def test_dal_does_not_import_fastapi() -> None:
    violations: list[str] = []
    for path in (_ROOT / "dal").rglob("*.py"):
        if "tests" in path.parts:
            continue
        for module in _imported_modules(path):
            if module == "fastapi" or module.startswith("fastapi."):
                violations.append(
                    f"{path.relative_to(_ROOT)}: {module}"
                )

    assert not violations, "DAL imports the web framework:\n" + "\n".join(violations)
