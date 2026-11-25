# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Departments, zone grants, and the effective zone set for one account.

This module is the write path behind the ``user_id`` / ``dept_id`` access
model. A zone remains the unit of data access; it is now reachable through one
or more grants, each naming either a Better Auth user or a department. An
account's visible zones are the union of:

* zones granted directly to its ``user_id``;
* zones granted to any department it belongs to.

Only enabled zones count. An administrator is not expanded here: callers treat
the administrator's ``zone_ids=None`` as the existing "unscoped" state, which
keeps the difference between "all data" and "no data" explicit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn

from sqlalchemy import func, literal, select, text
from sqlalchemy.exc import IntegrityError

from all_ontology.dal import schema as s
from all_ontology.dal.session import store, write_transaction
from all_ontology.infra.postgres import FRONTEND_SCHEMA

_ACCOUNT_SQL = f"""
SELECT id, name, email, role, banned
  FROM {FRONTEND_SCHEMA}."user"
"""


class DepartmentNameTaken(ValueError):
    """Another department already holds this name, case-insensitively."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Department with name {name!r} already exists")


class UnknownDepartmentMembers(ValueError):
    """One or more member ids are not accounts."""

    def __init__(self, user_ids: list[str]) -> None:
        self.user_ids = user_ids
        super().__init__(f"Unknown user id(s): {', '.join(user_ids)}")


class UnknownDepartments(ValueError):
    """One or more department ids do not exist."""

    def __init__(self, dept_ids: list[str]) -> None:
        self.dept_ids = dept_ids
        super().__init__(f"Unknown department id(s): {', '.join(dept_ids)}")


class UnknownZoneGrantSubjects(ValueError):
    """A zone grant names an unknown user or department."""

    def __init__(self, *, user_ids: list[str], dept_ids: list[str]) -> None:
        self.user_ids = user_ids
        self.dept_ids = dept_ids
        parts = []
        if user_ids:
            parts.append(f"unknown user id(s): {', '.join(user_ids)}")
        if dept_ids:
            parts.append(f"unknown department id(s): {', '.join(dept_ids)}")
        super().__init__("; ".join(parts))


def _accounts_by_id(user_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not user_ids:
        return {}
    rows = store().query_read(
        text(_ACCOUNT_SQL + " WHERE id = ANY(:user_ids)"),
        {"user_ids": list(dict.fromkeys(user_ids))},
    )
    return {str(row["id"]): dict(row) for row in rows}


def _missing_user_ids(user_ids: list[str]) -> list[str]:
    found = _accounts_by_id(user_ids)
    return [user_id for user_id in dict.fromkeys(user_ids) if user_id not in found]


def _require_members_exist(user_ids: list[str]) -> None:
    missing = _missing_user_ids(user_ids)
    if missing:
        raise UnknownDepartmentMembers(missing)


def _require_departments_exist(dept_ids: list[str]) -> None:
    if not dept_ids:
        return
    found = {
        str(row["id"])
        for row in store().query_read(
            select(s.department.c.id).where(
                s.department.c.id.in_(list(dict.fromkeys(dept_ids)))
            )
        )
    }
    missing = [dept_id for dept_id in dict.fromkeys(dept_ids) if dept_id not in found]
    if missing:
        raise UnknownDepartments(missing)


def _name_taken(name: str, *, exclude_id: str | None = None) -> bool:
    statement = select(s.department.c.id).where(
        func.lower(func.trim(s.department.c.name)) == name.strip().lower()
    )
    if exclude_id is not None:
        statement = statement.where(s.department.c.id != exclude_id)
    return bool(store().query_read(statement))


def _raise_name_taken(exc: IntegrityError, name: str) -> NoReturn:
    if "uq_department_name_lower" not in str(exc.orig):
        raise exc
    raise DepartmentNameTaken(name) from exc


def _member_view(account: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if account is None:
        return {"id": user_id, "name": "", "email": "", "role": None}
    return {
        "id": str(account["id"]),
        "name": account.get("name") or "",
        "email": account.get("email") or "",
        "role": account.get("role"),
    }


def _attach_members(departments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not departments:
        return []
    dept_ids = [str(dept["id"]) for dept in departments]
    rows = store().query_read(
        select(
            s.department__member.c.dept_id,
            s.department__member.c.user_id,
        ).where(s.department__member.c.dept_id.in_(dept_ids))
    )
    accounts = _accounts_by_id([str(row["user_id"]) for row in rows])
    by_dept: dict[str, list[str]] = {}
    for row in rows:
        by_dept.setdefault(str(row["dept_id"]), []).append(str(row["user_id"]))

    out: list[dict[str, Any]] = []
    for dept in departments:
        users = [
            _member_view(accounts.get(user_id), user_id)
            for user_id in by_dept.get(str(dept["id"]), [])
        ]
        users.sort(key=lambda user: ((user["name"] or "").lower(), user["id"]))
        out.append(
            {
                **dept,
                "description": dept.get("description") or "",
                "users": users,
                "user_ids": [user["id"] for user in users],
            }
        )
    return out


def list_departments() -> list[dict[str, Any]]:
    """Every department with its members, ordered by name."""
    rows = store().query_read(
        select(
            s.department.c.id,
            s.department.c.name,
            s.department.c.description,
            s.department.c.created,
        ).order_by(func.lower(s.department.c.name), s.department.c.id)
    )
    return _attach_members([dict(row) for row in rows])


def get_department(dept_id: str) -> dict[str, Any] | None:
    rows = list_departments()
    return next((dept for dept in rows if dept["id"] == dept_id), None)


def create_department(
    *, name: str, description: str | None, user_ids: list[str]
) -> dict[str, Any]:
    """Create a department and its members."""
    if _name_taken(name):
        raise DepartmentNameTaken(name)
    _require_members_exist(user_ids)
    try:
        with write_transaction():
            rows = store().query_write(
                s.department.insert()
                .values(name=name, description=description)
                .returning(s.department.c.id)
            )
            dept_id = str(rows[0]["id"])
            if user_ids:
                store().query_write(
                    s.department__member.insert().values(
                        [
                            {"dept_id": dept_id, "user_id": user_id}
                            for user_id in dict.fromkeys(user_ids)
                        ]
                    )
                )
    except IntegrityError as exc:
        _raise_name_taken(exc, name)
    created = get_department(dept_id)
    if created is None:  # pragma: no cover - the insert just returned this id
        raise RuntimeError(f"Department {dept_id!r} missing after insert")
    return created


def update_department(
    dept_id: str,
    updates: dict[str, Any],
    *,
    user_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Patch fields and, when *user_ids* is given, replace membership."""
    if user_ids is not None:
        _require_members_exist(user_ids)
    try:
        with write_transaction():
            locked = store().query_read(
                select(s.department.c.id)
                .where(s.department.c.id == dept_id)
                .with_for_update()
            )
            if not locked:
                return None
            if "name" in updates and _name_taken(
                str(updates["name"]), exclude_id=dept_id
            ):
                raise DepartmentNameTaken(str(updates["name"]))
            if updates:
                store().query_write(
                    s.department.update()
                    .where(s.department.c.id == dept_id)
                    .values(**updates)
                )
            if user_ids is not None:
                store().query_write(
                    s.department__member.delete().where(
                        s.department__member.c.dept_id == dept_id
                    )
                )
                if user_ids:
                    store().query_write(
                        s.department__member.insert().values(
                            [
                                {"dept_id": dept_id, "user_id": user_id}
                                for user_id in dict.fromkeys(user_ids)
                            ]
                        )
                    )
    except IntegrityError as exc:
        if "name" in updates:
            _raise_name_taken(exc, str(updates["name"]))
        raise
    return get_department(dept_id)


