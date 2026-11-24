# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add parsing stage

Revision ID: 1f6c8a2e4d7b
Revises: 3c8f1a6d9b2e
Create Date: 2026-11-24 12:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "1f6c8a2e4d7b"
down_revision: str | Sequence[str] | None = "3c8f1a6d9b2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "parsing_document", sa.Column("stage", sa.Text(), nullable=True)
    )
    op.add_column("parsing_run", sa.Column("stage", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("parsing_run", "stage")
    op.drop_column("parsing_document", "stage")
