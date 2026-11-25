# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge definitions from BKN

Revision ID: c7a2e5d9b413
Revises: 6b1d9f4a2c7e
Create Date: 2026-11-25 12:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c7a2e5d9b413"
down_revision: str | Sequence[str] | None = "6b1d9f4a2c7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Add action, risk and concept-group definitions beside concepts/relations."""
    op.create_table(
        "knowledge_action",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "action_intent",
            sa.Text(),
            server_default=sa.text("'execute'"),
            nullable=False,
        ),
        sa.Column("bound_concept_id", sa.Text(), nullable=True),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            "action_intent IN ('add', 'modify', 'delete', 'execute')",
            name="known_intent",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'certified')",
            name="known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_action_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bound_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_action_bound_concept_id_knowledge_concept",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_action_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_action"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_action_network_key"
        ),
    )

    op.create_table(
        "knowledge_risk",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "severity", sa.Text(), server_default=sa.text("'medium'"), nullable=False
        ),
        sa.Column("mitigation", sa.Text(), nullable=True),
        sa.Column("related_concept_id", sa.Text(), nullable=True),
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
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="known_severity",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'certified')",
            name="known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_risk_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["related_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_risk_related_concept_id_knowledge_concept",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_risk_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_risk"),
        sa.UniqueConstraint("network_id", "key", name="uq_knowledge_risk_network_key"),
    )

    op.create_table(
        "knowledge_concept_group",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
            name="fk_knowledge_concept_group_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_concept_group"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_concept_group_network_key"
        ),
    )

    op.create_table(
        "knowledge_concept_group__concept",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("concept_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["knowledge_concept_group.id"],
            name="fk_knowledge_group_member_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_group_member_concept",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_concept_group__concept"),
        sa.UniqueConstraint(
            "group_id", "concept_id", name="uq_knowledge_concept_group__concept"
        ),
    )

    op.add_column(
        "knowledge_evidence", sa.Column("action_id", sa.Text(), nullable=True)
    )
    op.add_column("knowledge_evidence", sa.Column("risk_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_evidence_action_id_knowledge_action",
        "knowledge_evidence",
        "knowledge_action",
        ["action_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_evidence_risk_id_knowledge_risk",
        "knowledge_evidence",
        "knowledge_risk",
        ["risk_id"],
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
        "num_nonnulls(concept_id, relation_id, fact_id, action_id, risk_id) = 1",
    )

    for table_name, comment in {
        "knowledge_action": "知识行动：从文档抽取的可执行操作，可绑定到概念并导出为 BKN action_type",
        "knowledge_risk": "知识风险：从文档抽取的风险、严重度与缓解措施，可导出为 BKN risk_type",
        "knowledge_concept_group": "概念分组：把相关概念组织在一起，可导出为 BKN concept_group",
        "knowledge_concept_group__concept": "概念分组成员关系",
    }.items():
        op.execute(f"COMMENT ON TABLE {table_name} IS '{comment}'")

    op.create_index(
        "ix_knowledge_action_network", "knowledge_action", ["network_id", "name"]
    )
    op.create_index(
        "ix_knowledge_risk_network", "knowledge_risk", ["network_id", "name"]
    )
    op.create_index(
        "ix_knowledge_concept_group_network",
        "knowledge_concept_group",
        ["network_id", "name"],
    )
    op.create_index(
        "ix_knowledge_concept_group__concept_group",
        "knowledge_concept_group__concept",
        ["group_id"],
    )


def downgrade() -> None:
    """Drop BKN action/risk/group definitions; concepts and relations stay."""
    op.drop_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        type_="check",
    )
    op.create_check_constraint(
        "exactly_one_target",
        "knowledge_evidence",
        "num_nonnulls(concept_id, relation_id, fact_id) = 1",
    )
    op.drop_constraint(
        "fk_knowledge_evidence_risk_id_knowledge_risk",
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_evidence_action_id_knowledge_action",
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_column("knowledge_evidence", "risk_id")
    op.drop_column("knowledge_evidence", "action_id")
    op.drop_table("knowledge_concept_group__concept")
    op.drop_table("knowledge_concept_group")
    op.drop_table("knowledge_risk")
    op.drop_table("knowledge_action")
