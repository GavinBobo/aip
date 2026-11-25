# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ensure pql_analysis has a zone scope

Revision ID: d9e2f4a6b801
Revises: d7f9b1c3e526
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "d9e2f4a6b801"
down_revision: Union[str, Sequence[str], None] = "d7f9b1c3e526"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    ``IF NOT EXISTS`` keeps this safe for a database that already applied the
    same column in an earlier development migration.
    """
    op.execute(
        "ALTER TABLE pql_analysis "
        "ADD COLUMN IF NOT EXISTS zone_id text "
        "REFERENCES zone(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE pql_analysis DROP COLUMN IF EXISTS zone_id")
