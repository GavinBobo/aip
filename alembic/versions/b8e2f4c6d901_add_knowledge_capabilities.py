# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge capabilities

Revision ID: b8e2f4c6d901
Revises: a1c4e7f9b2d3
Create Date: 2026-11-25 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b8e2f4c6d901"
down_revision: str | Sequence[str] | None = "a1c4e7f9b2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Declare network capabilities (Skill/Function/MCP tool/knowledge base)."""
    op.create_table(
        "knowledge_capability",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'skill'"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('skill', 'function', 'mcp_tool', 'knowledge_base')",
            name="known_kind",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_capability_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_capability"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_capability_network_key"
        ),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_capability IS "
        "'知识网络能力：Skill、Function、MCP 工具或知识库的依赖声明'"
    )
    op.create_index(
        "ix_knowledge_capability_network",
        "knowledge_capability",
        ["network_id", "name"],
    )


def downgrade() -> None:
    """Drop capability declarations; the network and its knowledge stay."""
    op.drop_table("knowledge_capability")
