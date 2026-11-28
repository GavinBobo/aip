# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document-knowledge retrieval across chunks, concepts, facts and evidence.

This is deliberately separate from :mod:`all_ontology.knowledge.context`.
That module builds a compact prompt block for one chat turn. This module is the
general retrieval surface: it returns document passages, graph objects and
citations that a person, an agent, or a future search page can consume.

The first version is lexical. It uses the same pg_trgm-backed substring search
as the catalog, then ranks by phrase/token coverage and status. Chunk rows are
the primary passage index; evidence rows remain a fallback for documents
extracted before chunks were stored.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import aliased

from all_ontology.dal import schema as s
from all_ontology.dal.session import store

SearchMode = Literal["human", "agent"]

_AGENT_STATUSES = {"reviewed", "certified"}
_MAX_TOKENS = 16
_CANDIDATE_MULTIPLIER = 6


def _tokens(query: str) -> list[str]:
    """Bounded English words plus 2/3/4-character Chinese n-grams."""
    seen: set[str] = set()
    result: list[str] = []

    def add(token: str) -> bool:
        key = token.casefold()
        if key in seen:
            return False
        seen.add(key)
        result.append(token)
        return len(result) >= _MAX_TOKENS

    for word in re.findall(r"[A-Za-z0-9_]{2,}", query):
        if add(word):
            return result
    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        if len(sequence) <= 4:
            if add(sequence):
                return result
            continue
        for size in (2, 3, 4):
            for index in range(0, len(sequence) - size + 1):
                if add(sequence[index : index + size]):
                    return result
    return result


def _like_any(columns: list[Any], tokens: list[str]) -> Any:
    return or_(*[column.ilike(f"%{token}%") for token in tokens for column in columns])


def _scope(network_ids: list[str] | None, zone_ids: list[str] | None) -> list[Any]:
    clauses: list[Any] = []
    if network_ids is not None:
        clauses.append(s.knowledge_network.c.id.in_(network_ids))
    if zone_ids is not None:
        clauses.append(
            or_(
                s.knowledge_network.c.zone_id.is_(None),
                s.knowledge_network.c.zone_id.in_(zone_ids),
            )
        )
    return clauses


def _document_scope(document_id: str | None) -> list[Any]:
    return [s.knowledge_document.c.id == document_id] if document_id else []


def _reviewed_document_ids() -> set[str]:
    """Documents with at least one reviewed/certified graph item."""
    ids: set[str] = set()
    for table in (
        s.knowledge_concept,
        s.knowledge_relation,
        s.knowledge_fact,
        s.knowledge_action,
        s.knowledge_risk,
        s.knowledge_metric,
    ):
        rows = store().query_read(
            select(table.c.source_document_id)
            .where(
                table.c.status.in_(_AGENT_STATUSES),
                table.c.source_document_id.isnot(None),
            )
            .distinct()
        )
        ids.update(str(row["source_document_id"]) for row in rows)
    return ids


def _score(
    texts: list[Any],
    *,
    query: str,
    tokens: list[str],
    weight: float,
    status: str | None = None,
) -> tuple[float, list[str]]:
    haystack = " \n ".join(
        str(text).casefold() for text in texts if text is not None and str(text).strip()
    )
    if not haystack:
        return 0.0, []
    matched = [token for token in tokens if token.casefold() in haystack]
    coverage = len(matched) / len(tokens) if tokens else 0.0
    score = weight * (0.35 + 0.65 * coverage)
    if query and query.casefold() in haystack:
        score += 2.0
    if status == "certified":
        score += 0.15
    elif status == "reviewed":
        score += 0.07
    return round(score, 4), matched


