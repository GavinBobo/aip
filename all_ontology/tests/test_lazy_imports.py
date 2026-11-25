# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import-cost guards for the lazy ``utils`` and ``connectors`` packages.

A subprocess is the only honest way to test this: by the time the suite runs,
other test modules have already imported pandas and the drivers into this
process, so ``sys.modules`` here says nothing about what one import costs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _run(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(_REPO)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_importing_utils_does_not_load_the_embedding_stack() -> None:
    output = _run(
        "import sys; import all_ontology.utils; "
        "print('pandas' in sys.modules, 'openai' in sys.modules, "
        "'all_ontology.utils.embedding' in sys.modules)"
    )

    assert output == "False False False"


def test_importing_connectors_does_not_load_any_driver() -> None:
    output = _run(
        "import sys; import all_ontology.connectors; "
        "print('snowflake.connector' in sys.modules, 'pandas' in sys.modules, "
        "'all_ontology.connectors.registry' in sys.modules)"
    )

    assert output == "False False False"


def test_public_names_still_resolve() -> None:
    output = _run(
        "from all_ontology.utils import dump_sample_values; "
        "from all_ontology.connectors import get_connectors, PostgresDatabase; "
        "print(callable(dump_sample_values), callable(get_connectors), "
        "PostgresDatabase.__name__)"
    )

    assert output == "True True PostgresDatabase"


def test_registry_lookup_imports_only_the_requested_driver() -> None:
    output = _run(
        "import sys; "
        "from all_ontology.connectors.registry import CONNECTOR_REGISTRY; "
        "print(CONNECTOR_REGISTRY['postgres'].__name__, "
        "'snowflake.connector' in sys.modules)"
    )

    assert output == "PostgresDatabase False"
