# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Text to PQL pipeline (the twin of ``sql_gen``): retrieve, generate, validate, predict, repair.

Differences from SQL generation:

* The model emits a PQL query **and**, optionally, an *entity-selection* read-only SQL that scopes which
  entities to score (the D4 ``SQL pre-filter -> entity-ID list -> predict(indices=...)`` pattern).
* Validity is checked with the **cheap** graph parse (``KumoModel.validate_pql`` -> ``parse_query``, no
  inference): its error is the repair signal. ``predict()`` then produces the actual answer (and also
  self-validates). Entity scaling above the per-call cap is handled by ``KumoModel.predict`` (batch mode).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from all_ontology.connectors.base import SQLDatabase

from all_ontology.retrieval.kumo.budget import RefusedForCapacity
from all_ontology.retrieval.kumo.pql_errors import (  # noqa: F401
    _friendly_backend_unavailable_message,
    _friendly_empty_context_message,
    _friendly_unsupported_message,
    _is_context_capacity_error,
    _is_context_size_limit_error,
    _is_empty_context_error,
    _is_retryable_exec_error,
    _is_spurious_predict_parse_error,
    _is_transient_exec_error,
    _is_unsupported_shape_error,
    _retry_at_full_neighbourhood,
)
from all_ontology.retrieval.kumo.pql_execution import (  # noqa: F401
    _GROUP_BY_MAX_ENTITIES,
    _NeighbourhoodMemo,
    _PREDICT_BATCH_SIZE,
    _emit_retry_note,
    _explain_resilient,
    _predict_in_batches,
    _predict_resilient,
    _predict_with_retry,
)
from all_ontology.retrieval.kumo.pql_results import (  # noqa: F401
    PqlGroupByError,
    _entity_id_column,
    _is_existence_count_pql,
    _is_forecast,
    _order_forecast,
    _rank_prediction,
    aggregate_prediction_by,
)
from all_ontology.retrieval.kumo.pql_syntax import (  # noqa: F401
    _AGG_OPEN,
    _CHANGE_COL_MARKER,
    _CHANGE_INTENT,
    _FOR_EACH_KW,
    _FOR_ENTITY,
    _FROM_JOIN_RE,
    _GENERIC_FENCE,
    _GRAPH_TABLE_LINE,
    _IDENT,
    _LIST_DISTINCT,
    _METRIC_SUFFIX,
    _NON_ORDINAL_STYPES,
    _PQL_BANNED_TIME_FUNCS,
    _PQL_FENCE,
    _PREDICT_LINE_START,
    _QUALIFIED_IDENTIFIER,
    _RANK_TOP,
    _REL_COMPARISON,
    _SELECT_TOKEN,
    _TABLE_COL,
    _WINDOWED_AGG_TARGET,
    _WINDOW_TAIL,
    PqlStaticError,
    _aggregation_clauses,
    _balanced_paren_body,
    _qualify_from_clauses,
    _sql_table,
    parse_entity,
    quote_ident,
    quote_name,
    unquote_name,
    validate_pql_static,
)
from all_ontology.retrieval.kumo.prompts import build_pql_prompt
from all_ontology.utils.llm_invoke import invoke_text

logger = logging.getLogger(__name__)




class PqlValidatorModel(Protocol):
    """Minimal KumoModel interface used here (satisfied by :class:`kumo_rfm.kumo_client.KumoModel`)."""

    def validate_pql(self, query: str) -> Any: ...

    def predict(
        self, query: str, indices: list[Any] | None = None, **kwargs: Any
    ) -> Any: ...


@dataclass
class PqlGenerationResult:
    """Outcome of a text-to-PQL generation + prediction."""

    question: str
    pql: str = ""
    entity_sql: str | None = None
    success: bool = False
    attempts: int = 0
    error: str | None = None
    num_entities: int = 0
    population: int = 0
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    explanation: str | None = None
    explanation_warning: str | None = None
    explanation_details: Any = None
    group_by: str | None = None
    truncated: bool = False
    note: str | None = None
    prediction_table: str | None = None
    prediction_table_columns: list[str] = field(default_factory=list)


class PqlPopulationTooLargeError(RefusedForCapacity, ValueError):
    """A whole-population question over more entities than one run can score.

    Distinct from a query the repair loop can fix: no rewriting of the PQL makes
    the population smaller, so this is surfaced to the asker rather than retried.
    """


