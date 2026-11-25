# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document -> knowledge graph extraction.

The model is asked for a small, grounded graph per chunk, never for a whole
document at once. That is what keeps a 200-page manual inside a context window
and — more importantly — what makes every claim carry a page and a quoted
passage instead of a plausible-sounding paraphrase.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from all_ontology.dal import knowledge as knowledge_dal
from all_ontology.knowledge.source import (
    SourceChunk,
    blocks_for_run,
    chunk_blocks,
)

logger = logging.getLogger(__name__)

MAX_CHUNKS = 12
CHUNK_CHARS = 6000

CONCEPT_KINDS = {
    "entity",
    "event",
    "process",
    "rule",
    "metric",
    "role",
    "document",
}
RELATION_KINDS = {
    "association",
    "part_of",
    "causal",
    "depends_on",
    "controls",
    "flows_to",
    "related",
}


class ExtractedAttribute(BaseModel):
    name: str = Field(description="属性名，短名称，例如 金额、生效日期")
    value: str | None = Field(default=None, description="原文中该属性的值")
    description: str | None = Field(default=None, description="属性的说明")
    type: str | None = Field(
        default="string", description="string/number/date/boolean/text"
    )


class ExtractedConcept(BaseModel):
    name: str = Field(description="概念的标准名称，使用原文用词")
    kind: str = Field(
        default="entity",
        description="entity/event/process/rule/metric/role/document 之一",
    )
    description: str = Field(default="", description="基于原文的简要定义，不要编造")
    aliases: list[str] = Field(default_factory=list, description="原文出现过的其他叫法")
    attributes: list[ExtractedAttribute] = Field(default_factory=list)
    evidence_quote: str | None = Field(
        default=None, description="原文中支持该概念的逐字片段"
    )
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedRelation(BaseModel):
    source: str = Field(description="起点概念名称，必须与 concepts 中的 name 一致")
    target: str = Field(description="终点概念名称，必须与 concepts 中的 name 一致")
    name: str = Field(description="关系名，例如 包含、审批、依赖")
    kind: str = Field(
        default="association",
        description="association/part_of/causal/depends_on/controls/flows_to/related 之一",
    )
    description: str = Field(default="")
    evidence_quote: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedFact(BaseModel):
    subject: str = Field(description="陈述的主语概念名称")
    predicate: str = Field(description="谓语/属性，例如 金额为、负责人是、适用于")
    object: str = Field(description="宾语；可以是概念名称，也可以是原文中的值")
    statement: str = Field(description="一句完整、可独立阅读的陈述")
    evidence_quote: str = Field(description="原文中逐字支持该陈述的片段")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedAction(BaseModel):
    name: str = Field(description="行动名称，例如 提交采购申请、审批采购订单")
    description: str = Field(default="", description="这个行动做什么，依据原文")
    action_intent: str = Field(
        default="execute",
        description="add/modify/delete/execute 之一；无法判断时用 execute",
    )
    bound_concept: str | None = Field(
        default=None, description="行动作用的概念名称；独立工具调用可为空"
    )
    parameters: list[dict] = Field(
        default_factory=list, description="参数名、类型、说明等"
    )
    evidence_quote: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedRisk(BaseModel):
    name: str = Field(description="风险名称，例如 越权审批风险")
    description: str = Field(default="", description="风险是什么，依据原文")
    severity: str = Field(default="medium", description="low/medium/high/critical 之一")
    mitigation: str | None = Field(default=None, description="原文给出的缓解措施")
    related_concept: str | None = Field(default=None, description="风险关联的概念名称")
    evidence_quote: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedMetric(BaseModel):
    name: str = Field(description="指标名称，例如 月采购额、审批通过率")
    description: str = Field(default="", description="指标口径说明")
    expression: str | None = Field(
        default=None, description="原文给出的计算公式或 SQL 表达式；没有则为空"
    )
    unit: str | None = Field(default=None, description="单位，例如 元、百分比、天")
    related_concept: str | None = Field(default=None, description="指标所属概念")
    evidence_quote: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractedChunk(BaseModel):
    summary: str = Field(default="", description="本片段的一句话摘要")
    concepts: list[ExtractedConcept] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    actions: list[ExtractedAction] = Field(default_factory=list)
    risks: list[ExtractedRisk] = Field(default_factory=list)
    metrics: list[ExtractedMetric] = Field(default_factory=list)


