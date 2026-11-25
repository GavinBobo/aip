# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge network grant audit

Revision ID: d7f9b1c3e526
Revises: c5e7a9b1d324
Create Date: 2026-11-25 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d7f9b1c3e526"
down_revision: str | Sequence[str] | None = "c5e7a9b1d324"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Record who replaced a knowledge network's grants."""
    op.create_table(
        "knowledge_network_grant_audit",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Text(), nullable=True),
        sa.Column(
            "action", sa.Text(), server_default=sa.text("'replace'"), nullable=False
        ),
        sa.Column(
            "before",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "after",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("action IN ('replace')", name="known_action"),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_network_grant_audit"),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_network_grant_audit IS "
        "'知识网络授权审计：操作者、变更前后授权'"
    )
    op.create_index(
        "ix_knowledge_network_grant_audit_network",
        "knowledge_network_grant_audit",
        ["network_id", "created"],
    )


def downgrade() -> None:
    """Drop the grant audit trail."""
    op.drop_table("knowledge_network_grant_audit")
