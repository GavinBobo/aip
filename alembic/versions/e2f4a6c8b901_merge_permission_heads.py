# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""merge permission and expiry heads

Revision ID: e2f4a6c8b901
Revises: e1f3a5c7b902, f8a0c2e4d657
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union


revision: str = "e2f4a6c8b901"
down_revision: Union[str, Sequence[str], None] = (
    "e1f3a5c7b902",
    "f8a0c2e4d657",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the two independent permission-model branches."""


def downgrade() -> None:
    """Split back into the two parent heads."""
