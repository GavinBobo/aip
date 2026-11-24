# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add parsing document processing duration

Revision ID: 3c8f1a6d9b2e
Revises: 7b2d9e4c1a6f
Create Date: 2026-11-24 12:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "3c8f1a6d9b2e"
down_revision: str | Sequence[str] | None = "7b2d9e4c1a6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "parsing_document",
        sa.Column("processing_time_ms", sa.Double(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("parsing_document", "processing_time_ms")
