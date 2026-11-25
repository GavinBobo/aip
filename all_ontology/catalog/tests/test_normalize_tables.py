# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pandas as pd

from all_ontology.catalog.normalize import normalize_tables


def test_created_is_utc_with_second_precision() -> None:
    frame = pd.DataFrame(
        {
            "table_schema": ["public"],
            "table_name": ["orders"],
            "table_type": ["BASE TABLE"],
            "created": ["2024-01-01T08:30:00.123456+08:00"],
        }
    )

    result = normalize_tables(frame)

    created = result["created"].iloc[0]
    assert created.microsecond == 0
    assert created.utcoffset().total_seconds() == 0
    assert created.hour == 0


def test_missing_created_column_is_tolerated() -> None:
    frame = pd.DataFrame(
        {
            "table_schema": ["public"],
            "table_name": ["orders"],
            "table_type": ["BASE TABLE"],
        }
    )

    result = normalize_tables(frame)

    assert result["table_name"].tolist() == ["orders"]