def _population_refusal(pql: str, population: int, cap: int) -> str:
    """Say what was asked for, what it would cost, and what to ask instead.

    Named rather than rounded down: a total over a slice of the population,
    presented as a total, is wrong in a way the reader cannot see, so this
    refuses instead of answering.
    """
    parsed = parse_entity(pql)
    entity = f"{parsed[0]}" if parsed else "entities"
    covered = (
        "an unknown number of"
        if population >= _UNCOUNTED_POPULATION
        else f"{population:,}"
    )
    return (
        f"This question covers {covered} {entity}, and one prediction run scores at "
        f"most {cap:,}. Answering it from part of them would report a total that "
        f"reads like the whole. Ask about a narrower group, such as one segment, "
        f"region or time period, and the answer will cover all of it."
    )


def extract_pql(text: str) -> str:
    """Pull a PQL statement from a model response.

    An unfenced response must put ``PREDICT`` at the start of a line. This
    avoids treating prose such as "we need to predict ..." as executable PQL.
    PQL is a single statement, so only that line is accepted when no explicit
    fence/tag bounds it.
    """
    match = _PQL_FENCE.search(text)
    if match and match.group(1).strip():
        candidate = match.group(1)
        bounded = True
    else:
        tag = re.search(r"\[PQL\](.*?)\[/PQL\]", text, re.DOTALL | re.IGNORECASE)
        candidate = tag.group(1) if tag else text
        bounded = tag is not None
    start = _PREDICT_LINE_START.search(candidate)
    if start is None:
        return ""
    pql = candidate[start.start() :]
    if not bounded:
        pql = pql.splitlines()[0]
    return pql.strip().rstrip(";").strip()


def canonicalize_pql_identifiers(pql: str, graph_ddl: str) -> str:
    """Match qualified PQL identifiers to the graph's exact casing.

    Snowflake commonly reports uppercase identifiers while PostgreSQL and
    Databricks commonly report lowercase identifiers. KumoRFM's parser is
    case-sensitive, so generated identifiers are rewritten using graph metadata
    instead of connector-specific assumptions.
    """
    tables: dict[str, tuple[str, dict[str, str]]] = {}
    for match in _GRAPH_TABLE_LINE.finditer(graph_ddl):
        table = unquote_name(match.group("table"))
        columns: dict[str, str] = {}
        for definition in match.group("columns").split(","):
            parts = definition.strip().rsplit(maxsplit=1)
            if parts:
                # The DDL quotes a name PQL cannot spell bare, and the lookup is by
                # the name itself: keyed with the backticks still on, a quoted column
                # would never match and would keep whatever casing the model guessed.
                column = unquote_name(parts[0])
                columns[column.casefold()] = column
        tables[table.casefold()] = (table, columns)

    def replace(match: re.Match[str]) -> str:
        entry = tables.get(unquote_name(match.group("table")).casefold())
        if entry is None:
            return match.group(0)
        table, columns = entry
        raw_column = unquote_name(match.group("column"))
        column = columns.get(raw_column.casefold(), raw_column)
        return f"{quote_name(table)}.{quote_name(column)}"

    return _QUALIFIED_IDENTIFIER.sub(replace, pql)


def extract_entity_sql(text: str) -> str | None:
    """Pull the optional entity-selection SQL (a ```sql block that is not the ```pql block)."""
    for match in _GENERIC_FENCE.finditer(text):
        block = match.group(1).strip()
        if (
            block
            and "PREDICT" not in block.upper()
            and re.match(r"(?is)^\s*(WITH|SELECT)\b", block)
        ):
            return block.rstrip(";").strip()
    return None




def _metric_stem(column: str) -> str:
    """Return the business-metric stem from a numeric column name."""
    return _METRIC_SUFFIX.sub("", column.lower())


def _explicit_change_candidate(
    table: str,
    column: str,
    *,
    col_stypes: dict[str, dict[str, str]] | None,
    schema_text: str = "",
) -> str | None:
    """Find a same-table explicit change/delta target for a level metric column.

    This is intentionally schema-driven and domain-agnostic: for a question about gains/losses/change, if
    the model picked ``revenue_usd`` and the same table exposes ``revenue_qoq_change_usd``, the latter is the
    target. Columns already containing a change marker are left alone.
    """
    if _CHANGE_COL_MARKER.search(column):
        return None
    table_cols: dict[str, str] = {}
    if col_stypes:
        for t_name, cols in col_stypes.items():
            if t_name.lower() == table.lower():
                table_cols = {c.lower(): c for c in cols}
                break
    if schema_text:
        table_col_pattern = re.compile(
            rf"\b{re.escape(table)}\.([A-Za-z_]\w*)\b", re.IGNORECASE
        )
        for match in table_col_pattern.finditer(schema_text):
            table_cols.setdefault(match.group(1).lower(), match.group(1))
        block_pattern = re.compile(
            rf"\b{re.escape(table)}\b\s*\((.*?)\)", re.IGNORECASE | re.DOTALL
        )
        for match in block_pattern.finditer(schema_text):
            for name in re.findall(r"\b[A-Za-z_]\w*\b", match.group(1)):
                if name.upper() not in {
                    "CREATE",
                    "TABLE",
                    "PRIMARY",
                    "KEY",
                    "FOREIGN",
                    "REFERENCES",
                }:
                    table_cols.setdefault(name.lower(), name)
    if not table_cols:
        return None
    stem = _metric_stem(column)
    candidates = [
        original
        for lowered, original in table_cols.items()
        if _CHANGE_COL_MARKER.search(lowered)
        and (lowered.startswith(stem + "_") or stem in lowered.split("_"))
    ]
    if not candidates:
        return None
    original_lower = column.lower()

    def score(name: str) -> tuple[int, int, int, int]:
        lowered = name.lower()
        return (
            1 if "qoq" in lowered else 0,
            1 if original_lower.endswith("_usd") and lowered.endswith("_usd") else 0,
            1 if "pct" not in lowered and "percent" not in lowered else 0,
            -len(lowered),
        )

    return max(candidates, key=score)


