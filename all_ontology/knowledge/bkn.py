# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Export a knowledge network as a BKN package.

BKN (Business Knowledge Network) is the Markdown-based modelling format used by
openbkn/bkn-foundry. The mapping is intentionally conservative:

* a concept becomes ``object_types/<key>.bkn``;
* a relation becomes ``relation_types/<key>.bkn``;
* every object type gets a synthetic ``concept_id`` key and every relation a
  ``concept_id -> concept_id`` placeholder mapping, so the package validates
  even before a physical data resource is attached.

The last point matters: BKN models *data-bound* object types, while a document
concept may have no table yet. The placeholder keeps the semantic graph
portable, and once a concept is linked to a catalog table the export can be
refined with real mapping rules.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from typing import Any


def _network_key(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if text:
        return text[:80]
    return f"kn_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]}"


def _property_name(name: str, index: int) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
    if text and text[0].isalnum():
        return text[:40]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"p_{index}_{digest}"[:40]


def _property_type(value: str | None) -> str:
    text = (value or "string").strip().lower()
    if text in {"number", "float", "decimal", "integer", "int"}:
        return "decimal"
    if text in {"date", "datetime", "timestamp", "time"}:
        return text
    if text in {"boolean", "bool"}:
        return "boolean"
    if text == "text":
        return "text"
    return "string"


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>").strip()


def _yaml(value: Any) -> str:
    """A YAML scalar that stays valid for Chinese text and punctuation."""
    return json.dumps(str(value or ""), ensure_ascii=False)


def _object_type(concept: dict[str, Any]) -> str:
    properties: list[tuple[str, str, str, str]] = [
        ("concept_id", "概念 ID", "string", "知识本体的稳定标识"),
    ]
    for index, attribute in enumerate(concept.get("attributes") or [], start=1):
        if not isinstance(attribute, dict):
            continue
        display = str(attribute.get("display_name") or attribute.get("name") or "")
        if not display:
            continue
        properties.append(
            (
                _property_name(str(attribute.get("name") or display), index),
                display,
                _property_type(attribute.get("type")),
                str(attribute.get("description") or attribute.get("value") or ""),
            )
        )

    aliases = [
        str(item).strip() for item in concept.get("aliases") or [] if str(item).strip()
    ]
    description_parts = [str(concept.get("description") or "").strip()]
    if aliases:
        description_parts.append(f"别名：{'、'.join(aliases)}。")
    description_parts.append(
        f"抽取可信度：{float(concept.get('confidence') or 0):.2f}；"
        f"认证状态：{concept.get('status') or 'draft'}。"
    )
    description = "\n\n".join(part for part in description_parts if part)
    frontmatter_aliases = ""
    if aliases:
        frontmatter_aliases = "\naliases:\n" + "\n".join(
            f"  - {_yaml(alias)}" for alias in aliases[:10]
        )
    rows = "\n".join(
        f"| {_cell(name)} | {_cell(display)} | {_cell(kind)} | {_cell(note)} | {_cell(name)} |"
        for name, display, kind, note in properties
    )
    return f"""---
type: object_type
id: {concept["key"]}
name: {_yaml(concept["name"])}
tags: [knowledge-ontology]{frontmatter_aliases}
---

## ObjectType: {concept["name"]}

{description}

### Data Properties

| Name | Display Name | Type | Description | Mapped Field |
|------|--------------|------|-------------|--------------|
{rows}

### Keys

Primary Keys: concept_id
Display Key: concept_id
"""


def _relation_type(
    relation: dict[str, Any],
    concepts_by_id: dict[str, dict[str, Any]],
) -> str:
    source = concepts_by_id.get(relation["source_concept_id"], {})
    target = concepts_by_id.get(relation["target_concept_id"], {})
    description = str(relation.get("description") or "").strip()
    suffix = (
        f"关系类型：{relation.get('kind') or 'association'}；"
        f"抽取可信度：{float(relation.get('confidence') or 0):.2f}。"
    )
    body = "\n\n".join(part for part in (description, suffix) if part)
    return f"""---
type: relation_type
id: {relation["key"]}
name: {_yaml(relation["name"])}
tags: [knowledge-ontology]
---

## RelationType: {relation["name"]}

{body}

### Endpoint

| Source | Target | Type |
|--------|--------|------|
| {source.get("key") or relation["source_concept_id"]} | {target.get("key") or relation["target_concept_id"]} | direct |

### Mapping Rules

| Source Property | Target Property |
|-----------------|-----------------|
| concept_id | concept_id |

<!-- {source.get("name", "")} -> {target.get("name", "")} -->
"""


def build_bkn_package(
    network: dict[str, Any],
    concepts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> tuple[str, bytes]:
    """Return ``(download_name, tar.gz_bytes)`` for a BKN v3 package."""
    network_id = _network_key(str(network["name"]))
    files: dict[str, str] = {}
    files["network.bkn"] = f"""---
type: knowledge_network
id: {network_id}
name: {_yaml(network["name"])}
tags: [knowledge-ontology]
bkn_spec: "3.0"
version: "{network.get("version") or "1.0"}"
---

# {network["name"]}

{network.get("description") or ""}

## Network Overview

由 All-Ontology 知识本体导出。概念 {len(concepts)} 个，关系 {len(relations)} 个，
事实 {len(facts)} 个。领域：{network.get("domain") or "未指定"}。
"""
    for concept in concepts:
        files[f"object_types/{concept['key']}.bkn"] = _object_type(concept)
    concepts_by_id = {str(item["id"]): item for item in concepts}
    for relation in relations:
        files[f"relation_types/{relation['key']}.bkn"] = _relation_type(
            relation, concepts_by_id
        )

    evidence_rows: list[dict[str, Any]] = []
    for fact in facts:
        for evidence in fact.get("evidence") or []:
            evidence_rows.append(
                {
                    "kind": "fact",
                    "statement": fact.get("statement"),
                    "page": evidence.get("page"),
                    "block_index": evidence.get("block_index"),
                    "quote": evidence.get("quote"),
                }
            )
    files["evidence.json"] = json.dumps(
        {
            "network": network["name"],
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "evidence": evidence_rows,
        },
        ensure_ascii=False,
        indent=2,
    )
    files["README.md"] = (
        "# BKN export\n\n"
        "This package was exported from All-Ontology's knowledge ontology.\n"
        f"Network: {network['name']}\n\n"
        "`object_types/` and `relation_types/` follow the BKN 3.0 Markdown "
        "format. `evidence.json` is an All-Ontology companion file and is "
        "ignored by BKN loaders.\n"
    )

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, content in sorted(files.items()):
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            archive.addfile(info, io.BytesIO(payload))
    return f"{network_id}.bkn.tar.gz", buffer.getvalue()
