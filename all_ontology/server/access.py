# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request-scoped data access context.

The Next.js gateway authenticates the caller and forwards the user id over the
private internal hop. Middleware resolves that id once per request into a
:class:`RequestAccess`; routers and services read the effective zone ids from
it without threading a ``Request`` through every DAL call.

``zone_ids=None`` retains its existing meaning in the DAL: the whole catalog.
Only an administrator gets that value. A non-admin with no grants gets ``[]``,
which every zone-scoped query treats as "match nothing".
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from fastapi import HTTPException

from all_ontology.dal import access as access_dal
from all_ontology.dal.schema import (
    GROUP_ROLE_ADMIN,
    ZONE_PERMISSION_EDIT,
    ZONE_PERMISSION_MANAGE,
    ZONE_PERMISSION_RANK,
    ZONE_PERMISSION_READ,
)
from all_ontology.dal.users import resolve_accessible_catalog_ids


@dataclass(frozen=True)
class RequestAccess:
    user_id: str
    role: str | None
    dept_ids: tuple[str, ...]
    zone_ids: tuple[str, ...] | None
    zone_permissions: tuple[tuple[str, str], ...] | None
    is_admin: bool


_CURRENT: ContextVar[RequestAccess | None] = ContextVar(
    "all_ontology_request_access", default=None
)


def load_request_access(user_id: str) -> RequestAccess | None:
    resolved = access_dal.account_access(user_id)
    if resolved is None or resolved["banned"]:
        return None
    is_admin = resolved["role"] == GROUP_ROLE_ADMIN
    return RequestAccess(
        user_id=user_id,
        role=resolved["role"],
        dept_ids=tuple(resolved["dept_ids"]),
        zone_ids=None if is_admin else tuple(resolved["zone_ids"]),
        zone_permissions=(
            None if is_admin else tuple(sorted(resolved["zone_permissions"].items()))
        ),
        is_admin=is_admin,
    )


def set_request_access(access: RequestAccess | None) -> Token[RequestAccess | None]:
    return _CURRENT.set(access)


def reset_request_access(token: Token[RequestAccess | None]) -> None:
    _CURRENT.reset(token)


def current_access() -> RequestAccess | None:
    return _CURRENT.get()


def current_user_id(*, required: bool = True) -> str | None:
    access = current_access()
    if access is not None:
        return access.user_id
    if required:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    return None


def require_admin() -> str:
    access = current_access()
    if access is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    if not access.is_admin:
        raise HTTPException(
            status_code=403, detail="Only admins can perform this action"
        )
    return access.user_id


def current_zone_permissions() -> dict[str, str] | None:
    access = current_access()
    if access is None or access.zone_permissions is None:
        return None
    return dict(access.zone_permissions)


def zone_permission(zone_id: str) -> str | None:
    """The caller's strongest permission on *zone_id*, or ``None``."""
    access = current_access()
    if access is None or access.is_admin:
        return str(ZONE_PERMISSION_MANAGE)
    permissions = current_zone_permissions() or {}
    return permissions.get(zone_id)


def current_zone_ids(
    minimum: str = str(ZONE_PERMISSION_READ),
) -> list[str] | None:
    """Effective zones for the current request.

    Missing context means a direct internal/test call outside the gateway
    middleware. It stays unscoped for backward compatibility with the existing
    service-level tests; every FastAPI request under ``/api`` is given context
    by the middleware in ``server.__main__``.
    """
    access = current_access()
    if access is None or access.zone_ids is None:
        return None
    if minimum == ZONE_PERMISSION_READ:
        return list(access.zone_ids)
    required_rank = ZONE_PERMISSION_RANK[str(minimum)]
    permissions = current_zone_permissions() or {}
    return [
        zone_id
        for zone_id in access.zone_ids
        if ZONE_PERMISSION_RANK.get(permissions.get(zone_id, ""), 0) >= required_rank
    ]


def zone_is_visible(zone_id: str) -> bool:
    zone_ids = current_zone_ids()
    return zone_ids is None or zone_id in zone_ids


def require_zone(zone_id: str) -> None:
    require_zone_permission(zone_id, ZONE_PERMISSION_READ)


def require_zone_permission(zone_id: str, minimum: str) -> None:
    actual = zone_permission(zone_id)
    if actual is None or ZONE_PERMISSION_RANK[actual] < ZONE_PERMISSION_RANK[minimum]:
        # 404 rather than 403: an inaccessible zone should read as absent, so
        # ids cannot be enumerated by status code.
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")


def table_is_editable(table_ids: list[str]) -> bool:
    """Whether every supplied table belongs to a zone the caller can edit."""
    if not table_ids:
        return False
    readable = current_zone_ids(ZONE_PERMISSION_EDIT)
    if readable is None:
        return True
    editable = resolve_accessible_catalog_ids(readable)
    return set(table_ids) <= set(editable["table_ids"])


def require_tables_editable(table_ids: list[str]) -> None:
    if not table_is_editable(table_ids):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit permission for every table in this object",
        )


__all__ = [
    "RequestAccess",
    "current_access",
    "current_user_id",
    "current_zone_ids",
    "current_zone_permissions",
    "load_request_access",
    "require_admin",
    "require_zone",
    "require_zone_permission",
    "require_tables_editable",
    "reset_request_access",
    "set_request_access",
    "zone_is_visible",
    "zone_permission",
    "table_is_editable",
]