def _snippet(text: str | None, query: str, tokens: list[str], *, limit: int = 420) -> str:
    value = str(text or "")
    if not value:
        return ""
    folded = value.casefold()
    position = folded.find(query.casefold()) if query else -1
    if position < 0:
        for token in tokens:
            position = folded.find(token.casefold())
            if position >= 0:
                break
    if position < 0:
        position = 0
    start = max(0, position - 140)
    end = min(len(value), position + limit)
    snippet = value[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(value):
        snippet = snippet + "…"
    return snippet


def _item(
    *,
    kind: str,
    id_value: str,
    score: float,
    title: str | None,
    snippet: str | None,
    network_id: str | None,
    network_name: str | None,
    document_id: str | None = None,
    document_title: str | None = None,
    source_name: str | None = None,
    source_path: str | None = None,
    status: str | None = None,
    page: int | None = None,
    page_end: int | None = None,
    block_index: int | None = None,
    citation: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": id_value,
        "score": score,
        "title": title,
        "snippet": snippet,
        "network_id": network_id,
        "network_name": network_name,
        "document_id": document_id,
        "document_title": document_title,
        "source_name": source_name,
        "source_path": source_path,
        "status": status,
        "page": page,
        "page_end": page_end,
        "block_index": block_index,
        "citation": citation or {},
        "metadata": metadata or {},
        "evidence": [],
    }


def _chunk_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    reviewed_documents: set[str] | None,
) -> list[dict[str, Any]]:
    statement = (
        select(
            s.knowledge_chunk.c.id,
            s.knowledge_chunk.c.document_id,
            s.knowledge_chunk.c.network_id,
            s.knowledge_chunk.c.text,
            s.knowledge_chunk.c.chunk_index,
            s.knowledge_chunk.c.page_start,
            s.knowledge_chunk.c.page_end,
            s.knowledge_chunk.c.block_start,
            s.knowledge_chunk.c.block_end,
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_document.c.source_name,
            s.knowledge_document.c.source_path,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_chunk.join(
                s.knowledge_document,
                s.knowledge_document.c.id == s.knowledge_chunk.c.document_id,
            ).join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_chunk.c.network_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_chunk.c.document_id == document_id]
                if document_id
                else []
            ),
            _like_any([s.knowledge_chunk.c.text], tokens),
        )
        .order_by(s.knowledge_chunk.c.document_id, s.knowledge_chunk.c.chunk_index)
        .limit(limit)
    )
    if reviewed_documents is not None:
        if not reviewed_documents:
            return []
        statement = statement.where(
            s.knowledge_chunk.c.document_id.in_(reviewed_documents)
        )
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["document_title"], row["text"]],
            query=query,
            tokens=tokens,
            weight=1.0,
        )
        results.append(
            _item(
                kind="chunk",
                id_value=str(row["id"]),
                score=score,
                title=row["document_title"],
                snippet=_snippet(row["text"], query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["document_id"]),
                document_title=row["document_title"],
                source_name=row["source_name"],
                source_path=row["source_path"],
                page=row["page_start"],
                page_end=row["page_end"],
                block_index=row["block_start"],
                citation={
                    "page": row["page_start"],
                    "page_end": row["page_end"],
                    "block_start": row["block_start"],
                    "block_end": row["block_end"],
                    "source_path": row["source_path"],
                },
                metadata={
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _document_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    reviewed_documents: set[str] | None,
) -> list[dict[str, Any]]:
    statement = (
        select(
            s.knowledge_document.c.id,
            s.knowledge_document.c.network_id,
            s.knowledge_document.c.title,
            s.knowledge_document.c.summary,
            s.knowledge_document.c.source_name,
            s.knowledge_document.c.source_path,
            s.knowledge_document.c.status,
            s.knowledge_document.c.created,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_document.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_document.c.network_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_document.c.id == document_id]
                if document_id
                else []
            ),
            s.knowledge_document.c.status == "extracted",
            _like_any(
                [s.knowledge_document.c.title, s.knowledge_document.c.summary],
                tokens,
            ),
        )
        .order_by(s.knowledge_document.c.created.desc())
        .limit(limit)
    )
    if reviewed_documents is not None:
        if not reviewed_documents:
            return []
        statement = statement.where(
            s.knowledge_document.c.id.in_(reviewed_documents)
        )
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["title"], row["summary"]],
            query=query,
            tokens=tokens,
            weight=1.05,
        )
        results.append(
            _item(
                kind="document",
                id_value=str(row["id"]),
                score=score,
                title=row["title"],
                snippet=_snippet(row["summary"], query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["id"]),
                document_title=row["title"],
                source_name=row["source_name"],
                source_path=row["source_path"],
                status=row["status"],
                metadata={"matched_tokens": matched},
            )
        )
    return results


