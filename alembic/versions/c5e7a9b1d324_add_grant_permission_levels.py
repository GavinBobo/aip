# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add read/edit/manage permission to zone and knowledge grants

Revision ID: c5e7a9b1d324
Revises: b4e6f8a0c132
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5e7a9b1d324"
down_revision: Union[str, Sequence[str], None] = "b4e6f8a0c132"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Existing grants mean what they meant before: read access. The server
    default is also the migration's backfill value, so no row is left without
    a permission level.
    """
    for table in ("zone_grant", "knowledge_network_grant"):
        op.add_column(
            table,
            sa.Column(
                "permission",
                sa.Text(),
                server_default=sa.text("'read'"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_permission_value"),
            table,
            "permission IN ('read', 'edit', 'manage')",
        )
    op.add_column(
        "pql_analysis",
        sa.Column("zone_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_pql_analysis_zone_id_zone"),
        "pql_analysis",
        "zone",
        ["zone_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_pql_analysis_zone_id_zone"), "pql_analysis", type_="foreignkey"
    )
    op.drop_column("pql_analysis", "zone_id")
    for table in ("zone_grant", "knowledge_network_grant"):
        op.drop_constraint(op.f(f"ck_{table}_permission_value"), table, type_="check")
        op.drop_column(table, "permission")