def delete_department(dept_id: str) -> bool:
    rows = store().query_write(
        s.department.delete()
        .where(s.department.c.id == dept_id)
        .returning(s.department.c.id)
    )
    return bool(rows)


def set_user_departments(user_id: str, dept_ids: list[str]) -> list[dict[str, Any]]:
    """Replace every department membership for one account."""
    if _missing_user_ids([user_id]):
        raise UnknownDepartmentMembers([user_id])
    _require_departments_exist(dept_ids)
    with write_transaction():
        store().query_write(
            s.department__member.delete().where(
                s.department__member.c.user_id == user_id
            )
        )
        if dept_ids:
            store().query_write(
                s.department__member.insert().values(
                    [
                        {"dept_id": dept_id, "user_id": user_id}
                        for dept_id in dict.fromkeys(dept_ids)
                    ]
                )
            )
    by_id = {
        dept["id"]: dept for dept in list_departments() if dept["id"] in set(dept_ids)
    }
    return [by_id[dept_id] for dept_id in dict.fromkeys(dept_ids) if dept_id in by_id]


def list_accounts_with_departments() -> list[dict[str, Any]]:
    """Accounts with the department ids they belong to, ordered by name."""
    accounts = store().query_read(text(_ACCOUNT_SQL + " ORDER BY lower(name), id"))
    memberships = store().query_read(
        select(s.department__member.c.user_id, s.department__member.c.dept_id)
    )
    by_user: dict[str, list[str]] = {}
    for row in memberships:
        by_user.setdefault(str(row["user_id"]), []).append(str(row["dept_id"]))
    return [
        {
            **_member_view(dict(account), str(account["id"])),
            "banned": bool(account.get("banned")),
            "dept_ids": sorted(by_user.get(str(account["id"]), [])),
        }
        for account in accounts
    ]