@dataclass
class NormalizedExtraction:
    summary: str = ""
    concepts: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)


SYSTEM_PROMPT = """\
你是一名业务知识工程师。你只从给定的文档片段中抽取知识，绝不补充片段之外的事实。

请抽取：
1. concepts：业务对象、事件、流程、规则、指标、角色等概念。合并同义叫法，名称使用原文用词。
2. relations：概念之间有明确文字依据的有向关系。source/target 必须是 concepts 中的 name。
3. facts：原文明确陈述的事实。每条 fact 必须附 evidence_quote，且 evidence_quote 必须是原文中连续出现的一段文字。
4. actions：原文描述的可执行操作，写明作用对象（bound_concept）和参数；没有明确操作时返回空数组。
5. risks：原文描述的风险、控制点或失败后果，尽量给出 severity 与 mitigation。
6. metrics：原文定义的业务指标，写清名称、口径、单位与公式；公式可以是自然语言或 SQL。

要求：
- 不要输出 Markdown，不要解释过程。
- 不要编造概念、关系或值。片段没有的内容就不要抽取。
- 一个片段最多 12 个概念、10 条关系、15 条事实、8 个行动、8 个风险、8 个指标。
- 描述和事实使用原文语言；专有名词保留原文。
- 如果片段只是目录、页眉页脚、无意义编号，返回空数组。
"""


def _slug(value: str, *, prefix: str) -> str:
    text = str(value or "").strip().lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if ascii_text and len(ascii_text) >= 2:
        return f"{prefix}_{ascii_text}"[:96]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def concept_key(name: str) -> str:
    return _slug(name, prefix="c")


def relation_key(source_key: str, target_key: str, name: str) -> str:
    digest = hashlib.sha1(
        f"{source_key}|{target_key}|{name.strip().casefold()}".encode("utf-8")
    ).hexdigest()[:10]
    ascii_name = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if ascii_name:
        return f"r_{ascii_name[:48]}_{digest}"[:96]
    return f"r_{digest}"


def definition_key(value: str, *, prefix: str) -> str:
    """A stable BKN-compatible id for a user-named definition."""
    return _slug(value, prefix=prefix)


