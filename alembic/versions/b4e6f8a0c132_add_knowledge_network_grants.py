# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge network grants

Revision ID: b4e6f8a0c132
Revises: a2d4f6b8c910
Create Date: 2026-11-25 20:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b4e6f8a0c132"
down_revision: str | Sequence[str] | None = "a2d4f6b8c910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Explicit user/department grants for knowledge networks."""
    op.create_table(
        "knowledge_network_grant",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("dept_id", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, dept_id) = 1",
            name="exactly_one_subject",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_network_grant_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["department.id"],
            name="fk_knowledge_network_grant_dept_id_department",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_network_grant"),
        sa.UniqueConstraint(
            "network_id", "user_id", name="uq_knowledge_network_grant_network_user"
        ),
        sa.UniqueConstraint(
            "network_id", "dept_id", name="uq_knowledge_network_grant_network_dept"
        ),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_network_grant IS '知识网络显式授权：用户或部门二选一'"
    )
    op.create_index(
        "ix_knowledge_network_grant_network",
        "knowledge_network_grant",
        ["network_id"],
    )


def downgrade() -> None:
    """Drop explicit network grants."""
    op.drop_table("knowledge_network_grant")
