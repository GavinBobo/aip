# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Env-derived Postgres connection config, shared across the codebase.

Not VDB-specific: the server, ingestion service, and dev tools all build the
local Postgres URL from the same ``POSTGRES_*`` env vars via this helper.
"""

from __future__ import annotations

import os

#: Schema holding the tables Prisma owns (`conversations`, `messages`,
#: `acronyms`, `prompts`, `configurations`, `conversation_analytics`, auth).
#:
#: The backend only ever *reads and writes rows* here -- the shape is Prisma's,
#: declared in `frontend/prisma/schema.prisma`, and Alembic deliberately does not
#: manage it. Every backend statement against these tables must qualify them with
#: this constant.
#:
#: Qualifying is not optional politeness. These tables used to live in `public`
#: and were reached unqualified, which worked only because the role's
#: `search_path` happened to resolve there. When they moved to `frontend` every
#: such statement broke -- and mostly broke *quietly*, because the call sites
#: catch their exceptions: the semantic-compilation flag silently read as
#: disabled, and acronyms and custom prompts silently came back empty. A
#: schema-qualified name cannot fail that way.
FRONTEND_SCHEMA = "frontend"


def get_postgres_connection_string() -> str:
    """Build the local Postgres URL from ``POSTGRES_*`` env vars.

    ``database`` overrides ``POSTGRES_DATABASE`` when given (useful for
    multi-DB tools that target several databases on the same instance).
    """
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    db = os.environ.get("POSTGRES_DATABASE", "all_ontology")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}{sslmode_suffix()}"


def sslmode_suffix() -> str:
    """``?sslmode=<mode>`` for the connection URL, or ``''`` when unset.

    Empty by default on purpose: the bundled development Postgres and most
    in-cluster instances accept plaintext, and defaulting to ``require`` would
    break every setup that works today. A company-hosted instance that mandates
    TLS sets ``POSTGRES_SSLMODE=require`` (or ``verify-full``), and libpq —
    which psycopg 3 uses — reads the parameter straight off the URL.

    The asyncpg consumers cannot use this spelling and translate it themselves;
    see ``all_ontology/vdb/postgres.py: _to_async_url``.
    """
    mode = os.environ.get("POSTGRES_SSLMODE", "").strip()
    if not mode:
        return ""
    return f"?sslmode={mode}"
