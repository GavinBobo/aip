# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which row an edit is about, and the owner id stored on it.

An owner id names either an account or a group. This module only reads and
writes that column. Deciding whether the caller may edit, and whether a
chosen id is allowed to own the row, lives in ``all_ontology.server.owners``
because both answers need the role's permissions.

The rows whose stored owner the edit check reads are a database, a schema,
a table, and a term. A column, a column attribute, and a sql attribute are
still editable. The page shows the table's owner for a column and the term's
owner for either attribute. The edit check does not read an owner on those
rows, including the owner column a sql attribute still keeps.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select, update

from all_ontology.dal import schema as s
from all_ontology.dal.session import store

#: ``resource:action`` an owner of one of these rows must hold, and the edit must too.
CATALOG_EDIT = "catalog:edit"

_OWNED = (
    ("database", s.catalog_database, CATALOG_EDIT),
    ("schema", s.catalog_schema, CATALOG_EDIT),
    ("table", s.catalog_table, CATALOG_EDIT),
    ("term", s.term, CATALOG_EDIT),
)

#: Editable. The page shows the parent's owner. This check does not read one,
#: so a viewer in that owner's group is not admitted. A sql attribute keeps an
#: owner column; it is not what this check reads.
_EDITABLE = (
    ("column", s.catalog_column, CATALOG_EDIT),
    ("column_attribute", s.column_attribute, CATALOG_EDIT),
    ("sql_attribute", s.sql_attribute, CATALOG_EDIT),
)


class _Missing:
    """The id is not a row of the table that was asked."""


_MISSING = _Missing()


@dataclass(frozen=True)
class EditSubject:
    """The permission an edit needs, and the owner already stored."""

    permission: str
    owner_id: str | None
    #: Every catalog table the object touches. Zone edit permission is checked
    #: over the whole set, so a term or SQL attribute spanning two zones needs
    #: edit rights in both.
    target_table_ids: tuple[str, ...] = ()


def _stored_owner(table, entity_id: str) -> str | None | _Missing:
    rows = store().query_read(
        select(table.c.owner_id).where(table.c.id == entity_id).limit(1)
    )
    if not rows:
        return _MISSING
    return rows[0]["owner_id"]


def _row_exists(table, entity_id: str) -> bool:
    rows = store().query_read(
        select(table.c.id).where(table.c.id == entity_id).limit(1)
    )
    return bool(rows)


def _table_ids(kind: str, entity_id: str) -> tuple[str, ...]:
    if kind == "database":
        statement = (
            select(s.catalog_table.c.id)
            .select_from(
                s.catalog_table.join(
                    s.catalog_schema,
                    s.catalog_schema.c.id == s.catalog_table.c.schema_id,
                )
            )
            .where(s.catalog_schema.c.database_id == entity_id)
        )
    elif kind == "schema":
        statement = select(s.catalog_table.c.id).where(
            s.catalog_table.c.schema_id == entity_id
        )
    elif kind == "table":
        statement = select(s.catalog_table.c.id).where(
            s.catalog_table.c.id == entity_id
        )
    elif kind == "column":
        statement = select(s.catalog_column.c.table_id).where(
            s.catalog_column.c.id == entity_id
        )
    elif kind == "column_attribute":
        statement = select(s.column_attribute.c.table_id).where(
            s.column_attribute.c.id == entity_id
        )
    elif kind == "term":
        statement = select(s.table__term.c.table_id).where(
            s.table__term.c.term_id == entity_id
        )
    elif kind == "sql_attribute":
        statement = (
            select(s.sql_query__table.c.table_id)
            .select_from(
                s.sql_attribute__sql.join(
                    s.sql_query__table,
                    s.sql_query__table.c.sql_query_id
                    == s.sql_attribute__sql.c.sql_query_id,
                )
            )
            .where(s.sql_attribute__sql.c.attribute_id == entity_id)
        )
    else:  # pragma: no cover - callers use the fixed kind list above
        return ()
    return tuple(
        sorted(
            {
                str(row["table_id"] if "table_id" in row else row["id"])
                for row in store().query_read(statement)
                if (row.get("table_id") or row.get("id"))
            }
        )
    )


def edit_subject(entity_id: str) -> EditSubject | None:
    """The row *entity_id* names, or ``None`` when it names none of these.

    A zone and either kind of analysis are not among them. A column, a column
    attribute, and a sql attribute are, with no owner consulted here: the page
    shows the table's or the term's.
    """
    for kind, table, permission in _OWNED:
        stored = _stored_owner(table, entity_id)
        if stored is not _MISSING:
            return EditSubject(
                permission=permission,
                owner_id=stored,
                target_table_ids=_table_ids(kind, entity_id),
            )
    for kind, table, permission in _EDITABLE:
        if _row_exists(table, entity_id):
            return EditSubject(
                permission=permission,
                owner_id=None,
                target_table_ids=_table_ids(kind, entity_id),
            )
    return None


def current_owner(table, entity_id: str) -> str | None:
    """The stored owner, or null when the row is missing or unassigned."""
    stored = _stored_owner(table, entity_id)
    if stored is _MISSING:
        return None
    return stored


def assign_owner(table, entity_id: str, owner_id: str | None) -> None:
    """Set or clear ``owner_id``. ``None`` clears it."""
    store().query_write(
        update(table).where(table.c.id == entity_id).values(owner_id=owner_id)
    )
