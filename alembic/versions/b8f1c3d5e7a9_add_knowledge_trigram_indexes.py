# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add trigram indexes for knowledge-context retrieval.

Revision ID: b8f1c3d5e7a9
Revises: f3a5c7e9b102
Create Date: 2026-11-25
"""

from alembic import op

revision: str = "b8f1c3d5e7a9"
down_revision: str | None = "f3a5c7e9b102"
branch_labels: str | None = None
depends_on: str | None = None

_INDEXES = (
    ("ix_knowledge_concept_name_trgm", "knowledge_concept", "name"),
    ("ix_knowledge_concept_description_trgm", "knowledge_concept", "description"),
    ("ix_knowledge_fact_statement_trgm", "knowledge_fact", "statement"),
    ("ix_knowledge_action_name_trgm", "knowledge_action", "name"),
    ("ix_knowledge_action_description_trgm", "knowledge_action", "description"),
    ("ix_knowledge_risk_name_trgm", "knowledge_risk", "name"),
    ("ix_knowledge_risk_description_trgm", "knowledge_risk", "description"),
    ("ix_knowledge_risk_mitigation_trgm", "knowledge_risk", "mitigation"),
    ("ix_knowledge_metric_name_trgm", "knowledge_metric", "name"),
    ("ix_knowledge_metric_description_trgm", "knowledge_metric", "description"),
    ("ix_knowledge_metric_expression_trgm", "knowledge_metric", "expression"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(
            name,
            table,
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
