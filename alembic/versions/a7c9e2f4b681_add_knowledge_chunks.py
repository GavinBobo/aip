# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add searchable knowledge chunks.

Revision ID: a7c9e2f4b681
Revises: 5f7b2c9e4a13
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a7c9e2f4b681"
down_revision: str | Sequence[str] | None = "5f7b2c9e4a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("block_start", sa.Integer(), nullable=True),
        sa.Column("block_end", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_chunk_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_chunk_document_id_knowledge_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunk"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunk_document_index",
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_network",
        "knowledge_chunk",
        ["network_id", "document_id"],
    )
    for name, table, column in (
        ("ix_knowledge_chunk_text_trgm", "knowledge_chunk", "text"),
        ("ix_knowledge_document_title_trgm", "knowledge_document", "title"),
        ("ix_knowledge_document_summary_trgm", "knowledge_document", "summary"),
    ):
        op.create_index(
            name,
            table,
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    for name, table in (
        ("ix_knowledge_document_summary_trgm", "knowledge_document"),
        ("ix_knowledge_document_title_trgm", "knowledge_document"),
        ("ix_knowledge_chunk_text_trgm", "knowledge_chunk"),
        ("ix_knowledge_chunk_network", "knowledge_chunk"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_table("knowledge_chunk")
