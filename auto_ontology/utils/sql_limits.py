# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dialect-aware row limiting for the SQL this codebase writes itself.

Most engines accept ``LIMIT n``. T-SQL does not: it spells the same thing
``SELECT TOP (n)``, and a probe carrying ``LIMIT`` fails with a syntax error
rather than returning too many rows. The profiling and probe queries build
``LIMIT`` by hand (they are not model-authored, so the text-to-SQL prompt rules
never see them), which would silently disable profiling on SQL Server.

A statement that already carries a limit is left alone, so a caller keeps its
own bound. The dialect name is the connector's ``dialect`` property.
"""

from __future__ import annotations

import logging
import re

import sqlglot

logger = logging.getLogger(__name__)

# Dialects where ``LIMIT`` is not valid and sqlglot renders the equivalent
# ``TOP`` form instead.
_TOP_STYLE_DIALECTS = frozenset({"tsql"})

_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)


def with_row_limit(sql: str, limit: int, dialect: str | None = None) -> str:
    """Bound *sql* to at most *limit* rows, spelled for *dialect*.

    Rewrites the statement through sqlglot only for dialects that cannot take
    ``LIMIT``; everywhere else the SQL is returned unchanged except for an
    appended clause, which keeps existing behaviour and existing tests
    byte-for-byte. A statement sqlglot cannot parse is returned untouched: the
    callers already treat a failed probe as "no data" and log it, which is more
    useful than raising here.
    """
    stripped = sql.strip().rstrip(";").strip()
    normalized = (dialect or "").strip().lower()

    if normalized in _TOP_STYLE_DIALECTS:
        try:
            tree = sqlglot.parse_one(stripped, dialect=normalized)
            if tree.args.get("limit") is None:
                tree = tree.limit(limit)
            return tree.sql(dialect=normalized)
        except Exception:
            logger.warning(
                "Could not apply a %s row limit; running the probe unbounded",
                normalized,
                exc_info=True,
            )
            return stripped

    if _LIMIT_RE.search(stripped):
        return stripped
    return f"{stripped} LIMIT {limit}"


__all__ = ["with_row_limit"]
