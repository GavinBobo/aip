# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add image-understanding records and knowledge image citations.

Revision ID: c2d3e4f5a6b7
Revises: b8f1c3d5e7a9
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b8f1c3d5e7a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parsing_document",
        sa.Column("source_md5", sa.Text(), nullable=True),
    )
    op.add_column(
        "parsing_document",
        sa.Column("parsed_md_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "parsing_document",
        sa.Column(
            "learned_to_knowledge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "parsing_document",
        sa.Column("learned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "parsing_document",
        sa.Column("knowledge_document_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_parsing_document_knowledge_document",
        "parsing_document",
        "knowledge_document",
        ["knowledge_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "knowledge_document",
        sa.Column("source_md5", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("source_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("parsed_md_path", sa.Text(), nullable=True),
    )

    op.add_column(
        "knowledge_evidence",
        sa.Column("image_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_evidence",
        sa.Column("source_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_evidence",
        sa.Column("image_path", sa.Text(), nullable=True),
    )
    op.create_table(
        "parsing_image",
        sa.Column(
            "id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("(gen_random_uuid())::text"),
        ),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("image_md5", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("image_file_path", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("area_px", sa.BigInteger(), nullable=True),
        sa.Column("vlm_prompt", sa.Text(), nullable=True),
        sa.Column("vlm_content", sa.Text(), nullable=True),
        sa.Column(
            "vlm_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("vlm_error", sa.Text(), nullable=True),
        sa.Column(
            "learned_to_knowledge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("learned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("knowledge_document_id", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["parsing_run.id"],
            name="fk_parsing_image_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["parsing_document.id"],
            name="fk_parsing_image_document_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_document_id"],
            ["knowledge_document.id"],
            name="fk_parsing_image_knowledge_document_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parsing_image"),
        sa.UniqueConstraint(
            "run_id",
            "page",
            "block_index",
            name="uq_parsing_image_run_page_block",
        ),
        sa.CheckConstraint(
            "vlm_status IN ('pending', 'succeeded', 'failed', 'skipped_small', 'disabled')",
            name="known_vlm_status",
        ),
    )
    op.create_foreign_key(
        "fk_knowledge_evidence_image",
        "knowledge_evidence",
        "parsing_image",
        ["image_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "COMMENT ON TABLE parsing_document IS "
        "'解析文件：源文件 MD5/路径、解析后 Markdown 路径、进度与知识学习状态'"
    )
    op.execute(
        "COMMENT ON TABLE parsing_image IS "
        "'解析图片：图片 MD5/路径、像素面积、VLM 解读内容与知识学习状态'"
    )

    op.create_index(
        "ix_parsing_document_source_md5",
        "parsing_document",
        ["source_md5"],
    )
    op.create_index(
        "ix_parsing_image_run",
        "parsing_image",
        ["run_id", "page"],
    )
    op.create_index(
        "ix_parsing_image_document",
        "parsing_image",
        ["document_id"],
    )
    op.create_index(
        "ix_parsing_image_md5",
        "parsing_image",
        ["image_md5"],
    )
    op.create_index(
        "ix_parsing_image_knowledge_document",
        "parsing_image",
        ["knowledge_document_id"],
    )
    op.create_index(
        "ix_knowledge_evidence_image",
        "knowledge_evidence",
        ["image_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_evidence_image", table_name="knowledge_evidence")
    op.drop_index(
        "ix_parsing_image_knowledge_document", table_name="parsing_image"
    )
    op.drop_index("ix_parsing_image_md5", table_name="parsing_image")
    op.drop_index("ix_parsing_image_document", table_name="parsing_image")
    op.drop_index("ix_parsing_image_run", table_name="parsing_image")
    op.drop_index(
        "ix_parsing_document_source_md5", table_name="parsing_document"
    )
    op.drop_constraint(
        "fk_knowledge_evidence_image",
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_table("parsing_image")
    op.drop_column("knowledge_evidence", "image_path")
    op.drop_column("knowledge_evidence", "source_path")
    op.drop_column("knowledge_evidence", "image_id")
    op.drop_column("knowledge_document", "parsed_md_path")
    op.drop_column("knowledge_document", "source_path")
    op.drop_column("knowledge_document", "source_md5")
    op.drop_constraint(
        "fk_parsing_document_knowledge_document",
        "parsing_document",
        type_="foreignkey",
    )
    op.drop_column("parsing_document", "knowledge_document_id")
    op.drop_column("parsing_document", "learned_at")
    op.drop_column("parsing_document", "learned_to_knowledge")
    op.drop_column("parsing_document", "parsed_md_path")
    op.drop_column("parsing_document", "source_md5")
