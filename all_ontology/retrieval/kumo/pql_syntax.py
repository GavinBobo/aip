# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""PQL syntax helpers and the cheap, pre-backend static validator."""

from __future__ import annotations

import re


def quote_ident(identifier: str, char: str = '"') -> str:
    """Quote a SQL identifier with *char*, escaping embedded occurrences by doubling."""
    return char + identifier.replace(char, char * 2) + char


def _sql_table(table: str, table_names: dict[str, str] | None) -> str:
    """Schema-qualified SQL name for a graph table, else a quoted bare name.

    The Kumo graph refers to tables by their bare name (``GPUS``); the live
    database needs ``"SCHEMA"."GPUS"``. ``table_names`` maps the graph name to
    that qualified form. Graph and PQL table names carry the catalog's real
    casing, so the lookup is an exact match.
    """
    if table_names:
        qualified = table_names.get(table)
        if qualified is not None:
            return qualified
    return quote_ident(table)


_FROM_JOIN_RE = re.compile(r'\b(FROM|JOIN)\s+"?([A-Za-z_]\w*)"?', re.IGNORECASE)


def _qualify_from_clauses(sql: str, table_names: dict[str, str] | None) -> str:
    """Schema-qualify bare table names after FROM / JOIN in model-authored SQL.

    Only the table token following FROM / JOIN is rewritten (quoted or not), so
    column references are untouched. Used for the LLM's entity-selection SQL,
    whose table names are the bare graph names (matched on the catalog's real
    casing).
    """
    if not table_names:
        return sql

    def repl(match: "re.Match[str]") -> str:
        qualified = table_names.get(match.group(2))
        return f"{match.group(1)} {qualified}" if qualified else match.group(0)

    return _FROM_JOIN_RE.sub(repl, sql)


