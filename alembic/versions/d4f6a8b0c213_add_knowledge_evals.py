# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge evals

Revision ID: d4f6a8b0c213
Revises: c3d5f7a9e102
Create Date: 2026-11-25 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d4f6a8b0c213"
down_revision: str | Sequence[str] | None = "c3d5f7a9e102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Create eval cases and runs."""
    op.create_table(
        "knowledge_eval_case",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "expected_concepts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "expected_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_eval_case_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_eval_case"),
    )
    op.create_table(
        "knowledge_eval_run",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("passed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
            name="fk_knowledge_eval_run_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_eval_run"),
    )
    for table_name, comment in {
        "knowledge_eval_case": "知识评测用例：问题、期望命中的概念与事实关键词",
        "knowledge_eval_run": "知识评测运行：通过数、总数与逐用例明细",
    }.items():
        op.execute(f"COMMENT ON TABLE {table_name} IS '{comment}'")
    op.create_index(
        "ix_knowledge_eval_case_network",
        "knowledge_eval_case",
        ["network_id", "created"],
    )
    op.create_index(
        "ix_knowledge_eval_run_network",
        "knowledge_eval_run",
        ["network_id", "created"],
    )


def downgrade() -> None:
    """Drop eval cases and runs."""
    op.drop_table("knowledge_eval_run")
    op.drop_table("knowledge_eval_case")
