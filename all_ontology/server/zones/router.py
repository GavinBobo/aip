# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API route handlers for semantic zones."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from all_ontology.dal import access as access_dal
from all_ontology.dal import zones as dal
from all_ontology.server.access import (
    current_access,
    current_zone_ids,
    require_admin,
    require_zone_permission,
)
from all_ontology.dal.schema import ZONE_PERMISSION_MANAGE
from all_ontology.server.responses import IdResponse, ZoneListResponse, ZoneResponse

router = APIRouter()


class ZoneCreate(BaseModel):
    name: str
    description: str | None = None
    color: str
    items: list[str]


class ZoneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    items: list[str] | None = None


class ZoneStatusUpdate(BaseModel):
    enabled: bool


class ZoneGrantInput(BaseModel):
    subject_type: Literal["user", "department"]
    subject_id: str
    permission: Literal["read", "edit", "manage"] = "read"
    expires_at: str | None = None


class ZoneAccessUpdate(BaseModel):
    grants: list[ZoneGrantInput] = []
    # Legacy shape from the first access release. These become read grants.
    user_ids: list[str] = []
    dept_ids: list[str] = []


def _without_admin_details(row: dict) -> dict:
    """A zone as a non-admin sees it.

    Grant subjects include account names and emails. Those are directory data
    for an administrator managing access, not something every viewer of the
    zone needs, so the whole grant block is omitted outside the settings API.
    """
    access = current_access()
    if access is not None and access.is_admin:
        return row
    presented = dict(row)
    presented.pop("access", None)
    return presented


@router.get("/zones", response_model=ZoneListResponse)
def list_zones() -> dict:
    """Return the zones the authenticated caller may access."""
    rows = [_without_admin_details(row) for row in dal.list_zones(current_zone_ids())]
    return {"data": rows, "count": len(rows)}


@router.get("/zones/{zone_id}", response_model=ZoneResponse)
def get_zone(zone_id: str) -> dict:
    """Return one zone with its catalog data items."""
    row = dal.get_zone_by_id(zone_id, current_zone_ids())
    if row is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": _without_admin_details(row)}


@router.post("/zones", status_code=201, response_model=ZoneResponse)
def create_zone(body: ZoneCreate) -> dict:
    """Create a zone and attach catalog items.  Requires admin role."""
    require_admin()
    normalized_name = body.name.strip()
    if normalized_name == "":
        raise HTTPException(status_code=400, detail="Zone name is required")
    try:
        row = dal.create_zone(
            name=normalized_name,
            description=body.description,
            color=body.color,
            item_ids=body.items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": row}


@router.patch("/zones/{zone_id}", response_model=ZoneResponse)
def update_zone(zone_id: str, body: ZoneUpdate) -> dict:
    """Update zone fields and optionally replace catalog data items."""
    require_zone_permission(zone_id, ZONE_PERMISSION_MANAGE)
    field_updates: dict[str, str | None] = {}
    provided_fields = body.model_fields_set

    if "name" in provided_fields:
        raw_name = body.name or ""
        normalized_name = raw_name.strip()
        if normalized_name == "":
            raise HTTPException(status_code=400, detail="Zone name is required")
        field_updates["name"] = normalized_name

    if "description" in provided_fields:
        normalized_description = (body.description or "").strip()
        field_updates["description"] = normalized_description or None

    if "color" in provided_fields:
        field_updates["color"] = body.color

    try:
        row = dal.update_zone(
            zone_id=zone_id,
            updates=field_updates,
            item_ids=body.items if "items" in provided_fields else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": row}


@router.delete("/zones/{zone_id}", response_model=IdResponse)
def delete_zone(zone_id: str) -> dict:
    """Delete one zone by id."""
    require_admin()
    if not dal.delete_zone(zone_id):
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": {"id": zone_id}}


@router.patch("/zones/{zone_id}/status", response_model=ZoneResponse)
def set_zone_status(
    zone_id: str,
    body: ZoneStatusUpdate,
) -> dict:
    """Enable or disable a zone.  Requires admin role.

    Disabling clears the zone's ``enabled`` flag
    (re-enabling reverses it), which immediately revokes the catalog access
    the zone granted without deleting it.
    """
    require_zone_permission(zone_id, ZONE_PERMISSION_MANAGE)
    row = dal.set_zone_enabled(zone_id, body.enabled)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": row}


@router.put("/zones/{zone_id}/access", response_model=ZoneResponse)
def replace_zone_access(zone_id: str, body: ZoneAccessUpdate) -> dict:
    """Replace the users and departments this zone is granted to.

    Requires admin. A user sees the union of their direct zone grants and the
    grants held by every department they belong to.
    """
    require_zone_permission(zone_id, ZONE_PERMISSION_MANAGE)
    try:
        access_dal.replace_zone_grants(
            zone_id,
            grants=[grant.model_dump() for grant in body.grants],
            user_ids=list(
                dict.fromkeys(item.strip() for item in body.user_ids if item.strip())
            ),
            dept_ids=list(
                dict.fromkeys(item.strip() for item in body.dept_ids if item.strip())
            ),
            actor_user_id=(
                current_access().user_id if current_access() is not None else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = dal.get_zone_by_id(zone_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return {"data": row}


@router.get("/zones/{zone_id}/grant-audit")
def list_zone_grant_audit(zone_id: str) -> dict:
    """Return recent grant changes; requires manage permission on the Zone."""
    require_zone_permission(zone_id, ZONE_PERMISSION_MANAGE)
    rows = access_dal.list_zone_grant_audit(zone_id)
    return {"data": rows, "count": len(rows)}
