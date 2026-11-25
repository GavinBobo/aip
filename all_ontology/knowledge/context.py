# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Retrieve reviewed knowledge for a chat question.

This is the bridge that makes the knowledge ontology useful to the SQL agent:
the worker calls it with the user's question, and the returned Markdown is
appended to the system prompt. Retrieval is deliberately lexical and
conservative — only reviewed/certified definitions, only stored evidence, and
never a generated answer.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select

from all_ontology.dal import schema as s
from all_ontology.dal.session import store

_STATUSES = {"reviewed", "certified"}
_MAX_TOKENS = 14


def _tokens(question: str) -> list[str]:
    """The bounded set of tokens the knowledge search uses.

    English identifiers stay whole; Chinese sequences are expanded into
    2/3/4-character n-grams. Generation stops once ``_MAX_TOKENS`` unique
    tokens exist, instead of materialising every n-gram first and truncating
    afterwards.
    """
    seen: set[str] = set()
    result: list[str] = []

    def add(token: str) -> bool:
        key = token.casefold()
        if key in seen:
            return False
        seen.add(key)
        result.append(token)
        return len(result) >= _MAX_TOKENS

    for word in re.findall(r"[A-Za-z0-9_]{2,}", question):
        if add(word):
            return result
    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        if len(sequence) <= 4:
            if add(sequence):
                return result
            continue
        for size in (2, 3, 4):
            for index in range(0, len(sequence) - size + 1):
                if add(sequence[index : index + size]):
                    return result
    return result

def _like_clause(columns: list[Any], tokens: list[str]) -> Any:
    clauses = []
    for token in tokens:
        pattern = f"%{token}%"
        clauses.extend(column.ilike(pattern) for column in columns)
    return or_(*clauses)


def _evidence_map(fact_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not fact_ids:
        return {}
    rows = store().query_read(
        select(
            s.knowledge_evidence.c.fact_id,
            s.knowledge_evidence.c.page,
            s.knowledge_evidence.c.block_index,
            s.knowledge_evidence.c.quote,
            s.knowledge_evidence.c.source_path,
            s.knowledge_evidence.c.image_path,
        )
        .where(s.knowledge_evidence.c.fact_id.in_(fact_ids))
        .order_by(s.knowledge_evidence.c.page, s.knowledge_evidence.c.block_index)
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["fact_id"])].append(dict(row))
    return grouped


