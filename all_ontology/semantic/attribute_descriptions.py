# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Describe every ColumnAttribute once the rest of the semantic layer exists.

The table pass writes attributes, but what an attribute means depends on what
it is linked to: semantic FKs, term families and the table's own Term are only
known after every table was visited. This stage writes one sentence per
undescribed attribute from that evidence, and re-embeds the attributes it
changes so the vector text carries the new description.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from all_ontology.dal.attributes import (
    fetch_attributes_to_describe,
    fetch_semantic_fk_ends,
    store_attribute_descriptions,
)
from all_ontology.dal.term_families import fetch_table_families
from all_ontology.dal.terms import fetch_terms_and_attributes_for_table
from all_ontology.semantic.cancellation import is_cancelled
from all_ontology.semantic.date_format import is_date_type
from all_ontology.semantic.deterministic import describe_columns
from all_ontology.semantic.embed import SemanticEmbedder
from all_ontology.utils.sample_values import stringify_sample_values

logger = logging.getLogger(__name__)

_BATCH_SIZE = 15
_MAX_WORKERS = 4
_MAX_SAMPLES = 5
_MAX_SAMPLE_LEN = 30
_MAX_REFERRERS = 5

_SYSTEM = """\
You are writing the business glossary of a semantic layer. For every column \
you are given, write ONE sentence of at most 30 words saying what the \
attribute means in business terms.

Use all the evidence given: the Term and table the attribute belongs to, the \
column's own description, its data type, sample values and value format, \
the columns it references or that reference it, and the table family.

Rules:
- Write a new sentence; never copy the column, table or Term description.
- State a reference as a business relationship ("identifies the customer who \
placed the order"), not as a table and column name.
- When a value format is given, state it.
- Only what the evidence supports  no speculation.
- Return exactly one entry per column, using the physical column name."""


def describe_column_attributes(
    database_name: str,
    embedder: SemanticEmbedder | None = None,
) -> int:
    """Write a description onto every undescribed attribute of *database_name*."""
    rows = fetch_attributes_to_describe(database_name)
    if not rows:
        logger.info("describe_column_attributes: every attribute is described")
        return 0

    references: dict[str, list[str]] = defaultdict(list)
    referrers: dict[str, list[str]] = defaultdict(list)
    for end in fetch_semantic_fk_ends(database_name):
        references[end["source_column_id"]].append(
            f"{end['target_table_name']}.{end['target_column_name']}"
        )
        if end["target_attribute_id"]:
            referrers[end["target_attribute_id"]].append(
                f"{end['source_table_name']}.{end['source_column_name']}"
            )

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["table_id"], row["term_name"])].append(row)
    batches = [
        group[i : i + _BATCH_SIZE]
        for group in groups.values()
        for i in range(0, len(group), _BATCH_SIZE)
    ]

    written_by_table: dict[str, set[str]] = defaultdict(set)
    written_lock = threading.Lock()

    def describe(batch: list[dict[str, Any]]) -> int:
        if is_cancelled():
            return 0
        try:
            by_column = {row["column_name"]: row for row in batch}
            generated = describe_columns(
                _SYSTEM, _prompt(batch, references, referrers), list(by_column)
            )
            descriptions = {
                by_column[name]["attribute_id"]: text
                for name, text in generated.items()
            }
            written = store_attribute_descriptions(descriptions)
            if written:
                table_id = batch[0]["table_id"]
                with written_lock:
                    written_by_table[table_id].update(
                        attr_id for attr_id, text in descriptions.items() if text
                    )
            return written
        except Exception:
            logger.exception(
                "describe_column_attributes: failed for table %s",
                batch[0]["table_name"],
            )
            return 0

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(batches))) as pool:
        written = sum(pool.map(describe, batches))
    if is_cancelled():
        logger.info("describe_column_attributes: cancelled")
    elif embedder is not None and written:
        _reembed(embedder, dict(written_by_table), database_name)
    return written


def _reembed(
    embedder: SemanticEmbedder,
    by_table: dict[str, set[str]],
    database_name: str,
) -> None:
    """Re-embed the attributes whose description changed; best-effort."""
    prefixes: dict[str, str] = {}
    try:
        for row in fetch_table_families(database_name):
            prefixes.setdefault(row["table_id"], row["prefix"])
    except Exception:
        logger.debug("term families unavailable while re-embedding", exc_info=True)
    for table_id, attribute_ids in by_table.items():
        try:
            _, attrs = fetch_terms_and_attributes_for_table(table_id)
            changed = [attr for attr in attrs if attr.get("id") in attribute_ids]
            for attr in changed:
                attr["family_prefix"] = prefixes.get(table_id)
            if changed:
                embedder.embed_column_attributes(changed)
        except Exception:
            logger.warning(
                "could not re-embed described attributes of table %s",
                table_id,
                exc_info=True,
            )


def _prompt(
    batch: list[dict[str, Any]],
    references: dict[str, list[str]],
    referrers: dict[str, list[str]],
) -> str:
    first = batch[0]
    term_description = _text(first.get("term_description"))
    table_description = _text(first.get("table_description"))
    lines = [f"Term: {first['term_name']}" + _dash(term_description)]
    lines.append(
        f"Table: {first['table_name']}"
        + _dash(_distinct(table_description, term_description))
    )
    if first.get("family_prefix"):
        lines.append(
            f"Family: {first['family_prefix']} — the table is one copy of a set "
            "of tables repeated under several prefixes"
        )
    lines.append("Columns:")
    for row in batch:
        lines.append(
            _column_line(
                row,
                references.get(row["column_id"], []),
                referrers.get(row["attribute_id"], []),
                (term_description, table_description),
            )
        )
    return "\n".join(lines)


def _column_line(
    row: dict[str, Any],
    references: list[str],
    referrers: list[str],
    seen: tuple[str, str],
) -> str:
    name = row["column_name"]
    facts: list[str] = []
    description = _distinct(_text(row.get("column_description")), name, *seen)
    if description:
        facts.append(f"description: {description}")
    if not is_date_type(row.get("data_type")):
        samples = (
            stringify_sample_values(row.get("sample_values"), max_len=_MAX_SAMPLE_LEN)
            or []
        )[:_MAX_SAMPLES]
        if samples:
            facts.append(f"samples: {', '.join(samples)}")
    if row.get("format"):
        facts.append(f"format: {row['format']}")
    if references:
        facts.append(f"references: {', '.join(sorted(references))}")
    if referrers:
        shown = sorted(referrers)[:_MAX_REFERRERS]
        more = len(referrers) - len(shown)
        facts.append(
            f"referenced by: {', '.join(shown)}" + (f" and {more} more" if more else "")
        )
    line = f"  - {name} ({row.get('data_type') or 'unknown'})"
    return f"{line} — {'; '.join(facts)}" if facts else line


def _text(value: Any) -> str:
    return (value or "").strip()


def _distinct(text: str, *others: str) -> str:
    """*text*, or ``""`` when it only repeats one of *others* (case-insensitively)."""
    folded = text.casefold()
    return "" if any(folded == other.casefold() for other in others) else text


def _dash(text: str) -> str:
    return f" — {text}" if text else ""
