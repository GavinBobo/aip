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
        # The word can appear in a literal or a comment (``WHERE name = 'limit'``)
        # while the statement is still unbounded, so confirm it is a real clause
        # before trusting it. Text sqlglot cannot parse keeps the old
        # "already limited" assumption rather than doubling up a clause.
        if _has_limit_clause(stripped, normalized):
            return stripped
    clause = f"LIMIT {limit}"
    if _ends_in_line_comment(stripped):
        # ``SELECT ... -- note`` would swallow an inline clause, leaving the
        # query unbounded; a new line ends the comment first.
        return f"{stripped}\n{clause}"
    return f"{stripped} {clause}"


def _has_limit_clause(sql: str, dialect: str) -> bool:
    """True when *sql* really carries a ``LIMIT``/``TOP``/``FETCH`` bound."""
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect or None)
    except Exception:
        return True
    # sqlglot puts ``LIMIT``, ``TOP`` and ``OFFSET ... FETCH`` all in ``limit``.
    return tree.args.get("limit") is not None


def _ends_in_line_comment(sql: str) -> bool:
    """True when the last line of *sql* ends inside a ``--`` comment."""
    last = sql.rsplit("\n", 1)[-1]
    in_quote = False
    index = 0
    while index < len(last):
        char = last[index]
        if in_quote and char == "\\":
            index += 2
            continue
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and last[index : index + 2] == "--":
            return True
        index += 1
    return False


__all__ = ["with_row_limit"]