def _norm(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _clamp(value: float | None) -> float:
    try:
        number = float(value if value is not None else 0.7)
    except (TypeError, ValueError):
        return 0.7
    return max(0.0, min(1.0, number))


def _quote_around(text: str, needle: str, *, radius: int = 80) -> str | None:
    position = text.find(needle)
    if position < 0:
        return None
    start = max(0, position - radius)
    end = min(len(text), position + len(needle) + radius)
    return text[start:end].replace("\n", " ").strip()


def _evidence(chunk: SourceChunk, quote: str | None) -> dict[str, Any] | None:
    text = str(quote or "").strip()
    if not text:
        return None
    # A quote the model invented is worse than no quote: it looks like
    # provenance while pointing at nothing. Require the opening of the quote to
    # occur in the chunk, which tolerates a trailing punctuation change but
    # rejects a fabricated sentence.
    probe = text if len(text) <= 40 else text[:40]
    if probe not in chunk.text:
        return None
    page, block_index = chunk.locate(text)
    return {"page": page, "block_index": block_index, "quote": text[:2000]}


def _concept_evidence(
    chunk: SourceChunk, concept: ExtractedConcept
) -> list[dict[str, Any]]:
    item = _evidence(chunk, concept.evidence_quote)
    if item is None:
        for needle in [concept.name, *concept.aliases]:
            quote = _quote_around(chunk.text, needle)
            if quote:
                item = _evidence(chunk, quote)
                if item:
                    break
    return [item] if item else []


def merge_chunks(
    results: list[tuple[SourceChunk, ExtractedChunk]],
) -> NormalizedExtraction:
    """Merge per-chunk answers into one network-local graph."""
    concepts: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    summaries: list[str] = []

    def ensure_concept(
        name: str, *, kind: str = "entity", confidence: float = 0.5
    ) -> str:
        key = _norm(name)
        if key in aliases:
            return aliases[key]
        base = concept_key(name)
        final_key = base
        suffix = 2
        # ``concepts`` is keyed by the final key, so membership is O(1). Rebuilding
        # a set of every key here made this loop O(C²) across a large document.
        while final_key in concepts:
            final_key = f"{base}_{suffix}"
            suffix += 1
        record = {
            "key": final_key,
            "name": str(name).strip(),
            "description": "",
            "kind": kind if kind in CONCEPT_KINDS else "entity",
            "aliases": [],
            "attributes": [],
            "confidence": _clamp(confidence),
            "evidence": [],
        }
        concepts[final_key] = record
        aliases[key] = final_key
        return final_key

    for chunk, result in results:
        if result.summary.strip():
            summaries.append(result.summary.strip())
        for concept in result.concepts:
            name = " ".join(concept.name.split()).strip()
            if not name:
                continue
            key = ensure_concept(name, kind=concept.kind, confidence=concept.confidence)
            record = concepts[key]
            if len(concept.description.strip()) > len(record["description"]):
                record["description"] = concept.description.strip()
            record["confidence"] = max(record["confidence"], _clamp(concept.confidence))
            record["aliases"] = list(
                dict.fromkeys(
                    [
                        *record["aliases"],
                        *[
                            " ".join(alias.split()).strip()
                            for alias in concept.aliases
                            if alias.strip()
                        ],
                    ]
                )
            )[:20]
            seen_attributes = {item["name"] for item in record["attributes"]}
            for attribute in concept.attributes:
                attr_name = " ".join(attribute.name.split()).strip()
                if not attr_name or attr_name in seen_attributes:
                    continue
                seen_attributes.add(attr_name)
                record["attributes"].append(
                    {
                        "name": attr_name,
                        "display_name": attr_name,
                        "type": (attribute.type or "string").strip() or "string",
                        "value": attribute.value,
                        "description": attribute.description or "",
                    }
                )
            record["evidence"].extend(_concept_evidence(chunk, concept))
            for alias in concept.aliases:
                if alias.strip():
                    aliases.setdefault(_norm(alias), key)

    relations: dict[str, dict[str, Any]] = {}
    for chunk, result in results:
        for relation in result.relations:
            source_key = aliases.get(_norm(relation.source))
            target_key = aliases.get(_norm(relation.target))
            if source_key is None:
                source_key = ensure_concept(relation.source, confidence=0.4)
            if target_key is None:
                target_key = ensure_concept(relation.target, confidence=0.4)
            name = " ".join(relation.name.split()).strip()
            if not name or source_key == target_key:
                continue
            key = relation_key(source_key, target_key, name)
            record = relations.setdefault(
                key,
                {
                    "key": key,
                    "source_key": source_key,
                    "target_key": target_key,
                    "name": name,
                    "description": "",
                    "kind": relation.kind
                    if relation.kind in RELATION_KINDS
                    else "association",
                    "confidence": _clamp(relation.confidence),
                    "evidence": [],
                },
            )
            record["confidence"] = max(
                float(record["confidence"]), _clamp(relation.confidence)
            )
            if len(relation.description.strip()) > len(record["description"]):
                record["description"] = relation.description.strip()
            quote = relation.evidence_quote or _quote_around(
                chunk.text, relation.source
            )
            evidence = _evidence(chunk, quote)
            if evidence:
                record["evidence"].append(evidence)

    actions: dict[str, dict[str, Any]] = {}
    for chunk, result in results:
        for action in result.actions:
            name = " ".join(action.name.split()).strip()
            if not name:
                continue
            key = _slug(name, prefix="a")
            bound_key = (
                aliases.get(_norm(action.bound_concept))
                if action.bound_concept
                else None
            )
            record = actions.setdefault(
                key,
                {
                    "key": key,
                    "name": name,
                    "description": action.description.strip(),
                    "action_intent": action.action_intent
                    if action.action_intent in {"add", "modify", "delete", "execute"}
                    else "execute",
                    "bound_key": bound_key,
                    "parameters": [
                        item for item in action.parameters if isinstance(item, dict)
                    ][:20],
                    "confidence": _clamp(action.confidence),
                    "evidence": [],
                },
            )
            record["confidence"] = max(
                float(record["confidence"]), _clamp(action.confidence)
            )
            if len(action.description.strip()) > len(record["description"]):
                record["description"] = action.description.strip()
            if record.get("bound_key") is None and bound_key:
                record["bound_key"] = bound_key
            quote = action.evidence_quote or _quote_around(chunk.text, name)
            evidence = _evidence(chunk, quote)
            if evidence:
                record["evidence"].append(evidence)

    risks: dict[str, dict[str, Any]] = {}
    for chunk, result in results:
        for risk in result.risks:
            name = " ".join(risk.name.split()).strip()
            if not name:
                continue
            key = _slug(name, prefix="k")
            related_key = (
                aliases.get(_norm(risk.related_concept))
                if risk.related_concept
                else None
            )
            record = risks.setdefault(
                key,
                {
                    "key": key,
                    "name": name,
                    "description": risk.description.strip(),
                    "severity": risk.severity
                    if risk.severity in {"low", "medium", "high", "critical"}
                    else "medium",
                    "mitigation": (risk.mitigation or "").strip() or None,
                    "related_key": related_key,
                    "confidence": _clamp(risk.confidence),
                    "evidence": [],
                },
            )
            record["confidence"] = max(
                float(record["confidence"]), _clamp(risk.confidence)
            )
            if len(risk.description.strip()) > len(record["description"]):
                record["description"] = risk.description.strip()
            if not record.get("mitigation") and risk.mitigation:
                record["mitigation"] = risk.mitigation.strip()
            if record.get("related_key") is None and related_key:
                record["related_key"] = related_key
            quote = risk.evidence_quote or _quote_around(chunk.text, name)
            evidence = _evidence(chunk, quote)
            if evidence:
                record["evidence"].append(evidence)

    metrics: dict[str, dict[str, Any]] = {}
    for chunk, result in results:
        for metric in result.metrics:
            name = " ".join(metric.name.split()).strip()
            if not name:
                continue
            key = _slug(name, prefix="m")
            owner_key = (
                aliases.get(_norm(metric.related_concept))
                if metric.related_concept
                else None
            )
            record = metrics.setdefault(
                key,
                {
                    "key": key,
                    "name": name,
                    "description": metric.description.strip(),
                    "expression": (metric.expression or "").strip() or None,
                    "unit": (metric.unit or "").strip() or None,
                    "concept_key": owner_key,
                    "confidence": _clamp(metric.confidence),
                    "evidence": [],
                },
            )
            record["confidence"] = max(
                float(record["confidence"]), _clamp(metric.confidence)
            )
            if len(metric.description.strip()) > len(record["description"]):
                record["description"] = metric.description.strip()
            if not record.get("expression") and metric.expression:
                record["expression"] = metric.expression.strip()
            if not record.get("unit") and metric.unit:
                record["unit"] = metric.unit.strip()
            if record.get("concept_key") is None and owner_key:
                record["concept_key"] = owner_key
            quote = metric.evidence_quote or _quote_around(chunk.text, name)
            evidence = _evidence(chunk, quote)
            if evidence:
                record["evidence"].append(evidence)

    facts: dict[str, dict[str, Any]] = {}
    for chunk, result in results:
        for fact in result.facts:
            subject_key = aliases.get(_norm(fact.subject))
            if subject_key is None:
                continue
            statement = " ".join(fact.statement.split()).strip()
            if not statement:
                continue
            object_key = aliases.get(_norm(fact.object))
            dedupe = f"{subject_key}|{_norm(fact.predicate)}|{_norm(fact.object)}"
            record = facts.setdefault(
                dedupe,
                {
                    "subject_key": subject_key,
                    "object_key": object_key,
                    "object_text": None if object_key else fact.object.strip() or None,
                    "predicate": fact.predicate.strip() or "related_to",
                    "statement": statement,
                    "confidence": _clamp(fact.confidence),
                    "evidence": [],
                },
            )
            record["confidence"] = max(
                float(record["confidence"]), _clamp(fact.confidence)
            )
            evidence = _evidence(chunk, fact.evidence_quote)
            if evidence:
                record["evidence"].append(evidence)
    # A fact with no quotable support is a guess, not knowledge.
    facts = {key: value for key, value in facts.items() if value["evidence"]}
    actions = {key: value for key, value in actions.items() if value["evidence"]}
    risks = {key: value for key, value in risks.items() if value["evidence"]}
    metrics = {key: value for key, value in metrics.items() if value["evidence"]}

    return NormalizedExtraction(
        summary="; ".join(dict.fromkeys(summaries))[:1200],
        concepts=sorted(concepts.values(), key=lambda item: item["name"]),
        relations=sorted(relations.values(), key=lambda item: item["name"]),
        facts=sorted(facts.values(), key=lambda item: item["statement"]),
        actions=sorted(actions.values(), key=lambda item: item["name"]),
        risks=sorted(risks.values(), key=lambda item: item["name"]),
        metrics=sorted(metrics.values(), key=lambda item: item["name"]),
    )


def _extract_chunk(
    title: str,
    chunk: SourceChunk,
    index: int,
    total: int,
) -> ExtractedChunk:
    from langchain_core.messages import HumanMessage, SystemMessage

    from all_ontology.utils.llm_invoke import safe_invoke_structured_nr

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Document title: {title}\n"
                f"Chunk {index}/{total}, pages {chunk.page_start}-{chunk.page_end}\n\n"
                "----- document chunk start -----\n"
                f"{chunk.text}\n"
                "----- document chunk end -----"
            )
        ),
    ]
    result = safe_invoke_structured_nr(messages, ExtractedChunk)
    if result is None:
        raise RuntimeError(
            "The extraction model returned no usable result. Check that the chat model is configured under Settings > Model settings."
        )
    return result


