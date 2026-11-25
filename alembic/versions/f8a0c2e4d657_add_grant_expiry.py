# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add grant expiry

Revision ID: f8a0c2e4d657
Revises: d9e2f4a6b801
Create Date: 2026-11-25 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f8a0c2e4d657"
down_revision: str | Sequence[str] | None = "d9e2f4a6b801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow temporary knowledge-network grants."""
    op.add_column(
        "knowledge_network_grant",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove grant expiry."""
    op.drop_column("knowledge_network_grant", "expires_at")
