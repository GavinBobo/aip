# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Assemble the All Ontology MCP server from the published OpenAPI spec."""

from __future__ import annotations

import base64
import json
import logging
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError
from mcp.types import Icon

from all_ontology_mcp import chat, readiness
from all_ontology_mcp.config import ConfigError, Settings
from all_ontology_mcp.all_ontology_auth import (
    build_all_ontology_auth,
    all_ontology_access_token,
)
from all_ontology_mcp.tools import (
    apply_description,
    missing_from_spec,
    names_by_operation_id,
    route_maps,
)
from all_ontology_mcp import get_version

logger = logging.getLogger(__name__)

SERVER_NAME = "all-ontology"

# Shipped in the package and inlined as a data URI rather than linked, so it
# needs no network and no reachable All Ontology to display — a client may well draw its
# server list before anything is connected.
ICON_PATH = Path(__file__).resolve().parent / "nvidia-mark.svg"
ICON_MIME_TYPE = "image/svg+xml"

# Advertised to the host at initialize. Tool descriptions say what each tool
# does; this says how they fit together, which is the part a model otherwise
# has to infer from names — and infers badly, usually by reaching straight for
# the expensive one.
INSTRUCTIONS = """\
All Ontology answers questions about an organisation's
structured data. It holds a compiled semantic layer — a glossary of business
terms mapped onto real database columns and reviewed SQL expressions — over the
databases this deployment is connected to.

Use `ask_question` for anything that needs an actual answer from the data. It
runs a full text-to-SQL agent and returns the answer, the SQL it ran, and the
rows.

The other tools exist so you can understand the vocabulary before you ask, and
check your assumptions after. A productive sequence is usually:

1. `search_terms` to find out what a business word means here. Deployments
   differ: "active customer" is a defined term with specific SQL behind it,
   not something to guess at.
2. `check_answerable` if you are unsure the question is in scope. It is far
   cheaper than `ask_question` and tells you whether the semantic layer covers
   the entities involved.
3. `ask_question` to get the answer.

`check_readiness` answers a different question: whether this deployment can
answer anything at all. A deployment with no database connection reads normally
and still fails every question, so reach for it before a first question here, or
when `ask_question` comes back empty — an empty answer is far more often a
deployment that is not set up than a question that was misunderstood.

Work through the semantic layer, not around it. `get_term_columns` tells you
which physical columns a term stands for, `get_term_sql_attributes` and
`get_sql_attribute` give you expressions that were already reviewed here, and
`describe_table` says what a table means rather than only its shape. There is
deliberately no tool for browsing databases, schemas, or raw columns:
questions are answered against the glossary.

Every tool reads. Nothing here modifies the catalog, the glossary, or the
underlying databases.
"""