def prefer_explicit_change_targets(
    pql: str,
    question: str,
    *,
    col_stypes: dict[str, dict[str, str]] | None = None,
    schema_text: str = "",
) -> str:
    """Rewrite level targets to explicit change targets for gain/loss/change questions when available."""
    if not _CHANGE_INTENT.search(question or ""):
        return pql

    def repl(match: re.Match[str]) -> str:
        agg, table, column, start, end, unit = match.groups()
        replacement = _explicit_change_candidate(
            unquote_name(table),
            unquote_name(column),
            col_stypes=col_stypes,
            schema_text=schema_text,
        )
        if not replacement:
            return match.group(0)
        return f"{agg}({table}.{quote_name(replacement)}, {start}, {end}, {unit})"

    return _WINDOWED_AGG_TARGET.sub(repl, pql)


def _count_entities(connector: SQLDatabase, source: str, pk: str) -> int:
    """How many entities the question covers, when a LIMIT query cannot say.

    A count that fails is reported as the cap itself rather than as zero: an
    unknown population must not read as a small one, since that is what would
    let an answer over a slice be presented as an answer over everything.
    """
    try:
        df = connector.execute(
            f"SELECT COUNT(DISTINCT {quote_ident(pk)}) FROM {source} "
            f"WHERE {quote_ident(pk)} IS NOT NULL"
        )
        return int(df.iloc[0, 0]) if not df.empty else 0
    except Exception:
        logger.info("Could not count the entities in %s.", source, exc_info=True)
        return _UNCOUNTED_POPULATION


_UNCOUNTED_POPULATION = 1 << 62


def _resolve_indices(
    pql: str,
    entity_sql: str | None,
    connector: SQLDatabase,
    max_entities: int,
    table_names: dict[str, str] | None = None,
    available_entity_ids: dict[str, list[Any]] | None = None,
) -> tuple[list[Any], int]:
    """Resolve entity IDs, and how many the question really covers.

    An explicit entity-selection query is still executed against the source,
    then intersected with graph IDs. Without a filter, graph IDs are used
    directly instead of issuing a second nondeterministic ``LIMIT`` query whose
    rows may differ from the graph sample.

    The second return value is the size of the population BEFORE any cap, which
    is what tells an answer over a slice apart from an answer over everything.
    Where the only way to learn it is a ``LIMIT`` query that cannot report what
    it left behind, one count is asked for; a count is cheap next to scoring
    every row it counted.
    """
    entity = parse_entity(pql)
    available = (
        available_entity_ids.get(entity[0].casefold())
        if available_entity_ids and entity
        else None
    )
    if entity_sql:
        df = connector.execute(_qualify_from_clauses(entity_sql, table_names))
        ids = df.iloc[:, 0].dropna().tolist() if not df.empty else []
        if available is not None:
            allowed = set(available)
            ids = [value for value in ids if value in allowed]
    elif available is not None:
        ids = available
    else:
        if entity is None:
            return [], 0
        table, pk = entity
        source = _sql_table(table, table_names)
        df = connector.execute(
            f"SELECT DISTINCT {quote_ident(pk)} FROM {source} "
            f"WHERE {quote_ident(pk)} IS NOT NULL LIMIT {int(max_entities)}"
        )
        ids = df.iloc[:, 0].dropna().tolist() if not df.empty else []
        if len(ids) >= max_entities:
            population = _count_entities(connector, source, pk)
            if population > max_entities:
                logger.info("Capping entities from %d to %d.", population, max_entities)
            return ids[:max_entities], population
        return ids, len(ids)
    population = len(ids)
    if population > max_entities:
        logger.info("Capping entities from %d to %d.", population, max_entities)
        ids = ids[:max_entities]
    return ids, population