def _evidence_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    reviewed_documents: set[str] | None,
) -> list[dict[str, Any]]:
    statement = (
        select(
            s.knowledge_evidence.c.id,
            s.knowledge_evidence.c.document_id,
            s.knowledge_evidence.c.network_id,
            s.knowledge_evidence.c.quote,
            s.knowledge_evidence.c.page,
            s.knowledge_evidence.c.block_index,
            s.knowledge_evidence.c.source_path,
            s.knowledge_evidence.c.image_path,
            s.knowledge_evidence.c.concept_id,
            s.knowledge_evidence.c.relation_id,
            s.knowledge_evidence.c.fact_id,
            s.knowledge_evidence.c.action_id,
            s.knowledge_evidence.c.risk_id,
            s.knowledge_evidence.c.metric_id,
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_evidence.join(
                s.knowledge_document,
                s.knowledge_document.c.id == s.knowledge_evidence.c.document_id,
            ).join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_evidence.c.network_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_evidence.c.document_id == document_id]
                if document_id
                else []
            ),
            _like_any([s.knowledge_evidence.c.quote], tokens),
        )
        .order_by(
            s.knowledge_evidence.c.document_id,
            s.knowledge_evidence.c.page,
            s.knowledge_evidence.c.block_index,
        )
        .limit(limit)
    )
    if reviewed_documents is not None:
        if not reviewed_documents:
            return []
        statement = statement.where(
            s.knowledge_evidence.c.document_id.in_(reviewed_documents)
        )
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["quote"]],
            query=query,
            tokens=tokens,
            weight=0.9,
        )
        target = next(
            (
                (kind, str(row[f"{kind}_id"]))
                for kind in ("concept", "relation", "fact", "action", "risk", "metric")
                if row.get(f"{kind}_id")
            ),
            (None, None),
        )
        results.append(
            _item(
                kind="evidence",
                id_value=str(row["id"]),
                score=score,
                title=row["document_title"],
                snippet=_snippet(row["quote"], query, tokens, limit=600),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["document_id"]),
                document_title=row["document_title"],
                source_path=row["source_path"],
                page=row["page"],
                block_index=row["block_index"],
                citation={
                    "page": row["page"],
                    "block_index": row["block_index"],
                    "quote": row["quote"],
                    "source_path": row["source_path"],
                    "image_path": row["image_path"],
                },
                metadata={
                    "target_kind": target[0],
                    "target_id": target[1],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _concept_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    statuses: set[str] | None,
) -> list[dict[str, Any]]:
    statement = (
        select(
            s.knowledge_concept.c.id,
            s.knowledge_concept.c.network_id,
            s.knowledge_concept.c.name,
            s.knowledge_concept.c.description,
            s.knowledge_concept.c.kind,
            s.knowledge_concept.c.aliases,
            s.knowledge_concept.c.status,
            s.knowledge_concept.c.confidence,
            s.knowledge_concept.c.source_document_id,
            s.knowledge_network.c.name.label("network_name"),
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_document.c.source_path,
        )
        .select_from(
            s.knowledge_concept.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_concept.c.network_id,
            ).outerjoin(
                s.knowledge_document,
                s.knowledge_document.c.id == s.knowledge_concept.c.source_document_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_concept.c.source_document_id == document_id]
                if document_id
                else []
            ),
            _like_any(
                [
                    s.knowledge_concept.c.name,
                    s.knowledge_concept.c.description,
                    cast(s.knowledge_concept.c.aliases, Text),
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_concept.c.name)
        .limit(limit)
    )
    if statuses is not None:
        statement = statement.where(s.knowledge_concept.c.status.in_(statuses))
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["name"], row["description"], row["aliases"]],
            query=query,
            tokens=tokens,
            weight=1.15,
            status=row["status"],
        )
        results.append(
            _item(
                kind="concept",
                id_value=str(row["id"]),
                score=score,
                title=row["name"],
                snippet=_snippet(row["description"], query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["source_document_id"])
                if row["source_document_id"]
                else None,
                document_title=row["document_title"],
                source_path=row["source_path"],
                status=row["status"],
                metadata={
                    "concept_kind": row["kind"],
                    "confidence": row["confidence"],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _relation_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    statuses: set[str] | None,
) -> list[dict[str, Any]]:
    source = aliased(s.knowledge_concept)
    target = aliased(s.knowledge_concept)
    statement = (
        select(
            s.knowledge_relation.c.id,
            s.knowledge_relation.c.network_id,
            s.knowledge_relation.c.name,
            s.knowledge_relation.c.description,
            s.knowledge_relation.c.kind,
            s.knowledge_relation.c.status,
            s.knowledge_relation.c.confidence,
            s.knowledge_relation.c.source_document_id,
            source.c.name.label("source_name"),
            target.c.name.label("target_name"),
            s.knowledge_network.c.name.label("network_name"),
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_document.c.source_path,
        )
        .select_from(
            s.knowledge_relation.join(
                source, source.c.id == s.knowledge_relation.c.source_concept_id
            )
            .join(target, target.c.id == s.knowledge_relation.c.target_concept_id)
            .join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_relation.c.network_id,
            )
            .outerjoin(
                s.knowledge_document,
                s.knowledge_document.c.id == s.knowledge_relation.c.source_document_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_relation.c.source_document_id == document_id]
                if document_id
                else []
            ),
            _like_any(
                [
                    s.knowledge_relation.c.name,
                    s.knowledge_relation.c.description,
                    source.c.name,
                    target.c.name,
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_relation.c.name)
        .limit(limit)
    )
    if statuses is not None:
        statement = statement.where(s.knowledge_relation.c.status.in_(statuses))
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["name"], row["description"], row["source_name"], row["target_name"]],
            query=query,
            tokens=tokens,
            weight=1.05,
            status=row["status"],
        )
        results.append(
            _item(
                kind="relation",
                id_value=str(row["id"]),
                score=score,
                title=f"{row['source_name']} → {row['target_name']}",
                snippet=_snippet(row["description"], query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["source_document_id"])
                if row["source_document_id"]
                else None,
                document_title=row["document_title"],
                source_path=row["source_path"],
                status=row["status"],
                metadata={
                    "relation": row["name"],
                    "relation_kind": row["kind"],
                    "confidence": row["confidence"],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _fact_results(
    *,
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    statuses: set[str] | None,
) -> list[dict[str, Any]]:
    subject = aliased(s.knowledge_concept)
    object_concept = aliased(s.knowledge_concept)
    statement = (
        select(
            s.knowledge_fact.c.id,
            s.knowledge_fact.c.network_id,
            s.knowledge_fact.c.statement,
            s.knowledge_fact.c.predicate,
            s.knowledge_fact.c.status,
            s.knowledge_fact.c.confidence,
            s.knowledge_fact.c.source_document_id,
            subject.c.name.label("subject_name"),
            object_concept.c.name.label("object_name"),
            s.knowledge_network.c.name.label("network_name"),
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_document.c.source_path,
        )
        .select_from(
            s.knowledge_fact.join(
                subject, subject.c.id == s.knowledge_fact.c.subject_concept_id
            )
            .outerjoin(
                object_concept,
                object_concept.c.id == s.knowledge_fact.c.object_concept_id,
            )
            .join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_fact.c.network_id,
            )
            .outerjoin(
                s.knowledge_document,
                s.knowledge_document.c.id == s.knowledge_fact.c.source_document_id,
            )
        )
        .where(
            *scope,
            *(
                [s.knowledge_fact.c.source_document_id == document_id]
                if document_id
                else []
            ),
            _like_any(
                [s.knowledge_fact.c.statement, s.knowledge_fact.c.predicate],
                tokens,
            ),
        )
        .order_by(s.knowledge_fact.c.created.desc())
        .limit(limit)
    )
    if statuses is not None:
        statement = statement.where(s.knowledge_fact.c.status.in_(statuses))
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["statement"], row["predicate"], row["subject_name"], row["object_name"]],
            query=query,
            tokens=tokens,
            weight=1.2,
            status=row["status"],
        )
        results.append(
            _item(
                kind="fact",
                id_value=str(row["id"]),
                score=score,
                title=row["subject_name"],
                snippet=_snippet(row["statement"], query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["source_document_id"])
                if row["source_document_id"]
                else None,
                document_title=row["document_title"],
                source_path=row["source_path"],
                status=row["status"],
                metadata={
                    "predicate": row["predicate"],
                    "object_name": row["object_name"],
                    "confidence": row["confidence"],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _simple_graph_results(
    *,
    kind: str,
    table: Any,
    name_column: Any,
    description_column: Any,
    extra_columns: list[Any],
    query: str,
    tokens: list[str],
    limit: int,
    scope: list[Any],
    document_id: str | None,
    statuses: set[str] | None,
    weight: float,
) -> list[dict[str, Any]]:
    statement = (
        select(
            table.c.id,
            table.c.network_id,
            name_column.label("name"),
            description_column.label("description"),
            table.c.status,
            table.c.confidence,
            table.c.source_document_id,
            *extra_columns,
            s.knowledge_network.c.name.label("network_name"),
            s.knowledge_document.c.title.label("document_title"),
            s.knowledge_document.c.source_path,
        )
        .select_from(
            table.join(
                s.knowledge_network,
                s.knowledge_network.c.id == table.c.network_id,
            ).outerjoin(
                s.knowledge_document,
                s.knowledge_document.c.id == table.c.source_document_id,
            )
        )
        .where(
            *scope,
            *([table.c.source_document_id == document_id] if document_id else []),
            _like_any([name_column, description_column, *extra_columns], tokens),
        )
        .order_by(name_column)
        .limit(limit)
    )
    if statuses is not None:
        statement = statement.where(table.c.status.in_(statuses))
    results: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        score, matched = _score(
            [row["name"], row["description"], *[row.get(column.name) for column in extra_columns]],
            query=query,
            tokens=tokens,
            weight=weight,
            status=row["status"],
        )
        snippet_source = row["description"]
        if not snippet_source:
            snippet_source = next(
                (
                    row.get(column.name)
                    for column in extra_columns
                    if row.get(column.name)
                ),
                None,
            )
        results.append(
            _item(
                kind=kind,
                id_value=str(row["id"]),
                score=score,
                title=row["name"],
                snippet=_snippet(snippet_source, query, tokens),
                network_id=str(row["network_id"]),
                network_name=row["network_name"],
                document_id=str(row["source_document_id"])
                if row["source_document_id"]
                else None,
                document_title=row["document_title"],
                source_path=row["source_path"],
                status=row["status"],
                metadata={
                    **{
                        column.name: row.get(column.name)
                        for column in extra_columns
                    },
                    "confidence": row["confidence"],
                    "matched_tokens": matched,
                },
            )
        )
    return results


def _attach_evidence(results: list[dict[str, Any]]) -> None:
    ids_by_kind: dict[str, list[str]] = defaultdict(list)
    column_by_kind = {
        "concept": s.knowledge_evidence.c.concept_id,
        "relation": s.knowledge_evidence.c.relation_id,
        "fact": s.knowledge_evidence.c.fact_id,
        "action": s.knowledge_evidence.c.action_id,
        "risk": s.knowledge_evidence.c.risk_id,
        "metric": s.knowledge_evidence.c.metric_id,
        "rule": s.knowledge_evidence.c.rule_id,
    }
    for result in results:
        if result["kind"] in column_by_kind:
            ids_by_kind[result["kind"]].append(result["id"])
    clauses = [
        column.in_(ids_by_kind[kind])
        for kind, column in column_by_kind.items()
        if ids_by_kind[kind]
    ]
    if not clauses:
        return
    rows = store().query_read(
        select(
            s.knowledge_evidence.c.id,
            s.knowledge_evidence.c.concept_id,
            s.knowledge_evidence.c.relation_id,
            s.knowledge_evidence.c.fact_id,
            s.knowledge_evidence.c.action_id,
            s.knowledge_evidence.c.risk_id,
            s.knowledge_evidence.c.metric_id,
            s.knowledge_evidence.c.page,
            s.knowledge_evidence.c.block_index,
            s.knowledge_evidence.c.quote,
            s.knowledge_evidence.c.source_path,
            s.knowledge_evidence.c.image_path,
        ).where(or_(*clauses))
    )
    by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for kind in column_by_kind:
            target_id = row.get(f"{kind}_id")
            if target_id:
                by_target[(kind, str(target_id))].append(dict(row))
    for result in results:
        result["evidence"] = by_target.get((result["kind"], result["id"]), [])


def _context(results: list[dict[str, Any]], query: str) -> str:
    if not results:
        return ""
    chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
    lines = ["## Knowledge retrieval context"]
    lines.append(
        "Use this context only when the answer needs a policy, process, role or "
        "document definition. Keep page numbers and quoted evidence when citing. "
        "Do not treat document facts as database rows."
        if not chinese
        else "仅在回答需要制度、流程、角色或文档定义时使用以下上下文；引用时保留页码与原文证据，不要把文档事实当成数据库行。"
    )
    for result in results:
        kind = result["kind"]
        document = result.get("document_title") or result.get("network_name") or "Document"
        if kind in {"chunk", "evidence"}:
            page = result.get("page")
            lines.append(
                f"- [{document}{f', p.{page}' if page is not None else ''}] "
                f"{result.get('snippet') or ''}"
            )
        elif kind == "fact":
            lines.append(f"- {result.get('snippet') or ''}")
        elif kind == "concept":
            lines.append(
                f"- [{result.get('status') or 'draft'}] {result.get('title')}: "
                f"{result.get('snippet') or ''}"
            )
        elif kind == "relation":
            lines.append(
                f"- {result.get('title')}: {result.get('snippet') or ''}"
            )
        else:
            lines.append(
                f"- [{kind}] {result.get('title')}: {result.get('snippet') or ''}"
            )
        for evidence in result.get("evidence") or []:
            page = evidence.get("page")
            quote = evidence.get("quote")
            if quote:
                lines.append(
                    f"  - Evidence{f', p.{page}' if page is not None else ''}: "
                    f"“{quote}”"
                )
    return "\n".join(lines) + "\n"


def search_knowledge(
    query: str,
    *,
    network_ids: list[str] | None,
    zone_ids: list[str] | None,
    mode: SearchMode = "human",
    kinds: list[str] | None = None,
    limit: int = 20,
    document_id: str | None = None,
    include_evidence: bool = True,
) -> dict[str, Any]:
    """Return ranked document passages and knowledge objects with citations."""
    cleaned = " ".join(str(query or "").split())
    tokens = _tokens(cleaned)
    if not cleaned or not tokens:
        return {
            "query": cleaned,
            "mode": mode,
            "total": 0,
            "returned": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": [],
            "facets": {"kinds": {}, "networks": [], "documents": []},
            "context": "",
        }

    allowed_kinds = {
        "chunk",
        "document",
        "concept",
        "relation",
        "fact",
        "action",
        "risk",
        "metric",
        "rule",
        "evidence",
    }
    selected = set(kinds or allowed_kinds) & allowed_kinds
    statuses = _AGENT_STATUSES if mode == "agent" else None
    reviewed_documents = _reviewed_document_ids() if mode == "agent" else None
    scope = _scope(network_ids, zone_ids)
    candidate_limit = max(30, limit * _CANDIDATE_MULTIPLIER)
    results: list[dict[str, Any]] = []

    if "chunk" in selected:
        results.extend(
            _chunk_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                reviewed_documents=reviewed_documents,
            )
        )
    if "document" in selected:
        results.extend(
            _document_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                reviewed_documents=reviewed_documents,
            )
        )
    if "concept" in selected:
        results.extend(
            _concept_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                statuses=statuses,
            )
        )
    if "relation" in selected:
        results.extend(
            _relation_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                statuses=statuses,
            )
        )
    if "fact" in selected:
        results.extend(
            _fact_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                statuses=statuses,
            )
        )
    for kind, table, weight in (
        ("action", s.knowledge_action, 0.95),
        ("risk", s.knowledge_risk, 0.95),
        ("metric", s.knowledge_metric, 0.95),
        ("rule", s.knowledge_rule, 1.2),
    ):
        if kind not in selected:
            continue
        if kind == "action":
            extra = [s.knowledge_action.c.action_intent]
        elif kind == "risk":
            extra = [s.knowledge_risk.c.severity, s.knowledge_risk.c.mitigation]
        elif kind == "metric":
            extra = [s.knowledge_metric.c.expression, s.knowledge_metric.c.unit]
        else:
            extra = [s.knowledge_rule.c.scope, s.knowledge_rule.c.condition]
        description_column = (
            s.knowledge_rule.c.statement
            if kind == "rule"
            else table.c.description
        )
        results.extend(
            _simple_graph_results(
                kind=kind,
                table=table,
                name_column=table.c.name,
                description_column=description_column,
                extra_columns=extra,
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                statuses=statuses,
                weight=weight,
            )
        )
    if include_evidence and "evidence" in selected:
        results.extend(
            _evidence_results(
                query=cleaned,
                tokens=tokens,
                limit=candidate_limit,
                scope=scope,
                document_id=document_id,
                reviewed_documents=reviewed_documents,
            )
        )

    # A chunk already carries the prose an evidence row quotes. Keep the precise
    # evidence fallback for old documents, but not as a duplicate of a chunk.
    chunk_texts: dict[str, list[str]] = defaultdict(list)
    for result in results:
        if result["kind"] == "chunk" and result.get("document_id"):
            chunk_texts[result["document_id"]].append(
                str(result.get("metadata", {}).get("text") or "")
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in sorted(
        results, key=lambda item: (-float(item["score"]), item["kind"], item["id"])
    ):
        key = (result["kind"], result["id"])
        if key in seen:
            continue
        if result["kind"] == "evidence":
            quote = str((result.get("citation") or {}).get("quote") or "")
            if quote and any(
                quote[:80].casefold() in text.casefold()
                for text in chunk_texts.get(result.get("document_id") or "", [])
            ):
                continue
        seen.add(key)
        deduped.append(result)

    _attach_evidence(deduped)
    total = len(deduped)
    limited = deduped[:limit]
    kind_counts = Counter(result["kind"] for result in deduped)
    network_counts: Counter[tuple[str | None, str | None]] = Counter(
        (result.get("network_id"), result.get("network_name")) for result in deduped
    )
    document_counts: Counter[tuple[str | None, str | None]] = Counter(
        (result.get("document_id"), result.get("document_title")) for result in deduped
    )
    return {
        "query": cleaned,
        "mode": mode,
        "total": total,
        "returned": len(limited),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": limited,
        "facets": {
            "kinds": dict(kind_counts),
            "networks": [
                {"id": network_id, "name": name or "", "count": count}
                for (network_id, name), count in network_counts.most_common(20)
            ],
            "documents": [
                {"id": document_id, "name": name or "", "count": count}
                for (document_id, name), count in document_counts.most_common(20)
            ],
        },
        "context": _context(limited, cleaned),
    }


def retrieve_agent_context(
    question: str,
    *,
    network_ids: list[str] | None = None,
    zone_ids: list[str] | None = None,
    limit: int = 10,
) -> str:
    """The compact, reviewed-only context block used by the SQL agent.

    Kept as a named entry point so the chat worker does not have to know the
    retrieval result shape. It intentionally uses the same conservative
    ``agent`` profile as the HTTP search service.
    """
    result = search_knowledge(
        question,
        network_ids=network_ids,
        zone_ids=zone_ids,
        mode="agent",
        limit=limit,
    )
    return str(result.get("context") or "")
