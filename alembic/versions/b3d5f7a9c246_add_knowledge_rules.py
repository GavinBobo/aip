# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add document-grounded business rules and their bridge links.

Revision ID: b3d5f7a9c246
Revises: a7c9e2f4b681
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b3d5f7a9c246"
down_revision: str | Sequence[str] | None = "a7c9e2f4b681"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    op.create_table(
        "knowledge_rule",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exceptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("confidence", sa.Double(), server_default=sa.text("0.6"), nullable=False),
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
            name=op.f("ck_knowledge_rule_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_rule_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_rule_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_rule"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_rule_network_key"
        ),
    )
    for table_name, target_table, column_name in (
        ("knowledge_rule__concept", "knowledge_concept", "concept_id"),
        ("knowledge_rule__metric", "knowledge_metric", "metric_id"),
        ("knowledge_rule__action", "knowledge_action", "action_id"),
    ):
        op.create_table(
            table_name,
            sa.Column("rule_id", sa.Text(), nullable=False),
            sa.Column(column_name, sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(
                ["rule_id"],
                ["knowledge_rule.id"],
                name=f"fk_{table_name}_rule_id_knowledge_rule",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                [column_name],
                [f"{target_table}.id"],
                name=f"fk_{table_name}_{column_name}_{target_table}",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("rule_id", column_name, name=f"pk_{table_name}"),
        )

    op.add_column(
        "knowledge_evidence",
        sa.Column("rule_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_evidence_rule_id_knowledge_rule",
        "knowledge_evidence",
        "knowledge_rule",
        ["rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        op.f("ck_knowledge_evidence_exactly_one_target"),
        "knowledge_evidence",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_evidence_exactly_one_target"),
        "knowledge_evidence",
        "num_nonnulls(concept_id, relation_id, fact_id, action_id, risk_id, metric_id, rule_id) = 1",
    )

    op.create_index(
        "ix_knowledge_rule_network",
        "knowledge_rule",
        ["network_id", "name"],
    )
    for column in ("name", "statement", "description", "scope", "condition"):
        op.create_index(
            f"ix_knowledge_rule_{column}_trgm",
            "knowledge_rule",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    for column in ("condition", "scope", "description", "statement", "name"):
        op.drop_index(f"ix_knowledge_rule_{column}_trgm", table_name="knowledge_rule")
    op.drop_index("ix_knowledge_rule_network", table_name="knowledge_rule")
    op.drop_constraint(
        op.f("ck_knowledge_evidence_exactly_one_target"),
        "knowledge_evidence",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_evidence_exactly_one_target"),
        "knowledge_evidence",
        "num_nonnulls(concept_id, relation_id, fact_id, action_id, risk_id, metric_id) = 1",
    )
    op.drop_constraint(
        op.f("fk_knowledge_evidence_rule_id_knowledge_rule"),
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_column("knowledge_evidence", "rule_id")
    op.drop_table("knowledge_rule__action")
    op.drop_table("knowledge_rule__metric")
    op.drop_table("knowledge_rule__concept")
    op.drop_table("knowledge_rule")