def _persist_full_prediction(
    prediction: Any,
    *,
    pql: str,
    mirror_path: str,
    table: str,
    lock: Any,
    result: PqlGenerationResult,
) -> None:
    """Write the FULL per-entity prediction to a mirror scratch table for SQL comparison.

    Renames KumoRFM's ``ENTITY`` column to the entity primary key so a follow-up
    ``rfm__sql_query`` can JOIN the scratch table to source tables naturally.
    Best-effort: a persistence failure never fails an otherwise-good prediction.
    """
    from kumo_rfm.predict_store import persist_prediction

    try:
        entity = parse_entity(pql)
        pk = entity[1] if entity else None
        id_col = _entity_id_column(prediction, pk or "")
        frame = prediction
        if pk and id_col != pk:
            frame = prediction.rename(columns={id_col: pk})
        persist_prediction(mirror_path, table, frame, lock=lock)
        result.prediction_table = table
        result.prediction_table_columns = list(frame.columns)
    except Exception:  # noqa: BLE001 - persistence is an enhancement, never a hard dependency
        logger.warning(
            "Failed to persist prediction to scratch table %s", table, exc_info=True
        )


_ANCHOR_TABLE_RE = re.compile(
    rf"(?:SUM|COUNT|AVG|MIN|MAX|FIRST|LAST|LIST_DISTINCT)\s*\(\s*({_IDENT})\.",
    re.IGNORECASE,
)
_ANCHOR_WINDOW_RE = re.compile(
    r",\s*\d+\s*,\s*(\d+)\s*,\s*(day|days|week|weeks|month|months|year|years)\s*\)",
    re.IGNORECASE,
)
_ANCHOR_UNIT_DAYS = {
    "day": 1,
    "days": 1,
    "week": 7,
    "weeks": 7,
    "month": 30,
    "months": 30,
    "year": 365,
    "years": 365,
}


def _forecast_anchor(
    pql: str,
    connector: SQLDatabase,
    time_columns: dict[str, str | None] | None,
    *,
    now: Any = None,
    table_names: dict[str, str] | None = None,
) -> Any:
    """Anchor a forward prediction at *now* (a true "forecast from today"), capped so the
    ``[anchor, anchor + horizon]`` window never runs past the data.

    KumoRFM derives its default anchor from the data's MAX timestamp. On a dataset whose data extends past
    today that makes it forecast a window with no in-context future and return degenerate (collapsed or
    wildly over-extrapolated) predictions. Anchoring at *now* lands the window inside real data; the cap
    keeps it valid even when *now* is already at/after the data's edge. Returns a ``pd.Timestamp`` for
    ``anchor_time``, or ``None`` to let the SDK derive it (non-temporal query / unknown horizon / no time
    column / lookup failure)."""
    if not time_columns:
        return None
    tm = _ANCHOR_TABLE_RE.search(pql or "")
    wm = _ANCHOR_WINDOW_RE.search(pql or "")
    if not tm or not wm:
        return None
    anchor_table = unquote_name(tm.group(1))
    time_col = time_columns.get(anchor_table)
    if not time_col:
        return None
    horizon_days = int(wm.group(1)) * _ANCHOR_UNIT_DAYS[wm.group(2).lower()]
    try:
        import pandas as pd

        df = connector.execute(
            f"SELECT MAX({quote_ident(time_col)}) AS m "
            f"FROM {_sql_table(anchor_table, table_names)}"
        )
        data_max = (
            pd.Timestamp(df.iloc[0, 0])
            if (not df.empty and df.iloc[0, 0] is not None)
            else None
        )
    except Exception:  # noqa: BLE001 - anchor is best-effort; fall back to the SDK default
        return None
    if data_max is None:
        return None
    safe = data_max - pd.Timedelta(days=horizon_days + 7)
    now_ts = (
        pd.Timestamp(now)
        if now is not None
        else pd.Timestamp(pd.Timestamp.today().date())
    )
    return min(now_ts, safe)


_STALE_ANCHOR_DAYS = 31


def _join_notes(*notes: str | None) -> str | None:
    """Keep every note a run has to make, rather than the last one written."""
    kept = [note for note in notes if note]
    return "\n\n".join(kept) if kept else None


