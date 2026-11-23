# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add semantic quality tables and value profiles

Revision ID: c4d81a7f2e35
Revises: b6e9d2a4c781
Create Date: 2026-11-23 14:00:00.000000

Ports the semantic-quality half of Auto-Ontology 1.3.0: term families and the
two catalog_column value-profile fields semantic FK resolution compares.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d81a7f2e35"
down_revision: str | Sequence[str] | None = "b6e9d2a4c781"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "catalog_column", sa.Column("distinct_values", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_column", sa.Column("distinct_ratio", sa.Float(), nullable=True)
    )
    op.create_table(
        "term_family",
        sa.Column(
            "id",
            sa.Text(),
            server_default=sa.text("(gen_random_uuid())::text"),
            nullable=False,
        ),
        sa.Column("schema_id", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["schema_id"],
            ["catalog_schema.id"],
            name=op.f("fk_term_family_schema_id_catalog_schema"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_term_family")),
        sa.UniqueConstraint("schema_id", "prefix", name="uq_term_family_schema_prefix"),
    )
    op.create_table(
        "term__term_family",
        sa.Column("term_id", sa.Text(), nullable=False),
        sa.Column("family_id", sa.Text(), nullable=False),
        sa.Column("base_name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["term_family.id"],
            name=op.f("fk_term__term_family_family_id_term_family"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["term.id"],
            name=op.f("fk_term__term_family_term_id_term"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "term_id", "family_id", name=op.f("pk_term__term_family")
        ),
        sa.UniqueConstraint("term_id", name=op.f("uq_term__term_family_term_id")),
    )
    op.create_table_comment(
        "term_family",
        "Term families: copies of one schema told apart by a table-name prefix",
        existing_comment=None,
        schema=None,
    )
    op.create_table_comment(
        "term__term_family",
        "Term membership in a term family; base_name is the table name without the prefix",
        existing_comment=None,
        schema=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("term__term_family")
    op.drop_table("term_family")
    op.drop_column("catalog_column", "distinct_ratio")
    op.drop_column("catalog_column", "distinct_values")
