# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add action executions

Revision ID: f7b2c4d6e810
Revises: e6a1b3c5d709
Create Date: 2026-11-25 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f7b2c4d6e810"
down_revision: str | Sequence[str] | None = "e6a1b3c5d709"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Store action execution plans and results."""
    op.create_table(
        "knowledge_action_execution",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'planned'"), nullable=False
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "plan",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("finished", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned', 'completed', 'failed')",
            name="known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_action_execution_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["knowledge_action.id"],
            name="fk_knowledge_action_execution_action_id_knowledge_action",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_action_execution"),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_action_execution IS "
        "'行动执行记录：参数、执行计划、结果与状态'"
    )
    op.create_index(
        "ix_knowledge_action_execution_network",
        "knowledge_action_execution",
        ["network_id", "created"],
    )


def downgrade() -> None:
    """Drop action execution records."""
    op.drop_table("knowledge_action_execution")
