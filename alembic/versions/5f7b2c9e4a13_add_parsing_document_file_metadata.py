# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add parsing document file metadata

Revision ID: 5f7b2c9e4a13
Revises: d4a8f1c6e932
Create Date: 2026-11-27 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "5f7b2c9e4a13"
down_revision: str | Sequence[str] | None = "d4a8f1c6e932"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "parsing_document", sa.Column("mime_type", sa.Text(), nullable=True)
    )
    op.add_column(
        "parsing_document", sa.Column("file_type", sa.Text(), nullable=True)
    )
    op.add_column(
        "parsing_document", sa.Column("page_width", sa.Integer(), nullable=True)
    )
    op.add_column(
        "parsing_document", sa.Column("page_height", sa.Integer(), nullable=True)
    )
    op.add_column(
        "parsing_document",
        sa.Column("source_mtime", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("parsing_document", "source_mtime")
    op.drop_column("parsing_document", "page_height")
    op.drop_column("parsing_document", "page_width")
    op.drop_column("parsing_document", "file_type")
    op.drop_column("parsing_document", "mime_type")
