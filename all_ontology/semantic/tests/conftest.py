# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared test doubles for semantic compilation tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_value_profile_writes():
    """Keep value-profile persistence out of tests that use a fake warehouse."""
    with (
        patch("all_ontology.semantic.visit_enter.store_column_distinct_ratios"),
        patch("all_ontology.semantic.visit_enter.store_column_distinct_values"),
    ):
        yield
