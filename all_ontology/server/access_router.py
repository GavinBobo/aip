# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Administration of departments and the caller's own effective data scope."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from all_ontology.dal import access as dal
from all_ontology.server.access import current_access, require_admin

router = APIRouter()

MAX_DEPARTMENT_NAME_LENGTH = 100


class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None
    user_ids: list[str] = []


class DepartmentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    user_ids: list[str] | None = None


class DepartmentMembers(BaseModel):
    user_ids: list[str] = []


class UserDepartments(BaseModel):
    dept_ids: list[str] = []


def _name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Department name is required")
    if len(name) > MAX_DEPARTMENT_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                "Department name must be at most "
                f"{MAX_DEPARTMENT_NAME_LENGTH} characters"
            ),
        )
    return name


def _description(value: str | None) -> str | None:
    return None if value is None else (value.strip() or None)


def _ids(raw: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in raw if item.strip()))


def _translate(exc: ValueError) -> HTTPException:
    if isinstance(exc, dal.DepartmentNameTaken):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/access/me")
def get_my_access() -> dict:
    """The caller's role, departments and effective enabled zones."""
    access = current_access()
    if access is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    return {
        "data": {
            "user_id": access.user_id,
            "role": access.role,
            "is_admin": access.is_admin,
            "dept_ids": list(access.dept_ids),
            "zone_ids": None if access.is_admin else list(access.zone_ids or ()),
            "zone_permissions": (
                None
                if access.is_admin
                else {
                    zone_id: permission
                    for zone_id, permission in (access.zone_permissions or ())
                }
            ),
        }
    }


@router.get("/access/departments")
def list_departments() -> dict:
    """Every department with members. Requires admin."""
    require_admin()
    rows = dal.list_departments()
    return {"data": rows, "count": len(rows)}


@router.post("/access/departments", status_code=201)
def create_department(body: DepartmentCreate) -> dict:
    """Create a department. Requires admin."""
    require_admin()
    try:
        row = dal.create_department(
            name=_name(body.name),
            description=_description(body.description),
            user_ids=_ids(body.user_ids),
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"data": row}


@router.patch("/access/departments/{dept_id}")
def update_department(dept_id: str, body: DepartmentUpdate) -> dict:
    """Patch a department and optionally replace its members. Requires admin."""
    require_admin()
    provided = body.model_fields_set
    updates: dict[str, str | None] = {}
    if "name" in provided:
        updates["name"] = _name(body.name or "")
    if "description" in provided:
        updates["description"] = _description(body.description)
    try:
        row = dal.update_department(
            dept_id,
            updates,
            user_ids=_ids(body.user_ids) if "user_ids" in provided else None,
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"data": row}


@router.delete("/access/departments/{dept_id}")
def delete_department(dept_id: str) -> dict:
    """Delete a department and its zone grants. Requires admin."""
    require_admin()
    if not dal.delete_department(dept_id):
        raise HTTPException(status_code=404, detail="Department not found")
    return {"data": {"id": dept_id}}


@router.put("/access/departments/{dept_id}/members")
def replace_department_members(dept_id: str, body: DepartmentMembers) -> dict:
    """Replace a department's membership. Requires admin."""
    require_admin()
    try:
        row = dal.update_department(
            dept_id,
            {},
            user_ids=_ids(body.user_ids),
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"data": row}


@router.get("/access/users")
def list_access_users() -> dict:
    """Every account with its department ids. Requires admin."""
    require_admin()
    rows = dal.list_accounts_with_departments()
    return {"data": rows, "count": len(rows)}


@router.put("/access/users/{user_id}/departments")
def replace_user_departments(user_id: str, body: UserDepartments) -> dict:
    """Replace one account's department memberships. Requires admin."""
    require_admin()
    try:
        departments = dal.set_user_departments(user_id, _ids(body.dept_ids))
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"data": {"user_id": user_id, "departments": departments}}