def account_access(user_id: str) -> dict[str, Any] | None:
    """The role, departments and effective enabled zones for *user_id*.

    ``None`` means the account does not exist. A banned account resolves to an
    empty zone set rather than to an error so the caller can deny uniformly.
    """
    rows = store().query_read(
        text(_ACCOUNT_SQL + " WHERE id = :user_id"),
        {"user_id": user_id},
    )
    if not rows:
        return None
    account = dict(rows[0])
    role = account.get("role")
    dept_rows = store().query_read(
        select(s.department__member.c.dept_id).where(
            s.department__member.c.user_id == user_id
        )
    )
    dept_ids = sorted({str(row["dept_id"]) for row in dept_rows})
    zone_permissions: dict[str, str] = {}
    if not account.get("banned"):
        if role == s.GROUP_ROLE_ADMIN:
            zone_permissions = {
                str(row["id"]): str(s.ZONE_PERMISSION_MANAGE)
                for row in store().query_read(
                    select(s.zone.c.id).where(s.zone.c.enabled.is_(True))
                )
            }
        else:
            rows = store().query_read(
                text(
                    """
                    SELECT zone.id AS zone_id, grant_row.permission
                      FROM zone
                      JOIN zone_grant grant_row
                        ON grant_row.zone_id = zone.id
                     WHERE zone.enabled
                       AND (
                            grant_row.user_id = :user_id
                            OR grant_row.dept_id = ANY(:dept_ids)
                       )
                       AND (
                            grant_row.expires_at IS NULL
                            OR grant_row.expires_at > now()
                       )
                    """
                ),
                {"user_id": user_id, "dept_ids": dept_ids},
            )
            for row in rows:
                zone_id = str(row["zone_id"])
                permission = str(row["permission"])
                current = zone_permissions.get(zone_id)
                if (
                    current is None
                    or s.ZONE_PERMISSION_RANK[permission]
                    > (s.ZONE_PERMISSION_RANK[current])
                ):
                    zone_permissions[zone_id] = permission
    return {
        "user_id": user_id,
        "role": role,
        "banned": bool(account.get("banned")),
        "dept_ids": dept_ids,
        "zone_ids": sorted(zone_permissions),
        "zone_permissions": zone_permissions,
    }