def retrieve_knowledge_context(
    question: str,
    *,
    limit: int = 8,
    network_id: str | None = None,
    zone_ids: list[str] | None = None,
    network_ids: list[str] | None = None,
) -> str:
    """Return a compact, cited context block, or an empty string."""
    tokens = _tokens(question)
    if not tokens:
        return ""
    concept_scope = (
        [s.knowledge_concept.c.network_id == network_id] if network_id else []
    )
    fact_scope = [s.knowledge_fact.c.network_id == network_id] if network_id else []
    action_scope = [s.knowledge_action.c.network_id == network_id] if network_id else []
    risk_scope = [s.knowledge_risk.c.network_id == network_id] if network_id else []
    metric_scope = [s.knowledge_metric.c.network_id == network_id] if network_id else []
    zone_scope = (
        [
            or_(
                s.knowledge_network.c.zone_id.is_(None),
                s.knowledge_network.c.zone_id.in_(zone_ids),
            )
        ]
        if zone_ids is not None
        else []
    )
    id_scope = (
        [s.knowledge_network.c.id.in_(network_ids)] if network_ids is not None else []
    )

    concepts = store().query_read(
        select(
            s.knowledge_concept.c.name,
            s.knowledge_concept.c.description,
            s.knowledge_concept.c.kind,
            s.knowledge_concept.c.status,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_concept.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_concept.c.network_id,
            )
        )
        .where(
            *concept_scope,
            *zone_scope,
            *id_scope,
            s.knowledge_concept.c.status.in_(_STATUSES),
            _like_clause(
                [
                    s.knowledge_concept.c.name,
                    s.knowledge_concept.c.description,
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_concept.c.name)
        .limit(limit)
    )
    facts = store().query_read(
        select(
            s.knowledge_fact.c.id,
            s.knowledge_fact.c.statement,
            s.knowledge_fact.c.status,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_fact.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_fact.c.network_id,
            )
        )
        .where(
            *fact_scope,
            *zone_scope,
            *id_scope,
            s.knowledge_fact.c.status.in_(_STATUSES),
            _like_clause([s.knowledge_fact.c.statement], tokens),
        )
        .order_by(s.knowledge_fact.c.created.desc())
        .limit(limit)
    )
    actions = store().query_read(
        select(
            s.knowledge_action.c.name,
            s.knowledge_action.c.description,
            s.knowledge_action.c.action_intent,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_action.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_action.c.network_id,
            )
        )
        .where(
            *action_scope,
            *zone_scope,
            *id_scope,
            s.knowledge_action.c.status.in_(_STATUSES),
            _like_clause(
                [
                    s.knowledge_action.c.name,
                    s.knowledge_action.c.description,
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_action.c.name)
        .limit(max(2, limit // 2))
    )
    risks = store().query_read(
        select(
            s.knowledge_risk.c.name,
            s.knowledge_risk.c.description,
            s.knowledge_risk.c.severity,
            s.knowledge_risk.c.mitigation,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_risk.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_risk.c.network_id,
            )
        )
        .where(
            *risk_scope,
            *zone_scope,
            *id_scope,
            s.knowledge_risk.c.status.in_(_STATUSES),
            _like_clause(
                [
                    s.knowledge_risk.c.name,
                    s.knowledge_risk.c.description,
                    s.knowledge_risk.c.mitigation,
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_risk.c.name)
        .limit(max(2, limit // 2))
    )
    metrics = store().query_read(
        select(
            s.knowledge_metric.c.name,
            s.knowledge_metric.c.description,
            s.knowledge_metric.c.expression,
            s.knowledge_metric.c.unit,
            s.knowledge_network.c.name.label("network_name"),
        )
        .select_from(
            s.knowledge_metric.join(
                s.knowledge_network,
                s.knowledge_network.c.id == s.knowledge_metric.c.network_id,
            )
        )
        .where(
            *metric_scope,
            *zone_scope,
            *id_scope,
            s.knowledge_metric.c.status.in_(_STATUSES),
            _like_clause(
                [
                    s.knowledge_metric.c.name,
                    s.knowledge_metric.c.description,
                    s.knowledge_metric.c.expression,
                ],
                tokens,
            ),
        )
        .order_by(s.knowledge_metric.c.name)
        .limit(max(2, limit // 2))
    )

    if not (concepts or facts or actions or risks or metrics):
        return ""

    evidence = _evidence_map([str(item["id"]) for item in facts])
    # The chat answer follows the question's language, so the context that is
    # prepended to the system prompt mirrors it instead of always speaking
    # Chinese. Facts themselves stay in the language they were extracted in.
    chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
    lines = ["## Knowledge ontology context"]
    lines.append(
        "仅在回答需要制度、流程、角色或文档定义时使用以下上下文；"
        "引用事实时保留页码与原文证据。不要把它当作数据库行。"
        if chinese
        else "Use this context only when the answer needs policies, processes, "
        "roles or document definitions. Keep page numbers and quoted evidence "
        "when citing a fact. Do not treat it as database rows."
    )
    if concepts:
        lines.append("### Concepts")
        for concept in concepts:
            description = str(concept.get("description") or "").strip()
            lines.append(
                f"- [{concept['network_name']}] {concept['name']} "
                f"({concept.get('kind') or 'entity'}, {concept.get('status')})"
                + (f": {description}" if description else "")
            )
    if facts:
        lines.append("### Facts")
        for fact in facts:
            lines.append(f"- [{fact['network_name']}] {fact['statement']}")
            for item in evidence.get(str(fact["id"]), [])[:2]:
                page = item.get("page")
                if chinese:
                    lines.append(
                        f"  - 证据 {f'第 {page} 页' if page is not None else '页码未知'}："
                        f"“{item.get('quote')}”"
                    )
                else:
                    lines.append(
                        f"  - Evidence, page {page if page is not None else 'unknown'}: "
                        f'"{item.get("quote")}"'
                    )
                if item.get("image_path"):
                    lines.append(f"  ![]({item['image_path']})")
                if item.get("source_path"):
                    lines.append(f"  - Source document: {item['source_path']}")
    if actions:
        lines.append("### Actions")
        for action in actions:
            description = str(action.get("description") or "").strip()
            lines.append(
                f"- [{action['network_name']}] {action['name']} "
                f"({action.get('action_intent') or 'execute'})"
                + (f": {description}" if description else "")
            )
    if risks:
        lines.append("### Risks")
        for risk in risks:
            mitigation = str(risk.get("mitigation") or "").strip()
            lines.append(
                f"- [{risk['network_name']}] {risk['name']} "
                f"(severity={risk.get('severity') or 'medium'})"
                + (f"; mitigation: {mitigation}" if mitigation else "")
            )
    if metrics:
        lines.append("### Metrics")
        for metric in metrics:
            expression = str(metric.get("expression") or "").strip()
            unit = str(metric.get("unit") or "").strip()
            lines.append(
                f"- [{metric['network_name']}] {metric['name']}"
                + (f" = {expression}" if expression else "")
                + (f" ({unit})" if unit else "")
                + (
                    f": {metric.get('description')}"
                    if metric.get("description")
                    else ""
                )
            )
    return "\n".join(lines) + "\n"
