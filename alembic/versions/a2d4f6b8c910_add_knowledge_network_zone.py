# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge network zone

Revision ID: a2d4f6b8c910
Revises: f7b2c4d6e810
Create Date: 2026-11-25 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a2d4f6b8c910"
down_revision: str | Sequence[str] | None = "f7b2c4d6e810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Scope a knowledge network to an optional catalog zone."""
    op.add_column("knowledge_network", sa.Column("zone_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_network_zone_id_zone",
        "knowledge_network",
        "zone",
        ["zone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_knowledge_network_zone", "knowledge_network", ["zone_id"])


def downgrade() -> None:
    """Remove the optional zone scope."""
    op.drop_index("ix_knowledge_network_zone", table_name="knowledge_network")
    op.drop_constraint(
        "fk_knowledge_network_zone_id_zone",
        "knowledge_network",
        type_="foreignkey",
    )
    op.drop_column("knowledge_network", "zone_id")
