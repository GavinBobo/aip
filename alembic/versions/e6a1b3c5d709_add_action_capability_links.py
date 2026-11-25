# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add action capability links

Revision ID: e6a1b3c5d709
Revises: d4f6a8b0c213
Create Date: 2026-11-25 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e6a1b3c5d709"
down_revision: str | Sequence[str] | None = "d4f6a8b0c213"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Mount capabilities on action types."""
    op.create_table(
        "knowledge_action__capability",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("capability_id", sa.Text(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["knowledge_action.id"],
            name="fk_action_capability_action",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["knowledge_capability.id"],
            name="fk_action_capability_capability",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_action__capability"),
        sa.UniqueConstraint(
            "action_id",
            "capability_id",
            name="uq_knowledge_action__capability_pair",
        ),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_action__capability IS '行动类与能力的挂载关系'"
    )
    op.create_index(
        "ix_knowledge_action__capability_action",
        "knowledge_action__capability",
        ["action_id"],
    )


def downgrade() -> None:
    """Drop action-capability mounts."""
    op.drop_table("knowledge_action__capability")