def _stale_anchor_note(anchor: Any, *, now: Any = None) -> str | None:
    """Say when a forward prediction is not anchored anywhere near today.

    KumoRFM anchors within the data, so a warehouse that stopped being loaded
    pulls the window back to where the data ends. The prediction is still the
    best one the data supports, but it answers "the next 30 days" as they looked
    from that date, and a reader who is not told reads it as the next 30 days
    from now.
    """
    if anchor is None:
        return None
    import pandas as pd

    anchored = pd.Timestamp(anchor)
    today = (
        pd.Timestamp(now)
        if now is not None
        else pd.Timestamp(pd.Timestamp.today().date())
    )
    behind = (today - anchored).days
    if behind <= _STALE_ANCHOR_DAYS:
        return None
    return (
        f"This prediction is anchored at {anchored.date()}, {behind:,} days ago, "
        f"because that is as far as the data reaches. It is a forecast from that "
        f"date, not from today."
    )


def _resolve_single_index(
    pql: str,
    entity: str | None,
    connector: SQLDatabase,
    table_names: dict[str, str] | None = None,
    available_entity_ids: dict[str, list[Any]] | None = None,
) -> list[Any]:
    """Resolve one entity-id (the PK value to explain) to its correctly-typed value via the read-only guard.

    Matches on the string form of the PK so a user-supplied id (always a string) finds an int/str key alike.
    """
    parsed = parse_entity(pql)
    if parsed is None or entity is None:
        return []
    table, pk = parsed
    if available_entity_ids:
        for value in available_entity_ids.get(table.casefold(), []):
            if str(value) == str(entity):
                return [value]
        return []
    safe = str(entity).replace("'", "''")
    string_type = "VARCHAR"
    df = connector.execute(
        f"SELECT {quote_ident(pk)} FROM {_sql_table(table, table_names)} "
        f"WHERE CAST({quote_ident(pk)} AS {string_type}) = '{safe}' LIMIT 1"
    )
    return df.iloc[:, 0].tolist() if not df.empty else []


def _scope_explain_entity(pql: str, entity: str) -> str:
    """Make an explanation PQL visibly target the exact entity passed to the tool.

    The SDK still receives the warehouse-resolved, correctly typed value through ``indices``. Keeping the
    same scope in the PQL is important for trace accuracy and prevents a model-produced example id from
    describing a different entity than the one actually explained.
    """
    match = _FOR_ENTITY.search(pql)
    if match is None:
        return pql

    table, pk = match.group("table"), match.group("pk")
    tail = pql[match.end() :]
    ident = rf"{re.escape(table)}\s*\.\s*{re.escape(pk)}"
    value = r"(?:'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[^\s]+)"

    # Discard a stale single-entity value or the legacy FOR EACH ... WHERE pk=value form before applying
    # the authoritative entity supplied by the tool call.
    if match.group("each"):
        tail = re.sub(
            rf"^\s+WHERE\s+{ident}\s*=\s*{value}(?=\s*(?:ASSUMING|$))",
            "",
            tail,
            flags=re.IGNORECASE,
        )
    else:
        tail = re.sub(rf"^\s*=\s*{value}", "", tail, count=1, flags=re.IGNORECASE)

    safe = str(entity).replace("'", "''")
    return f"{pql[: match.start()]}FOR {table}.{pk}='{safe}'{tail}"


_GENERIC_ENTITY_FILTER_RE = re.compile(
    rf"(?P<head>\bFOR\s+EACH\s+(?P<table>{_IDENT})\.(?P<pk>{_IDENT}))"
    rf"\s+WHERE\s+(?P=table)\.(?P<column>{_IDENT})\s*=\s*'(?P<value>[^']+)'"
    r"(?P<tail>\s*(?:ASSUMING\b.*)?$)",
    re.IGNORECASE,
)
_GENERIC_ENTITY_TYPE_COLUMNS = {"customer_type", "account_type", "entity_type", "type"}


def _strip_unasked_generic_entity_filter(pql: str, question: str) -> str:
    """Remove inferred entity-type filters when the user asked for the whole population.

    LLM repair sometimes turns generic words like "accounts" into a type filter, e.g.
    ``customers.customer_type = 'enterprise'``. That silently narrows top-N predictions. Keep explicit
    user scopes: if the column or value is named in the question, leave the filter intact.
    """
    match = _GENERIC_ENTITY_FILTER_RE.search(pql)
    if not match:
        return pql
    column = match.group("column").lower()
    if column not in _GENERIC_ENTITY_TYPE_COLUMNS:
        return pql
    question_l = (question or "").lower()
    value_l = match.group("value").lower()
    if column in question_l or value_l in question_l:
        return pql
    return (
        pql[: match.start()]
        + match.group("head")
        + match.group("tail")
        + pql[match.end() :]
    )