def zone_grants(zone_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Grants grouped by zone, with user and department display rows."""
    statement = select(
        s.zone_grant.c.zone_id,
        s.zone_grant.c.user_id,
        s.zone_grant.c.dept_id,
        s.zone_grant.c.permission,
        s.zone_grant.c.expires_at,
    )
    if zone_ids is not None:
        if not zone_ids:
            return {}
        statement = statement.where(s.zone_grant.c.zone_id.in_(zone_ids))
    rows = store().query_read(statement)
    user_ids = [str(row["user_id"]) for row in rows if row["user_id"]]
    dept_ids = [str(row["dept_id"]) for row in rows if row["dept_id"]]
    accounts = _accounts_by_id(user_ids)
    departments = {
        dept["id"]: dept for dept in list_departments() if dept["id"] in set(dept_ids)
    }
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        zone_id = str(row["zone_id"])
        entry = out.setdefault(
            zone_id,
            {
                "user_ids": [],
                "dept_ids": [],
                "users": [],
                "departments": [],
                "grants": [],
                "user_permissions": {},
                "dept_permissions": {},
            },
        )
        if row["user_id"]:
            user_id = str(row["user_id"])
            if user_id not in entry["user_ids"]:
                entry["user_ids"].append(user_id)
                entry["users"].append(_member_view(accounts.get(user_id), user_id))
                entry["user_permissions"][user_id] = str(row["permission"])
                entry["grants"].append(
                    {
                        "subject_type": "user",
                        "subject_id": user_id,
                        "permission": str(row["permission"]),
                        "expires_at": (
                            row["expires_at"].isoformat()
                            if row["expires_at"] is not None
                            else None
                        ),
                    }
                )
        if row["dept_id"]:
            dept_id = str(row["dept_id"])
            if dept_id not in entry["dept_ids"]:
                entry["dept_ids"].append(dept_id)
                dept = departments.get(dept_id)
                entry["departments"].append(
                    {
                        "id": dept_id,
                        "name": dept["name"] if dept else "",
                    }
                )
                entry["dept_permissions"][dept_id] = str(row["permission"])
                entry["grants"].append(
                    {
                        "subject_type": "department",
                        "subject_id": dept_id,
                        "permission": str(row["permission"]),
                        "expires_at": (
                            row["expires_at"].isoformat()
                            if row["expires_at"] is not None
                            else None
                        ),
                    }
                )
    for entry in out.values():
        entry["user_ids"].sort()
        entry["dept_ids"].sort()
        entry["users"].sort(key=lambda user: ((user["name"] or "").lower(), user["id"]))
        entry["departments"].sort(
            key=lambda dept: ((dept["name"] or "").lower(), dept["id"])
        )
        entry["grants"].sort(
            key=lambda grant: (grant["subject_type"], grant["subject_id"])
        )
    return out


def empty_grants() -> dict[str, Any]:
    return {
        "user_ids": [],
        "dept_ids": [],
        "users": [],
        "departments": [],
        "grants": [],
        "user_permissions": {},
        "dept_permissions": {},
    }


def replace_zone_grants(
    zone_id: str,
    *,
    grants: list[dict[str, Any]] | None = None,
    user_ids: list[str] | None = None,
    dept_ids: list[str] | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any] | None:
    """Replace a zone's direct user and department grants.

    ``None`` when the zone does not exist. Unknown subjects raise
    :class:`UnknownZoneGrantSubjects` before anything is written.

    *grants* is the current shape: a list of
    ``{subject_type, subject_id, permission}``. The legacy ``user_ids`` /
    ``dept_ids`` arguments remain for callers upgrading from the first release;
    they mean ``read`` access.
    """
    zone_rows = store().query_read(select(s.zone.c.id).where(s.zone.c.id == zone_id))
    if not zone_rows:
        return None
    before = [
        {
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "permission": row["permission"],
            "expires_at": row.get("expires_at"),
        }
        for row in zone_grants([zone_id]).get(zone_id, empty_grants())["grants"]
    ]
    normalized: dict[tuple[str, str], str] = {}
    expiry_by_key: dict[tuple[str, str], datetime | None] = {}
    raw_grants = list(grants or [])
    raw_grants.extend(
        {"subject_type": "user", "subject_id": subject_id, "permission": "read"}
        for subject_id in (user_ids or [])
    )
    raw_grants.extend(
        {
            "subject_type": "department",
            "subject_id": subject_id,
            "permission": "read",
        }
        for subject_id in (dept_ids or [])
    )
    for grant in raw_grants:
        subject_type = str(grant.get("subject_type") or "").strip()
        subject_id = str(grant.get("subject_id") or "").strip()
        permission = str(grant.get("permission") or "read").strip()
        if subject_type not in {"user", "department"} or not subject_id:
            raise ValueError("Each grant needs a user or department subject")
        if permission not in s.ZONE_PERMISSION_RANK:
            raise ValueError(f"Unknown permission {permission!r}")
        key = (subject_type, subject_id)
        current = normalized.get(key)
        if (
            current is None
            or s.ZONE_PERMISSION_RANK[permission] > (s.ZONE_PERMISSION_RANK[current])
        ):
            normalized[key] = permission
        raw_expiry = grant.get("expires_at")
        if raw_expiry:
            try:
                expiry_by_key[key] = datetime.fromisoformat(
                    str(raw_expiry).replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError("Invalid grant expiry") from exc
        else:
            expiry_by_key.setdefault(key, None)
    unique_users = [subject_id for kind, subject_id in normalized if kind == "user"]
    unique_depts = [
        subject_id for kind, subject_id in normalized if kind == "department"
    ]
    missing_users = _missing_user_ids(unique_users)
    _require_departments_exist(unique_depts)
    if missing_users:
        raise UnknownZoneGrantSubjects(user_ids=missing_users, dept_ids=[])
    with write_transaction():
        store().query_write(
            s.zone_grant.delete().where(s.zone_grant.c.zone_id == zone_id)
        )
        rows = [
            {
                "zone_id": zone_id,
                "user_id": subject_id if kind == "user" else None,
                "dept_id": subject_id if kind == "department" else None,
                "permission": permission,
                "expires_at": expiry_by_key.get((kind, subject_id)),
            }
            for (kind, subject_id), permission in normalized.items()
        ]
        if rows:
            store().query_write(s.zone_grant.insert().values(rows))
        store().query_write(
            s.zone_grant_audit.insert().values(
                zone_id=zone_id,
                actor_user_id=actor_user_id,
                action="replace",
                before=before,
                after=[
                    {
                        "subject_type": kind,
                        "subject_id": subject_id,
                        "permission": permission,
                        "expires_at": (
                            expiry_by_key[(kind, subject_id)].isoformat()
                            if expiry_by_key.get((kind, subject_id))
                            else None
                        ),
                    }
                    for (kind, subject_id), permission in normalized.items()
                ],
            )
        )
    return zone_grants([zone_id]).get(zone_id, empty_grants())


def list_zone_grant_audit(zone_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = store().query_read(
        select(s.zone_grant_audit)
        .where(s.zone_grant_audit.c.zone_id == zone_id)
        .order_by(s.zone_grant_audit.c.created.desc())
        .limit(limit)
    )
    return [dict(row) for row in rows]


def visible_object_ids(
    ids_by_label: dict[str, list[str]], allowed_table_ids: list[str]
) -> set[str]:
    """Which retrieved object ids stay visible under a table allow-list.

    Used by the chat pipeline before VDB hits reach the prompt. The label names
    are the ones the vector metadata already carries (``Table``, ``Column``,
    ``ColumnAttribute``, ``SqlAttribute``, ``CustomAnalysis``, ``Term``).
    Unknown labels are dropped; that is the fail-closed choice for a new
    retrievable kind that has not declared how it maps to catalog data.
    """
    allowed = set(allowed_table_ids)
    visible: set[str] = set()
    if not allowed:
        return visible

    labels = {label: [str(i) for i in ids if i] for label, ids in ids_by_label.items()}

    def _collect(statement) -> None:
        visible.update(str(row["id"]) for row in store().query_read(statement))

    table_ids = labels.get("Table", [])
    if table_ids:
        _collect(
            select(s.catalog_table.c.id).where(
                s.catalog_table.c.id.in_(table_ids),
                s.catalog_table.c.id.in_(allowed),
            )
        )

    column_ids = labels.get("Column", [])
    if column_ids:
        _collect(
            select(s.catalog_column.c.id).where(
                s.catalog_column.c.id.in_(column_ids),
                s.catalog_column.c.table_id.in_(allowed),
            )
        )

    attribute_ids = labels.get("ColumnAttribute", [])
    if attribute_ids:
        _collect(
            select(s.column_attribute.c.id).where(
                s.column_attribute.c.id.in_(attribute_ids),
                s.column_attribute.c.table_id.in_(allowed),
            )
        )

    term_ids = labels.get("Term", [])
    if term_ids:
        inside = (
            select(literal(1))
            .select_from(s.table__term)
            .where(
                s.table__term.c.term_id == s.term.c.id,
                s.table__term.c.table_id.in_(allowed),
            )
            .correlate(s.term)
            .exists()
        )
        outside = (
            select(literal(1))
            .select_from(s.table__term)
            .where(
                s.table__term.c.term_id == s.term.c.id,
                s.table__term.c.table_id.notin_(allowed),
            )
            .correlate(s.term)
            .exists()
        )
        _collect(
            select(s.term.c.id).where(
                s.term.c.id.in_(term_ids),
                inside,
                ~outside,
            )
        )

    sql_attr_ids = labels.get("SqlAttribute", [])
    if sql_attr_ids:
        outside = (
            select(literal(1))
            .select_from(
                s.sql_attribute__sql.join(
                    s.sql_query__table,
                    s.sql_query__table.c.sql_query_id
                    == s.sql_attribute__sql.c.sql_query_id,
                )
            )
            .where(
                s.sql_attribute__sql.c.attribute_id == s.sql_attribute.c.id,
                s.sql_query__table.c.table_id.notin_(allowed),
            )
            .correlate(s.sql_attribute)
            .exists()
        )
        _collect(
            select(s.sql_attribute.c.id).where(
                s.sql_attribute.c.id.in_(sql_attr_ids),
                ~outside,
            )
        )

    custom_ids = labels.get("CustomAnalysis", [])
    if custom_ids:
        outside = (
            select(literal(1))
            .select_from(
                s.custom_analysis__sql.join(
                    s.sql_query__table,
                    s.sql_query__table.c.sql_query_id
                    == s.custom_analysis__sql.c.sql_query_id,
                )
            )
            .where(
                s.custom_analysis__sql.c.analysis_id == s.custom_analysis.c.id,
                s.sql_query__table.c.table_id.notin_(allowed),
            )
            .correlate(s.custom_analysis)
            .exists()
        )
        _collect(
            select(s.custom_analysis.c.id).where(
                s.custom_analysis.c.id.in_(custom_ids),
                ~outside,
            )
        )

    return visible
