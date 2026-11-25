# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge network versions

Revision ID: c3d5f7a9e102
Revises: b8e2f4c6d901
Create Date: 2026-11-25 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c3d5f7a9e102"
down_revision: str | Sequence[str] | None = "b8e2f4c6d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Store full JSON snapshots for audit and rollback."""
    op.create_table(
        "knowledge_network_version",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_network_version_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_network_version"),
        sa.UniqueConstraint(
            "network_id",
            "version",
            name="uq_knowledge_network_version_network_version",
        ),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_network_version IS "
        "'知识网络版本：完整图定义快照，用于发布审计与回滚'"
    )
    op.create_index(
        "ix_knowledge_network_version_network",
        "knowledge_network_version",
        ["network_id", "version"],
    )


def downgrade() -> None:
    """Drop snapshots; the live network definitions stay."""
    op.drop_table("knowledge_network_version")
