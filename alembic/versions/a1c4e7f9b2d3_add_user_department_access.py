# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add departments and user/department zone grants

Revision ID: a1c4e7f9b2d3
Revises: e9b3c6a71d52
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1c4e7f9b2d3"
down_revision: Union[str, Sequence[str], None] = "e9b3c6a71d52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "department",
        sa.Column(
            "id",
            sa.Text(),
            server_default=sa.text("(gen_random_uuid())::text"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_department")),
    )
    op.create_index(
        "uq_department_name_lower",
        "department",
        [sa.literal_column("lower(TRIM(BOTH FROM name))")],
        unique=True,
    )

    op.create_table(
        "department__member",
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["department.id"],
            name=op.f("fk_department__member_dept_id_department"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dept_id", "user_id", name=op.f("pk_department__member")
        ),
    )
    op.create_index(
        "ix_department__member_user_id",
        "department__member",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "zone_grant",
        sa.Column(
            "id",
            sa.Text(),
            server_default=sa.text("(gen_random_uuid())::text"),
            nullable=False,
        ),
        sa.Column("zone_id", sa.Text(), nullable=False),
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
            name=op.f("ck_zone_grant_exactly_one_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["department.id"],
            name=op.f("fk_zone_grant_dept_id_department"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"],
            ["zone.id"],
            name=op.f("fk_zone_grant_zone_id_zone"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zone_grant")),
        sa.UniqueConstraint("zone_id", "user_id", name="uq_zone_grant_zone_user"),
        sa.UniqueConstraint("zone_id", "dept_id", name="uq_zone_grant_zone_dept"),
    )
    op.create_index("ix_zone_grant_zone_id", "zone_grant", ["zone_id"], unique=False)
    op.create_index("ix_zone_grant_user_id", "zone_grant", ["user_id"], unique=False)
    op.create_index("ix_zone_grant_dept_id", "zone_grant", ["dept_id"], unique=False)

    op.execute(
        "COMMENT ON TABLE department IS "
        "'部门：数据权限的部门主体，成员可继承部门的 Zone 授权'"
    )
    op.execute(
        "COMMENT ON TABLE department__member IS "
        "'部门成员关系，user_id 指向 Prisma 的 frontend.user'"
    )
    op.execute(
        "COMMENT ON TABLE zone_grant IS "
        "'分区授权：把 Zone 授权给一个用户或一个部门，二者取其一'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_zone_grant_dept_id", table_name="zone_grant")
    op.drop_index("ix_zone_grant_user_id", table_name="zone_grant")
    op.drop_index("ix_zone_grant_zone_id", table_name="zone_grant")
    op.drop_table("zone_grant")
    op.drop_index("ix_department__member_user_id", table_name="department__member")
    op.drop_table("department__member")
    op.drop_index("uq_department_name_lower", table_name="department")
    op.drop_table("department")
