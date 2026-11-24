# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""add parsing workbench tables

Revision ID: 7b2d9e4c1a6f
Revises: c4d81a7f2e35
Create Date: 2026-11-24 12:00:00.000000

The parsing pipeline already writes source files and results to disk. These
tables make the lifecycle queryable: a batch task, its files, each attempt, and
the block-level edits a reviewer makes. Large outputs deliberately stay on disk;
the run row stores their path.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7b2d9e4c1a6f"
down_revision: str | Sequence[str] | None = "c4d81a7f2e35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column(
        "id",
        sa.Text(),
        server_default=sa.text("(gen_random_uuid())::text"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "parsing_profile",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsing_profile")),
        sa.UniqueConstraint("name", name=op.f("uq_parsing_profile_name")),
    )
    op.create_table(
        "parsing_task",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column(
            "profile", sa.Text(), server_default=sa.text("'standard'"), nullable=False
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "total_documents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "completed_documents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failed_documents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_parsing_task_known_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsing_task")),
    )
    op.create_table(
        "parsing_document",
        _id(),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("instance_id", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column(
            "progress_done",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "progress_total",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_parsing_document_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["parsing_task.id"],
            name=op.f("fk_parsing_document_task_id_parsing_task"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsing_document")),
    )
    op.create_table(
        "parsing_run",
        _id(),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "profile", sa.Text(), server_default=sa.text("'standard'"), nullable=False
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "model_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "layout_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("pipeline_version", sa.Text(), nullable=True),
        sa.Column("instance_id", sa.Text(), nullable=True),
        sa.Column("result_path", sa.Text(), nullable=True),
        sa.Column("blocks_path", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column(
            "progress_done",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "progress_total",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "quality",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "reviewed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_parsing_run_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["parsing_document.id"],
            name=op.f("fk_parsing_run_document_id_parsing_document"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["parsing_task.id"],
            name=op.f("fk_parsing_run_task_id_parsing_task"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsing_run")),
    )
    op.create_table(
        "parsing_block_edit",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column(
            "content", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("edited_by", sa.Text(), nullable=True),
        sa.Column(
            "edited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["parsing_run.id"],
            name=op.f("fk_parsing_block_edit_run_id_parsing_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "page", "idx", name=op.f("pk_parsing_block_edit")
        ),
    )
    op.create_index(
        "ix_parsing_task_created", "parsing_task", ["created"], unique=False
    )
    op.create_index(
        "ix_parsing_document_task",
        "parsing_document",
        ["task_id", "created"],
        unique=False,
    )
    op.create_index(
        "ix_parsing_document_status",
        "parsing_document",
        ["status", "created"],
        unique=False,
    )
    op.create_index(
        "ix_parsing_run_document",
        "parsing_run",
        ["document_id", "created"],
        unique=False,
    )
    op.create_index(
        "ix_parsing_run_task",
        "parsing_run",
        ["task_id", "created"],
        unique=False,
    )
    for table, comment in (
        ("parsing_profile", "解析档位：快速/标准/高精度等预设，保存 DPI、页范围与重试策略"),
        ("parsing_task", "解析任务：一次批量提交，记录文件数、完成数与总体状态"),
        ("parsing_document", "解析文件：任务里的单个文件，记录源文件、页数与页级进度"),
        (
            "parsing_run",
            "解析运行：一次实际解析，记录模型快照、结果路径、质量与校对状态",
        ),
        ("parsing_block_edit", "解析块修订：人工改过的块内容，按 run/page/idx 覆盖原始结果"),
    ):
        op.create_table_comment(table, comment, existing_comment=None, schema=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_parsing_run_task", table_name="parsing_run")
    op.drop_index("ix_parsing_run_document", table_name="parsing_run")
    op.drop_index("ix_parsing_document_status", table_name="parsing_document")
    op.drop_index("ix_parsing_document_task", table_name="parsing_document")
    op.drop_index("ix_parsing_task_created", table_name="parsing_task")
    op.drop_table("parsing_block_edit")
    op.drop_table("parsing_run")
    op.drop_table("parsing_document")
    op.drop_table("parsing_task")
    op.drop_table("parsing_profile")