def extract_document(
    document_id: str,
    *,
    max_chunks: int = MAX_CHUNKS,
    chunk_chars: int = CHUNK_CHARS,
) -> dict[str, Any]:
    """Extract one knowledge document synchronously and persist its graph."""
    document = knowledge_dal.get_document(document_id)
    if document is None:
        raise ValueError("Knowledge document not found.")
    if not document.get("run_id"):
        raise ValueError(
            "This knowledge document is not linked to a parsing result, so it cannot be extracted."
        )

    knowledge_dal.update_document(document_id, status="extracting", error_message="")
    try:
        blocks, metadata = blocks_for_run(str(document["run_id"]))
        chunks = chunk_blocks(
            blocks,
            max_chars=max(1200, chunk_chars),
            max_chunks=max(1, max_chunks),
        )
        title = str(
            document.get("title") or metadata.get("file_name") or "Untitled document"
        )
        results: list[tuple[SourceChunk, ExtractedChunk]] = []
        for index, chunk in enumerate(chunks, start=1):
            results.append((chunk, _extract_chunk(title, chunk, index, len(chunks))))
        normalized = merge_chunks(results)
        knowledge_dal.save_extraction(
            document_id,
            summary=normalized.summary,
            concepts=normalized.concepts,
            relations=normalized.relations,
            facts=normalized.facts,
            actions=normalized.actions,
            risks=normalized.risks,
            metrics=normalized.metrics,
            chunk_count=len(chunks),
        )
    except Exception as exc:
        logger.exception("Knowledge extraction failed for document %s", document_id)
        knowledge_dal.update_document(
            document_id,
            status="failed",
            error_message=str(exc)[:2000] or type(exc).__name__,
        )
        raise

    refreshed = knowledge_dal.get_document(document_id) or document
    return {
        **refreshed,
        "concepts": len(normalized.concepts),
        "relations": len(normalized.relations),
        "facts": len(normalized.facts),
        "actions": len(normalized.actions),
        "risks": len(normalized.risks),
        "metrics": len(normalized.metrics),
    }
