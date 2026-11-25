# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge metrics

Revision ID: e9b3c6a71d52
Revises: c7a2e5d9b413
Create Date: 2026-11-25 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e9b3c6a71d52"
down_revision: str | Sequence[str] | None = "c7a2e5d9b413"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Add object metrics owned by knowledge concepts."""
    op.create_table(
        "knowledge_metric",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("concept_id", sa.Text(), nullable=True),
        sa.Column("sql_attribute_id", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column(
            "confidence", sa.Double(), server_default=sa.text("0.6"), nullable=False
        ),
        sa.Column("source_document_id", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'certified')",
            name="known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_metric_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_metric_concept_id_knowledge_concept",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sql_attribute_id"],
            ["sql_attribute.id"],
            name="fk_knowledge_metric_sql_attribute_id_sql_attribute",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_metric_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_metric"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_metric_network_key"
        ),
    )
    op.execute(
        "COMMENT ON TABLE knowledge_metric IS "
        "'对象指标：归属于概念的可计算表达式，可链接数据本体的 SQL 属性并导出为 BKN object_metric'"
    )
    op.create_index(
        "ix_knowledge_metric_network", "knowledge_metric", ["network_id", "name"]
    )
    op.add_column(
        "knowledge_evidence", sa.Column("metric_id", sa.Text(), nullable=True)
    )
    op.create_foreign_key(
        "fk_knowledge_evidence_metric_id_knowledge_metric",
        "knowledge_evidence",
        "knowledge_metric",
        ["metric_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        type_="check",
    )
    op.create_check_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        "num_nonnulls(concept_id, relation_id, fact_id, action_id, risk_id, metric_id) = 1",
    )


def downgrade() -> None:
    """Drop knowledge metrics; concepts and SQL attributes stay."""
    op.drop_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        type_="check",
    )
    op.create_check_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        "num_nonnulls(concept_id, relation_id, fact_id, action_id, risk_id) = 1",
    )
    op.drop_constraint(
        "fk_knowledge_evidence_metric_id_knowledge_metric",
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_column("knowledge_evidence", "metric_id")
    op.drop_table("knowledge_metric")
