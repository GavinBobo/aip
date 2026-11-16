# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""File-uploaded datasets backing the "Excel / CSV" connection type.

The bytes are stored on the catalog database rather than on a shared volume:
the API and the ingestion service are separate containers/deployments, and a
file that only one of them can see would produce a catalog nothing can query.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from all_ontology.dal import schema as s
from all_ontology.dal.session import store


def upsert_dataset(
    *,
    name: str,
    filename: str | None,
    table_name: str,
    row_count: int | None,
    content: bytes,
) -> dict[str, Any]:
    """Store (or replace) the dataset behind connection *name*."""
    statement = insert(s.uploaded_dataset).values(
        name=name,
        filename=filename,
        table_name=table_name,
        row_count=row_count,
        size_bytes=len(content),
        content=content,
    )
    rows = store().query_write(
        statement.on_conflict_do_update(
            index_elements=[s.uploaded_dataset.c.name],
            set_={
                "filename": statement.excluded.filename,
                "table_name": statement.excluded.table_name,
                "row_count": statement.excluded.row_count,
                "size_bytes": statement.excluded.size_bytes,
                "content": statement.excluded.content,
            },
        ).returning(
            s.uploaded_dataset.c.name,
            s.uploaded_dataset.c.filename,
            s.uploaded_dataset.c.table_name,
            s.uploaded_dataset.c.row_count,
            s.uploaded_dataset.c.size_bytes,
        )
    )
    return dict(rows[0])


def get_dataset(name: str) -> dict[str, Any] | None:
    """The stored dataset for *name*, including its bytes, or ``None``."""
    rows = store().query_read(
        select(
            s.uploaded_dataset.c.name,
            s.uploaded_dataset.c.filename,
            s.uploaded_dataset.c.table_name,
            s.uploaded_dataset.c.row_count,
            s.uploaded_dataset.c.size_bytes,
            s.uploaded_dataset.c.content,
        ).where(s.uploaded_dataset.c.name == name)
    )
    return dict(rows[0]) if rows else None


def delete_dataset(name: str) -> None:
    """Delete the dataset behind *name*. Idempotent."""
    store().query_write(
        delete(s.uploaded_dataset).where(s.uploaded_dataset.c.name == name)
    )