def predict_all(
    pql: str,
    *,
    kumo_model: PqlValidatorModel,
    connector: SQLDatabase,
    entity_sql: str | None = None,
    max_entities: int = 2000,
    time_columns: dict[str, str | None] | None = None,
    table_names: dict[str, str] | None = None,
) -> Any:
    """Run a pre-built, known-good PQL over the full entity scope and return the COMPLETE prediction frame.

    Unlike :func:`generate_pql`, this takes an explicit PQL (no LLM generation) and does not truncate to a
    preview — callers that must compare or rank *every* scored entity (e.g. a population-wide forecast vs a
    baseline) need all rows. Resolves the entity scope (explicit ``entity_sql`` or the PQL's own WHERE) and
    runs the same accuracy-first resilient predict path as :func:`generate_pql`.
    """
    scope = entity_sql if entity_sql is not None else extract_entity_sql(pql)
    indices, population = _resolve_indices(
        pql, scope, connector, max_entities, table_names
    )
    if population > max_entities:
        raise PqlPopulationTooLargeError(
            _population_refusal(pql, population, max_entities)
        )
    anchor = _forecast_anchor(pql, connector, time_columns, table_names=table_names)

    def _predict_call(idx: list[Any] | None, num_neighbors: list[int] | None) -> Any:
        kw: dict[str, Any] = {}
        if num_neighbors is not None:
            kw["num_neighbors"] = num_neighbors
        if anchor is not None:
            kw["anchor_time"] = anchor
        return kumo_model.predict(pql, indices=idx or None, **kw)

    raw = _predict_in_batches(
        indices, _predict_call, device_assert_terminal=_is_existence_count_pql(pql)
    )
    return _rank_prediction(raw)