def load_spec(settings: Settings) -> dict[str, Any]:
    """Read and validate the OpenAPI document the tools are generated from."""
    try:
        spec = json.loads(settings.spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{settings.spec_path} is not valid JSON: {exc}") from exc

    if not isinstance(spec, dict) or not spec.get("paths"):
        raise ConfigError(f"{settings.spec_path} has no paths; is it an OpenAPI spec?")

    # A curated entry that matches nothing would otherwise drop that tool
    # silently, leaving a server that looks healthy but is missing capability.
    missing = missing_from_spec(spec)
    if missing:
        raise ConfigError(
            "The OpenAPI spec no longer publishes these curated operations: "
            + ", ".join(missing)
            + ". Regenerate the spec, or update all_ontology_mcp/tools.py to match."
        )
    return spec


def load_icons() -> list[Icon]:
    """The NVIDIA mark, for clients that show an icon beside each server.

    Purely cosmetic, so a missing or unreadable file degrades to no icon rather
    than stopping a working server from starting.

    ``sizes`` is left unset deliberately: it is optional, an SVG has no natural
    pixel size, and clients have historically disagreed about whether the field
    is a string or a list.
    """
    try:
        svg = ICON_PATH.read_bytes()
    except OSError as exc:
        logger.warning("No icon at %s (%s); serving without one.", ICON_PATH, exc)
        return []

    encoded = base64.b64encode(svg).decode("ascii")
    return [
        Icon(src=f"data:{ICON_MIME_TYPE};base64,{encoded}", mimeType=ICON_MIME_TYPE)
    ]


BEARER_HEADER = "authorization"

# Not a credential this server accepts — one it refuses. FastMCP copies the
# incoming request's headers onto the outbound call, and All Ontology resolves an API key
# ahead of a bearer token, so a caller who sent one would be acting as its owner
# rather than as whoever they signed in as. It is stripped on the way out.
API_KEY_HEADER = "x-api-key"

# Delegated identity: the gateway proves itself with this key and names the
# user in the subject header. The same key is configured on All Ontology.
DELEGATION_KEY_HEADER = "x-all-ontology-delegation-key"


def _incoming_headers() -> dict[str, str]:
    """The request's headers, or an empty map outside an HTTP request."""
    try:
        # `include_all` matters: FastMCP strips Authorization from the default
        # view because forwarding it downstream is usually wrong. Here it is the
        # credential the caller asked us to relay.
        return {
            str(key).lower(): str(value)
            for key, value in get_http_headers(include_all=True).items()
        }
    except Exception:
        # The stdio transport has no HTTP request in scope. The identity modes
        # that need headers report that as an actionable error below.
        return {}


class CallerAuth(httpx.Auth):
    """Authenticate every outbound call as the caller who triggered it.

    Three modes, in order of preference:

    * **Sign-in (default).** Identity comes from the caller's All Ontology
      session; the access token All Ontology issued is forwarded unchanged.
    * **Credential passthrough.** The caller presents their own SSO bearer
      token or All Ontology API token on every request, and exactly one of them
      is relayed.
    * **Delegated subject.** A trusted gateway proves itself with a shared key
      and names the user; All Ontology resolves that subject.

    The server still holds no identity of its own: what changes per request is
    always resolved by All Ontology to that person's departments, zones, and
    grants.

    Attaching this as httpx auth rather than at each call site is deliberate: it
    covers the generated tools and the hand-written streaming one through the
    single client they share, so no tool can be added later that forgets to
    authenticate.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings

    @property
    def _delegated(self) -> bool:
        return bool(self._settings and self._settings.delegation_key)

    @property
    def _passthrough(self) -> bool:
        return bool(self._settings and self._settings.passthrough_auth)

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        if self._delegated:
            yield self._forward_delegation(request)
            return
        if self._passthrough:
            yield self._forward_caller_credential(request)
            return
        yield self._forward_signed_in_token(request)

    def _forward_delegation(self, request: httpx.Request) -> httpx.Request:
        """Relay a subject named by a trusted gateway.

        The gateway proves it may speak for users with the shared delegation
        key; All Ontology re-checks the same key before resolving the subject
        to a user, so the MCP server cannot invent an identity it did not
        receive. The key is never accepted from a browser: this server is the
        only holder on this hop.
        """
        settings = self._settings
        assert settings is not None and settings.delegation_key is not None
        incoming = _incoming_headers()
        presented = incoming.get(DELEGATION_KEY_HEADER, "")
        subject = incoming.get(settings.delegation_subject_header, "").strip()
        if not presented or not secrets.compare_digest(
            presented, settings.delegation_key
        ):
            raise ToolError(
                "This MCP server only accepts calls from its trusted gateway: "
                "send the configured delegation key header."
            )
        if not subject:
            raise ToolError(
                "The trusted gateway must name the caller in the "
                f"{settings.delegation_subject_header} header."
            )

        for name in (
            API_KEY_HEADER,
            BEARER_HEADER,
            DELEGATION_KEY_HEADER,
            settings.delegation_subject_header,
        ):
            if name in request.headers:
                del request.headers[name]
        request.headers[DELEGATION_KEY_HEADER] = settings.delegation_key
        request.headers[settings.delegation_subject_header] = subject
        return request

    def _forward_caller_credential(self, request: httpx.Request) -> httpx.Request:
        """Forward the credential the caller presented to this server.

        All Ontology is the verifier either way: an API token resolves to its
        owner, an SSO bearer token to the user sharing its email or subject.
        Exactly one credential is forwarded so a caller cannot combine two
        identities and have one of them win upstream by accident.
        """
        incoming = _incoming_headers()
        api_key = (incoming.get(API_KEY_HEADER) or "").strip()
        authorization = (incoming.get(BEARER_HEADER) or "").strip()
        for name in (*self._identity_headers(), API_KEY_HEADER, BEARER_HEADER):
            if name in request.headers:
                del request.headers[name]

        if api_key.startswith("all_ontology_"):
            request.headers[API_KEY_HEADER] = api_key
        elif authorization:
            request.headers[BEARER_HEADER] = authorization
        elif api_key:
            request.headers[API_KEY_HEADER] = api_key
        else:
            raise ToolError(
                "This MCP server forwards the caller's own credential. Send an "
                "All Ontology API token (x-api-key) or a signed-in bearer token "
                "with every request."
            )
        return request

    def _forward_signed_in_token(self, request: httpx.Request) -> httpx.Request:
        token = all_ontology_access_token()
        if not token:
            raise ToolError(
                "This request carried no signed-in session. Sign in again "
                "through the All Ontology deployment this server is pointed at."
            )

        # A request must never carry two identities, whichever slot the
        # caller's arrived in, so drop both before setting ours.
        for name in (*self._identity_headers(), API_KEY_HEADER, BEARER_HEADER):
            if name in request.headers:
                del request.headers[name]
        request.headers[BEARER_HEADER] = f"Bearer {token}"
        return request

    def _identity_headers(self) -> tuple[str, ...]:
        """Delegation headers a caller might smuggle; never forwarded by other modes."""
        subject = (
            self._settings.delegation_subject_header
            if self._settings is not None
            else "x-all-ontology-subject"
        )
        return (DELEGATION_KEY_HEADER, subject)


def build_client(settings: Settings) -> httpx.AsyncClient:
    """HTTP client for the public All Ontology API.

    The credential is not set here: :class:`CallerAuth` resolves one per
    request, so a single client can serve callers with different identities.
    """
    return httpx.AsyncClient(
        base_url=settings.api_url,
        auth=CallerAuth(settings),
        timeout=settings.timeout_s,
        # An agent harness may fan out across several tools at once.
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


def build_server(settings: Settings) -> tuple[FastMCP, httpx.AsyncClient]:
    """Build the server and the client it owns.

    The client is returned rather than hidden so the caller can close it; it
    outlives any single request because the streaming chat tool holds it open.
    """
    spec = load_spec(settings)
    client = build_client(settings)

    # Delegation and passthrough both replace the browser sign-in handshake:
    # the credential arrives on each request instead of at initialize.
    request_auth = (
        None
        if settings.delegation_key or settings.passthrough_auth
        else build_all_ontology_auth(settings)
    )
    mcp: FastMCP = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name=SERVER_NAME,
        route_maps=route_maps(),
        mcp_names=names_by_operation_id(spec),
        mcp_component_fn=apply_description,
        # Forwarded to the FastMCP constructor. Without an explicit version the
        # handshake advertises FastMCP's own, which reads as an All Ontology version to
        # anyone looking at the client's server list.
        instructions=INSTRUCTIONS,
        version=get_version(),
        icons=load_icons(),
        auth=request_auth,
    )

    chat.register(mcp, settings, client)
    readiness.register(mcp, settings, client)

    if settings.delegation_key:
        mode = "delegated identity (trusted gateway names the user)"
    elif settings.passthrough_auth:
        mode = "caller credential passthrough"
    else:
        mode = "per-user OAuth sign-in"
    logger.info(
        "All Ontology MCP server built against %s (spec: %s) in %s mode.",
        settings.api_url,
        settings.spec_path,
        mode,
    )
    return mcp, client


__all__ = [
    "API_KEY_HEADER",
    "BEARER_HEADER",
    "DELEGATION_KEY_HEADER",
    "ICON_PATH",
    "INSTRUCTIONS",
    "SERVER_NAME",
    "CallerAuth",
    "build_client",
    "build_server",
    "load_icons",
    "load_spec",
]
