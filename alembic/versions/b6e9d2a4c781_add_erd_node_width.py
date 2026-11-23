# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add erd node width

Revision ID: b6e9d2a4c781
Revises: 2f7c9b1e4a6d
Create Date: 2026-11-23 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b6e9d2a4c781"
down_revision: Union[str, Sequence[str], None] = "2f7c9b1e4a6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "erd_node",
        sa.Column("width", sa.Double(), nullable=False, server_default=sa.text("248")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("erd_node", "width")