_PQL_FENCE = re.compile(r"```pql\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_GENERIC_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_IDENT = r"(?:`[^`\r\n]+`|[A-Za-z_]\w*)"


def unquote_name(name: str) -> str:
    """Strips the backticks a quoted PQL name carries."""
    if len(name) >= 2 and name.startswith("`") and name.endswith("`"):
        return name[1:-1]
    return name


def quote_name(name: str) -> str:
    """Quotes a name only when PQL's bare identifier cannot spell it."""
    if name == "*" or re.fullmatch(r"[A-Za-z_]\w*", name):
        return name
    return f"`{name}`"


_PREDICT_LINE_START = re.compile(r"(?im)^[ \t]*PREDICT\b")
_QUALIFIED_IDENTIFIER = re.compile(rf"(?P<table>{_IDENT})\.(?P<column>{_IDENT})")
_GRAPH_TABLE_LINE = re.compile(
    rf"(?m)^(?P<table>{_IDENT}|[^(\r\n]+?)\((?P<columns>[^()]*)\)(?:\s+--.*)?$"
)
_FOR_ENTITY = re.compile(
    rf"\bFOR\s+(?P<each>EACH\s+)?(?P<table>{_IDENT})\.(?P<pk>{_IDENT})",
    re.IGNORECASE,
)
_LIST_DISTINCT = re.compile(r"\bLIST_DISTINCT\b", re.IGNORECASE)
_CHANGE_INTENT = re.compile(
    r"\b(gain|gains|loss|losses|increase|increases|decrease|decreases|change|changes|delta|growth|"
    r"decline|declines|drop|drops|rise|rises|up|down)\b",
    re.IGNORECASE,
)
_CHANGE_COL_MARKER = re.compile(
    r"(?:^|_)(?:change|delta|qoq|mom|yoy)(?:_|$)", re.IGNORECASE
)
_WINDOWED_AGG_TARGET = re.compile(
    rf"\b(SUM|AVG|MIN|MAX)\s*\(\s*({_IDENT})\s*\.\s*({_IDENT})"
    r"\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*([A-Za-z]+)\s*\)",
    re.IGNORECASE,
)
_METRIC_SUFFIX = re.compile(
    r"(_usd|_amount|_count|_qty|_rate|_pct|_percent|_value|_total)$", re.IGNORECASE
)

# --- Static PQL lint (catches known-bad shapes BEFORE the backend, with an actionable repair message) ----
# These shapes pass KumoRFM's cheap parse (validate_pql) yet fail at predict time with opaque backend errors
# (Invalid Syntax, Internal Server Error, Missing foreign key). Catching them here turns a slow, uninformative
# multi-attempt failure into a targeted repair signal the next generation can actually act on.
_SELECT_TOKEN = re.compile(r"\bSELECT\b", re.IGNORECASE)
_PQL_BANNED_TIME_FUNCS = re.compile(
    r"\b(CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME|GETDATE|SYSDATE|SYSTIMESTAMP|TODAY)\b|\bNOW\s*\(",
    re.IGNORECASE,
)
_RANK_TOP = re.compile(r"\bRANK\s+TOP\b", re.IGNORECASE)
_FOR_EACH_KW = re.compile(r"\bFOR\s+EACH\b", re.IGNORECASE)
_AGG_OPEN = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX|LIST_DISTINCT)\s*\(", re.IGNORECASE)
_TABLE_COL = re.compile(rf"({_IDENT})\s*\.\s*({_IDENT}|\*)")
# The trailing ``, <start>, <end>, <unit>`` window args inside an aggregation (e.g. ``, 0, 90, days``).
_WINDOW_TAIL = re.compile(r",\s*-?\d+\s*,\s*-?\d+\s*,\s*[A-Za-z]+\s*$")
_REL_COMPARISON = re.compile(rf"({_IDENT})\s*\.\s*({_IDENT})\s*(>=|<=|>|<(?!>))")
_NON_ORDINAL_STYPES = frozenset({"categorical", "multicategorical", "ID", "text"})


class PqlStaticError(ValueError):
    """A PQL shape rejected by the cheap static lint before it reaches the backend."""


def _balanced_paren_body(text: str, open_idx: int) -> str:
    """Return the substring inside the parenthesis that opens at ``open_idx`` (handles nesting)."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i]
    return text[open_idx + 1 :]


def _aggregation_clauses(pql: str) -> list[tuple[str, str | None]]:
    """Yield ``(aggregated_table, inner_where_or_None)`` for each ``AGG(<table>.* [WHERE ...], ...)``.

    The inner WHERE is the part of the aggregation body after ``WHERE`` and before the trailing window args;
    the FOR-EACH entity filter lives outside the parens and is intentionally not returned here.

    The table name comes back unquoted, matching what ``parse_entity`` and the graph edges carry: a name
    PQL has to backtick (one containing a space) would otherwise never compare equal to either.
    """
    clauses: list[tuple[str, str | None]] = []
    for match in _AGG_OPEN.finditer(pql):
        body = _balanced_paren_body(pql, match.end() - 1)
        body = _WINDOW_TAIL.sub("", body).strip()
        parts = re.split(r"\bWHERE\b", body, maxsplit=1, flags=re.IGNORECASE)
        table_match = _TABLE_COL.search(parts[0])
        if not table_match:
            continue
        where_clause = parts[1] if len(parts) > 1 else None
        clauses.append((unquote_name(table_match.group(1)), where_clause))
    return clauses


def validate_pql_static(
    pql: str,
    *,
    edges: list[tuple[str, str, str]] | None = None,
    col_stypes: dict[str, dict[str, str]] | None = None,
) -> None:
    """Reject known-bad PQL shapes with an actionable message, before the backend is ever called.

    Catches the failure families seen in the ERP stress sweep: a SQL subquery inside PQL/``ASSUMING``, SQL
    time functions like ``CURRENT_TIMESTAMP``, a cross-table predicate inside an aggregation ``WHERE``, a
    misplaced ``RANK TOP``, and — when ``edges`` (the graph's ``(src, fk, dst)`` foreign keys) are supplied —
    an aggregation whose event table has no DIRECT foreign key to the prediction entity (KumoRFM does not
    traverse multi-hop paths inside an aggregation). When ``col_stypes`` (``table -> {column -> declared
    stype}``) is supplied, it also rejects a ``>``/``<`` comparison against a declared non-ordinal column.
    Raises :class:`PqlStaticError` (a ``ValueError``) so it flows into the existing repair loop as
    ``prev_error``.
    """
    text = pql.strip()
    if not text:
        raise PqlStaticError("Empty PQL.")

    # 1. PQL has no subqueries — a stray SELECT means the model wrote SQL inside the PREDICT (e.g. ASSUMING).
    if _SELECT_TOKEN.search(text):
        raise PqlStaticError(
            "PQL has no SQL subqueries — remove the SELECT. To reach a related table, rely on the graph's "
            "foreign keys (the entity→event link is implicit); to restrict entities, use a plain WHERE on the "
            "entity table after FOR EACH; and put any entity-selection SQL in the SEPARATE ```sql block — "
            "never inside PREDICT and never inside ASSUMING."
        )

    # 2. SQL time functions are not valid in PQL — the forward window is the (start, end, unit) args.
    banned = _PQL_BANNED_TIME_FUNCS.search(text)
    if banned:
        raise PqlStaticError(
            f"PQL does not support the SQL time expression '{banned.group(0).strip()}'. The prediction window "
            "is already relative to the data's anchor time via the (start, end, unit) arguments. To restrict "
            "to entities in a future window (e.g. open / at-risk orders), do that date filter in the SEPARATE "
            "entity-selection ```sql block, not inside the PQL."
        )

    # 3. RANK TOP belongs immediately after the target, BEFORE FOR EACH — never after it.
    for_each = _FOR_EACH_KW.search(text)
    if for_each:
        rank = _RANK_TOP.search(text)
        if rank and rank.start() > for_each.start():
            raise PqlStaticError(
                "RANK TOP is misplaced: it goes immediately after the target and BEFORE FOR EACH "
                "(PREDICT <target> RANK TOP k FOR EACH <entity>.<pk>), not after it. Move it, or drop it — a "
                "binary/regression target needs no RANK because its scores already rank the entities."
            )

    # 4. An aggregation's WHERE can only filter the aggregated event table (no cross-table predicate).
    for agg_table, where_clause in _aggregation_clauses(text):
        if not where_clause:
            continue
        for tbl, _col in _TABLE_COL.findall(where_clause):
            if unquote_name(tbl).lower() != agg_table.lower():
                raise PqlStaticError(
                    f"The WHERE inside the {agg_table} aggregation can only filter columns of '{agg_table}' "
                    f"(the aggregated event table); it references '{tbl}', which PQL cannot express as a "
                    f"cross-table predicate inside an aggregation. Drop the '{tbl}.' condition (or use a column "
                    f"that lives on '{agg_table}'); to scope by a related table's attribute, filter the "
                    f"entities in the entity-selection ```sql block instead."
                )

    # 5. Each aggregation's event table must have a DIRECT foreign key to the FOR EACH entity. KumoRFM does not
    #    auto-traverse multi-hop paths inside an aggregation (e.g. po_receipts -> purchase_orders -> suppliers),
    #    so it rejects such queries with an opaque "Missing foreign key". Catch it here and name the tables that
    #    DO link directly to the entity (typically a rollup), so the repair lands on a valid shape.
    if edges:
        entity = parse_entity(text)
        if entity is not None:
            entity_table = entity[0].lower()
            direct = sorted(
                {src for src, _fk, dst in edges if dst.lower() == entity_table}
            )
            direct_lower = {t.lower() for t in direct}
            for agg_table, _where in _aggregation_clauses(text):
                at = agg_table.lower()
                if at != entity_table and at not in direct_lower:
                    alts = (
                        ", ".join(direct)
                        if direct
                        else "(none — pick a different entity)"
                    )
                    raise PqlStaticError(
                        f"'{agg_table}' has no direct foreign key to the prediction entity '{entity[0]}', and "
                        f"KumoRFM cannot traverse a multi-hop path inside an aggregation. Aggregate a table that "
                        f"links DIRECTLY to '{entity[0]}' instead (one of: {alts}) — a monthly/daily rollup is "
                        f"usually the right choice — or change the entity. To bring in an attribute that lives "
                        f"two hops away, pre-filter the entities in the entity-selection ```sql block."
                    )

    if col_stypes:
        for tbl, col, op in _REL_COMPARISON.findall(text):
            stype = col_stypes.get(unquote_name(tbl).lower(), {}).get(
                unquote_name(col).lower()
            )
            if stype in _NON_ORDINAL_STYPES:
                raise PqlStaticError(
                    f"'{tbl}.{col}' is a {stype} column and cannot be compared with '{op}'. Compare a "
                    f"categorical column with '=' / '!=' against one of its sampled values (see the column "
                    f"list) instead — e.g. a status/flag value — or use a numeric column for a threshold."
                )


def parse_entity(pql: str) -> tuple[str, str] | None:
    """Parse the entity from population and single-entity PQL ``FOR`` clauses."""
    match = _FOR_ENTITY.search(pql)
    if match is None:
        return None
    return (unquote_name(match.group("table")), unquote_name(match.group("pk")))
