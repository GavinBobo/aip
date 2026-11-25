# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add knowledge ontology

Revision ID: 6b1d9f4a2c7e
Revises: 8a4e2c6f9d1b
Create Date: 2026-11-25 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "6b1d9f4a2c7e"
down_revision: str | Sequence[str] | None = "8a4e2c6f9d1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("(gen_random_uuid())::text")


def upgrade() -> None:
    """Create the knowledge-network tier beside the existing data ontology."""
    op.create_table(
        "knowledge_network",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column(
            "version", sa.Text(), server_default=sa.text("'1.0'"), nullable=False
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("modified_by", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_knowledge_network_known_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_network"),
    )

    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'extracting', 'extracted', 'failed')",
            name="ck_knowledge_document_known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_document_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["parsing_run.id"],
            name="fk_knowledge_document_run_id_parsing_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_document"),
        sa.UniqueConstraint(
            "network_id",
            "run_id",
            name="uq_knowledge_document_network_run",
        ),
    )

    op.create_table(
        "knowledge_concept",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind", sa.Text(), server_default=sa.text("'entity'"), nullable=False
        ),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attributes",
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
            "kind IN ('entity', 'event', 'process', 'rule', 'metric', 'role', 'document')",
            name="ck_knowledge_concept_known_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'certified')",
            name="ck_knowledge_concept_known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_concept_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_concept_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_concept"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_concept_network_key"
        ),
    )

    op.create_table(
        "knowledge_relation",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("source_concept_id", sa.Text(), nullable=False),
        sa.Column("target_concept_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind", sa.Text(), server_default=sa.text("'association'"), nullable=False
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
            "kind IN ('association', 'part_of', 'causal', 'depends_on', 'controls', 'flows_to', 'related')",
            name="ck_knowledge_relation_known_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'certified')",
            name="ck_knowledge_relation_known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_relation_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_relation_source_concept_id_knowledge_concept",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_relation_target_concept_id_knowledge_concept",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_relation_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_relation"),
        sa.UniqueConstraint(
            "network_id", "key", name="uq_knowledge_relation_network_key"
        ),
    )

    op.create_table(
        "knowledge_fact",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("subject_concept_id", sa.Text(), nullable=False),
        sa.Column("relation_id", sa.Text(), nullable=True),
        sa.Column("object_concept_id", sa.Text(), nullable=True),
        sa.Column("object_text", sa.Text(), nullable=True),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
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
            name="ck_knowledge_fact_known_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_fact_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_fact_subject_concept_id_knowledge_concept",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relation_id"],
            ["knowledge_relation.id"],
            name="fk_knowledge_fact_relation_id_knowledge_relation",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["object_concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_fact_object_concept_id_knowledge_concept",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_fact_source_document_id_knowledge_document",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_fact"),
    )

    op.create_table(
        "knowledge_evidence",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("network_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("concept_id", sa.Text(), nullable=True),
        sa.Column("relation_id", sa.Text(), nullable=True),
        sa.Column("fact_id", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("block_index", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "num_nonnulls(concept_id, relation_id, fact_id) = 1",
            name="ck_knowledge_evidence_exactly_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["knowledge_network.id"],
            name="fk_knowledge_evidence_network_id_knowledge_network",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_document.id"],
            name="fk_knowledge_evidence_document_id_knowledge_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_evidence_concept_id_knowledge_concept",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relation_id"],
            ["knowledge_relation.id"],
            name="fk_knowledge_evidence_relation_id_knowledge_relation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["knowledge_fact.id"],
            name="fk_knowledge_evidence_fact_id_knowledge_fact",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_evidence"),
    )

    op.create_table(
        "knowledge_concept__data",
        sa.Column("id", sa.Text(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("concept_id", sa.Text(), nullable=False),
        sa.Column("term_id", sa.Text(), nullable=True),
        sa.Column("table_id", sa.Text(), nullable=True),
        sa.Column(
            "confidence", sa.Double(), server_default=sa.text("0.8"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "num_nonnulls(term_id, table_id) = 1",
            name="ck_knowledge_concept__data_exactly_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["knowledge_concept.id"],
            name="fk_knowledge_concept__data_concept_id_knowledge_concept",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["term.id"],
            name="fk_knowledge_concept__data_term_id_term",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["catalog_table.id"],
            name="fk_knowledge_concept__data_table_id_catalog_table",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_concept__data"),
    )

    op.create_index(
        "ix_knowledge_document_network",
        "knowledge_document",
        ["network_id", "created"],
    )
    op.create_index(
        "ix_knowledge_concept_network",
        "knowledge_concept",
        ["network_id", "name"],
    )
    op.create_index(
        "ix_knowledge_relation_network",
        "knowledge_relation",
        ["network_id", "source_concept_id"],
    )
    op.create_index(
        "ix_knowledge_fact_network",
        "knowledge_fact",
        ["network_id", "created"],
    )
    op.create_index(
        "ix_knowledge_evidence_document",
        "knowledge_evidence",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_evidence_concept",
        "knowledge_evidence",
        ["concept_id"],
    )
    op.create_index(
        "ix_knowledge_evidence_fact",
        "knowledge_evidence",
        ["fact_id"],
    )
    op.create_index(
        "ix_knowledge_concept__data_concept",
        "knowledge_concept__data",
        ["concept_id"],
    )


def downgrade() -> None:
    """Drop the knowledge tier; the data ontology and parse runs stay intact."""
    op.drop_table("knowledge_concept__data")
    op.drop_table("knowledge_evidence")
    op.drop_table("knowledge_fact")
    op.drop_table("knowledge_relation")
    op.drop_table("knowledge_concept")
    op.drop_table("knowledge_document")
    op.drop_table("knowledge_network")
