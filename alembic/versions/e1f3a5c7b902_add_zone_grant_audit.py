# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add zone grant audit

Revision ID: e1f3a5c7b902
Revises: d9e2f4a6b801
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1f3a5c7b902"
down_revision: Union[str, Sequence[str], None] = "d9e2f4a6b801"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "zone_grant_audit",
        sa.Column(
            "id",
            sa.Text(),
            server_default=sa.text("(gen_random_uuid())::text"),
            nullable=False,
        ),
        sa.Column("zone_id", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["zone_id"],
            ["zone.id"],
            name=op.f("fk_zone_grant_audit_zone_id_zone"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zone_grant_audit")),
    )
    op.create_index(
        "ix_zone_grant_audit_zone",
        "zone_grant_audit",
        ["zone_id", "created"],
        unique=False,
    )
    op.execute(
        "COMMENT ON TABLE zone_grant_audit IS "
        "'分区授权审计：操作者、变更前后授权与权限等级'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_zone_grant_audit_zone", table_name="zone_grant_audit")
    op.drop_table("zone_grant_audit")