def generate_pql(
    question: str,
    *,
    llm: BaseChatModel,
    kumo_model: PqlValidatorModel,
    connector: SQLDatabase,
    graph_ddl: str,
    graph_edges: list[tuple[str, str, str]] | None = None,
    graph_col_stypes: dict[str, dict[str, str]] | None = None,
    column_reference: str = "",
    vector_store: Any = None,
    success_cache: Any = None,
    dataset: str = "",
    max_tries: int = 5,
    escalation_llm: BaseChatModel | None = None,
    max_entities: int = 2000,
    max_preview_rows: int = 50,
    explain: bool = False,
    explain_entity: str | None = None,
    on_pql: Callable[[str, str | None], None] | None = None,
    group_by: str | None = None,
    mirror_path: str | None = None,
    persist_table: str | None = None,
    persist_lock: Any = None,
    time_columns: dict[str, str | None] | None = None,
    table_names: dict[str, str] | None = None,
    available_entity_ids: dict[str, list[Any]] | None = None,
    examples: list[dict[str, str]] | None = None,
) -> PqlGenerationResult:
    """Generate a PQL, validate it cheaply against the graph, scope entities, and predict (with repair).

    The repair signal is the cheap ``validate_pql`` parse error (or a ``predict`` error); on failure
    ``(prev_pql, error)`` is fed back. ``escalation_llm`` handles the final attempt (D11).

    ``examples`` are verified ``{question, query}`` PQL few-shots (retrieved from the
    ``PqlAnalysis`` corpus); they populate the prompt's "Verified examples" section.
    """
    examples = examples or []
    docs: list[str] = []

    result = PqlGenerationResult(question=question)
    prev_pql: str | None = None
    prev_error: str | None = None
    # Shared across every attempt of this run so the backoff ladder is not re-walked from
    # the full neighbourhood each time (see _NeighbourhoodMemo).
    neighbourhood_memo = _NeighbourhoodMemo()

    # Snowflake stores unquoted identifiers uppercase (so the graph tables are
    # uppercase); tell the LLM to match that case in the PQL.
    try:
        dialect = getattr(connector, "dialect", None)
    except Exception:  # noqa: BLE001 - dialect is a property; never fail generation over it
        dialect = None

    for attempt in range(1, max_tries + 1):
        active_llm = (
            escalation_llm
            if (escalation_llm is not None and attempt == max_tries)
            else llm
        )
        prompt = build_pql_prompt(
            graph_ddl=graph_ddl,
            columns=column_reference,
            docs=docs,
            examples=examples,
            question=question,
            explain_entity=explain_entity if explain else None,
            prev_pql=prev_pql,
            prev_error=prev_error,
            dialect=dialect,
        )
        result.attempts = attempt
        try:
            raw = invoke_text(active_llm, prompt)
        except Exception as exc:  # noqa: BLE001 - LLM/gateway failure: record and retry, never crash the run
            prev_error = str(exc)
            result.error = prev_error
            logger.info(
                "PQL attempt %d/%d: LLM generation failed: %s",
                attempt,
                max_tries,
                prev_error[:160],
            )
            continue
        pql = extract_pql(raw)
        if not pql:
            prev_error = (
                "The response did not contain a PQL statement beginning with "
                "PREDICT on its own line."
            )
            result.error = prev_error
            logger.info(
                "PQL attempt %d/%d failed: %s",
                attempt,
                max_tries,
                prev_error,
            )
            continue
        pql = canonicalize_pql_identifiers(pql, graph_ddl)
        pql = prefer_explicit_change_targets(
            pql,
            question,
            col_stypes=graph_col_stypes,
            schema_text="\n".join([graph_ddl, column_reference, *docs]),
        )
        pql = _strip_unasked_generic_entity_filter(pql, question)
        entity_sql = extract_entity_sql(raw)
        if explain and explain_entity:
            pql = _scope_explain_entity(pql, explain_entity)
        result.pql = pql
        result.entity_sql = entity_sql
        if on_pql is not None and pql and pql.strip():
            try:
                on_pql(pql, entity_sql)
            except Exception:  # noqa: BLE001 - surfacing the PQL early must never break the run
                logger.debug("on_pql callback failed", exc_info=True)
        try:
            validate_pql_static(pql, edges=graph_edges, col_stypes=graph_col_stypes)
            kumo_model.validate_pql(pql)
            if explain:
                indices = _resolve_single_index(
                    pql,
                    explain_entity,
                    connector,
                    table_names,
                    available_entity_ids,
                )
                if not indices:
                    raise ValueError(
                        f"Entity '{explain_entity}' not found in the dataset for this query."
                    )

                _anchor = _forecast_anchor(
                    pql, connector, time_columns, table_names=table_names
                )
                result.note = _join_notes(result.note, _stale_anchor_note(_anchor))

                def _explain_call(num_neighbors: list[int] | None) -> Any:
                    kw: dict[str, Any] = {"explain": True, "run_mode": "fast"}
                    if num_neighbors is not None:
                        kw["num_neighbors"] = num_neighbors
                    if _anchor is not None:
                        kw["anchor_time"] = _anchor
                    return kumo_model.predict(pql, indices=indices, **kw)

                expl = _explain_resilient(_explain_call)
                result.num_entities = 1
                result.explanation = getattr(expl, "summary", None)
                result.explanation_warning = getattr(expl, "warning", None)
                result.explanation_details = getattr(expl, "details", None)
                prediction = getattr(expl, "prediction", None)
                if prediction is not None and hasattr(prediction, "columns"):
                    if _anchor is not None and not any(
                        str(column).casefold() == "anchor_timestamp"
                        for column in prediction.columns
                    ):
                        prediction = prediction.copy()
                        prediction["ANCHOR_TIMESTAMP"] = _anchor
                    result.columns = list(prediction.columns)
                    result.rows = prediction.head(max_preview_rows).to_dict("records")
                    if persist_table and mirror_path and persist_lock is not None:
                        _persist_full_prediction(
                            prediction,
                            pql=pql,
                            mirror_path=mirror_path,
                            table=persist_table,
                            lock=persist_lock,
                            result=result,
                        )
            else:
                forecast = _is_forecast(pql)
                whole_population = group_by or bool(persist_table)
                entity_cap = (
                    max(max_entities, _GROUP_BY_MAX_ENTITIES)
                    if whole_population
                    else max_entities
                )
                scope_sql = entity_sql
                if group_by and entity_sql:
                    scope_sql = None
                    if re.search(r"\b(WHERE|LIMIT)\b", entity_sql, re.IGNORECASE):
                        result.note = (
                            "A grouped breakdown scores every entity and aggregates by "
                            f"'{group_by}', so the planner's entity filter was not applied — these totals "
                            "cover the whole population. Ask without grouping to filter a sub-population."
                        )
                    result.entity_sql = None
                indices, population = _resolve_indices(
                    pql,
                    scope_sql,
                    connector,
                    entity_cap,
                    table_names,
                    available_entity_ids,
                )
                if whole_population and population > entity_cap:
                    raise PqlPopulationTooLargeError(
                        _population_refusal(pql, population, entity_cap)
                    )
                if forecast:
                    if len(indices) > 1:
                        parsed = parse_entity(pql)
                        entity_table = parsed[0] if parsed else "entity"
                        result.note = (
                            f"LIMITATION: KumoRFM forecasts a multi-period time series for ONE {entity_table} at "
                            f"a time, so a month-by-month forecast for ALL {entity_table}s in one run is not "
                            f"supported. It supports EITHER (a) a multi-horizon forecast for a single "
                            f"{entity_table}, OR (b) a single-horizon prediction across all {entity_table}s. "
                            f"{len(indices)} {entity_table}s matched; shown below is the multi-period forecast "
                            f"for just one ({indices[0]}). To cover the whole population, run a single-horizon "
                            f"prediction across all {entity_table}s first, then a multi-horizon forecast for the "
                            f"few {entity_table}s of interest (one at a time). Tell the user both options and ask "
                            f"which they want — do NOT imply the all-entity month-by-month result was produced."
                        )
                    indices = indices[:1]

                _anchor = _forecast_anchor(
                    pql, connector, time_columns, table_names=table_names
                )
                result.note = _join_notes(result.note, _stale_anchor_note(_anchor))

                def _predict_call(
                    idx: list[Any] | None, num_neighbors: list[int] | None
                ) -> Any:
                    kw: dict[str, Any] = {}
                    if num_neighbors is not None:
                        kw["num_neighbors"] = num_neighbors
                    if _anchor is not None:
                        kw["anchor_time"] = _anchor
                    return kumo_model.predict(pql, indices=idx or None, **kw)

                raw = _predict_in_batches(
                    indices,
                    _predict_call,
                    device_assert_terminal=_is_existence_count_pql(pql),
                    memo=neighbourhood_memo,
                )
                if group_by:
                    if forecast or _LIST_DISTINCT.search(pql):
                        raise PqlGroupByError(
                            "group_by is only supported for per-entity regression/binary predictions, not "
                            "forecasts or link prediction."
                        )
                    entity = parse_entity(pql)
                    if entity is None:
                        raise PqlGroupByError(
                            "Could not determine the prediction entity to group from the PQL."
                        )
                    grouped = aggregate_prediction_by(
                        raw,
                        table=entity[0],
                        pk=entity[1],
                        group_by=group_by,
                        connector=connector,
                        table_names=table_names,
                    )
                    result.group_by = group_by
                    result.num_entities = len(raw)
                    result.population = population
                    result.truncated = population > entity_cap
                    result.columns = list(grouped.columns)
                    result.rows = grouped.to_dict("records")
                else:
                    prediction = (
                        _order_forecast(raw) if forecast else _rank_prediction(raw)
                    )
                    result.num_entities = len(indices)
                    result.population = population
                    result.truncated = not forecast and population > entity_cap
                    result.columns = list(prediction.columns)
                    result.rows = prediction.head(max_preview_rows).to_dict("records")
                    if (
                        persist_table
                        and mirror_path
                        and persist_lock is not None
                        and not forecast
                    ):
                        _persist_full_prediction(
                            prediction,
                            pql=pql,
                            mirror_path=mirror_path,
                            table=persist_table,
                            lock=persist_lock,
                            result=result,
                        )
            result.success = True
            result.error = None
            # Success-cache omitted with the RAG port (no vector store to write back to).
            return result
        except PqlPopulationTooLargeError as exc:
            result.error = str(exc)
            logger.info("Prediction refused, population too large: %s", str(exc)[:160])
            break
        except PqlGroupByError as exc:
            # A bad group-by (unknown column / un-aggregatable target) is a usage error, not a query the repair
            # loop can fix — surface it immediately with the actionable message.
            result.error = str(exc)
            logger.info("Grouped-prediction request rejected: %s", str(exc)[:160])
            break
        except Exception as exc:  # noqa: BLE001 - error feeds the repair loop
            prev_pql, prev_error = pql, str(exc)
            result.error = prev_error
            logger.info(
                "PQL attempt %d/%d failed: %s", attempt, max_tries, prev_error[:160]
            )
            if _is_unsupported_shape_error(prev_error):
                if _is_existence_count_pql(pql):
                    result.error = _friendly_unsupported_message(pql, prev_error)
                else:
                    result.error = (
                        "KumoRFM hit an intermittent backend error while computing this prediction "
                        "and it persisted across retries. Please try the question again."
                    )
                logger.info("Device-side assert on a valid query; not regenerating.")
                break
            # A context/GPU-capacity error on a valid query survived the neighbourhood backoff: regenerating
            # the PQL cannot help (the data/graph is what's too big), so stop and report rather than burn
            # the remaining attempts re-hitting the same server limit.
            if _is_context_capacity_error(prev_error):
                logger.info(
                    "Persistent context/GPU-capacity error on a valid query; not regenerating."
                )
                break
            if _is_empty_context_error(prev_error):
                result.error = _friendly_empty_context_message()
                logger.info(
                    "Empty entity set (no context examples) on a valid query; not regenerating."
                )
                break
            # The query passed both validators and the backend still failed (e.g. the NIM
            # answering /v1/predictions with a bare HTTP 500). That is infrastructure, not the
            # query: the predict path already retried it, and the LLM would only regenerate the
            # same statement, so stop instead of burning every remaining attempt on a fault no
            # rewrite can address.
            if _is_transient_exec_error(prev_error):
                result.error = _friendly_backend_unavailable_message()
                logger.warning(
                    "KumoRFM backend error on a valid query; not regenerating. Error: %s",
                    prev_error[:200],
                )
                break

    return result
