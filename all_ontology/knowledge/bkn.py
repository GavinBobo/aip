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


def _safe_aliases(values: Any) -> list[str]:
    """BKN aliases are short and cannot carry punctuation such as commas."""
    forbidden = set("/:?\\\"<>|：？‘’“”！《》,#[]{}%&*$^!=.'")
    aliases: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if (
            not text
            or len(text) > 40
            or any(char in forbidden for char in text)
            or text in aliases
        ):
            continue
        aliases.append(text)
    return aliases[:10]


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>").strip()


def _yaml(value: Any) -> str:
    """A YAML scalar that stays valid for Chinese text and punctuation."""
    return json.dumps(str(value or ""), ensure_ascii=False)


def _object_type(concept: dict[str, Any]) -> str:
    properties: list[tuple[str, str, str, str]] = [
        (
            "concept_id",
            "Concept ID",
            "string",
            "Stable identifier in the knowledge ontology",
        ),
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

    aliases = _safe_aliases(concept.get("aliases"))
    description_parts = [str(concept.get("description") or "").strip()]
    if aliases:
        description_parts.append(f"Aliases: {', '.join(aliases)}.")
    description_parts.append(
        f"Extraction confidence: {float(concept.get('confidence') or 0):.2f}; "
        f"status: {concept.get('status') or 'draft'}."
    )
    description = "\n\n".join(part for part in description_parts if part)
    frontmatter_aliases = ""
    if aliases:
        frontmatter_aliases = "\naliases:\n" + "\n".join(
            f"  - {_yaml(alias)}" for alias in aliases
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
        f"Relation type: {relation.get('kind') or 'association'}; "
        f"extraction confidence: {float(relation.get('confidence') or 0):.2f}."
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


def _action_type(
    action: dict[str, Any],
    concepts_by_id: dict[str, dict[str, Any]],
) -> str | None:
    """Render one action; unbound actions stay in aip rather than guessing a target."""
    bound = concepts_by_id.get(str(action.get("bound_concept_id") or ""))
    if bound is None:
        return None
    intent = str(action.get("action_intent") or "execute").lower()
    if intent not in {"add", "modify", "delete"}:
        intent = "modify"
    parameter_names = [
        str(item.get("name"))
        for item in action.get("parameters") or []
        if isinstance(item, dict) and item.get("name")
    ]
    description = str(action.get("description") or "").strip()
    if parameter_names:
        description = "\n\n".join(
            part
            for part in (
                description,
                f"Parameters: {', '.join(parameter_names)}.",
            )
            if part
        )
    action_source = ""
    for capability in action.get("capabilities") or []:
        config = capability.get("config") or {}
        if capability.get("kind") == "function":
            action_source = (
                "\n### Action Source\n\n"
                "| Type | BoxID | ToolID | McpID | ToolName |\n"
                "|------|-------|--------|-------|----------|\n"
                f"| tool | {_cell(config.get('box_id', capability.get('key')))} "
                f"| {_cell(config.get('tool_id', capability.get('key')))} | | |\n"
            )
            break
        if capability.get("kind") == "mcp_tool":
            action_source = (
                "\n### Action Source\n\n"
                "| Type | BoxID | ToolID | McpID | ToolName |\n"
                "|------|-------|--------|-------|----------|\n"
                f"| mcp | | | {_cell(config.get('mcp_id', capability.get('key')))} "
                f"| {_cell(config.get('tool_name', capability.get('name')))} |\n"
            )
            break
    return f"""---
type: action_type
id: {action["key"]}
name: {_yaml(action["name"])}
tags: [knowledge-ontology]
action_intent: {intent}
---

## ActionType: {action["name"]}

{description}

### Operation Config

```yaml
operation_config:
  type: object
```

### Bound Object

| Bound Object |
|--------------|
| {bound["key"]} |
{action_source}
"""


def _risk_type(risk: dict[str, Any]) -> str:
    description = "\n\n".join(
        part
        for part in (
            str(risk.get("description") or "").strip(),
            f"Severity: {risk.get('severity') or 'medium'}.",
            f"Mitigation: {risk['mitigation']}." if risk.get("mitigation") else "",
        )
        if part
    )
    return f"""---
type: risk_type
id: {risk["key"]}
name: {_yaml(risk["name"])}
tags: [knowledge-ontology]
---

## RiskType: {risk["name"]}

{description}
"""


def _concept_group(
    group: dict[str, Any],
    concept_keys: set[str],
) -> str:
    rows = "\n".join(
        f"| {member['key']} | {_cell(member.get('name'))} | |"
        for member in group.get("concepts") or []
        if member.get("key") in concept_keys
    )
    return f"""---
type: concept_group
id: {group["key"]}
name: {_yaml(group["name"])}
tags: [knowledge-ontology]
---

## ConceptGroup: {group["name"]}

{group.get("description") or ""}

### Object Types

| ID | Name | Description |
|----|------|-------------|
{rows}
"""


def _metric_json(
    metric: dict[str, Any],
    concepts_by_id: dict[str, dict[str, Any]],
) -> str | None:
    concept = concepts_by_id.get(str(metric.get("concept_id") or ""))
    if concept is None:
        return None
    payload = {
        "definition": {
            "id": metric["key"],
            "version": 1,
            "name": metric["name"],
            "description": metric.get("description") or "",
            "owner_object_type_id": concept["key"],
            "metric_type": "atomic",
            "expression": metric.get("expression"),
            "unit": metric.get("unit"),
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _capabilities_yaml(capabilities: list[dict[str, Any]]) -> str:
    sections = {
        "skill": "skills",
        "function": "functions",
        "mcp_tool": "mcp_tools",
        "knowledge_base": "knowledge_bases",
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for capability in capabilities:
        grouped.setdefault(
            sections.get(str(capability.get("kind")), "skills"), []
        ).append(capability)
    lines = ["capabilities:"]
    for section, items in grouped.items():
        lines.append(f"  {section}:")
        for item in items:
            config = item.get("config") or {}
            lines.append(f"    - id: {_yaml(item['key'])}")
            lines.append(f"      name: {_yaml(item['name'])}")
            if section == "functions":
                lines.append(
                    f"      box_id: {_yaml(config.get('box_id', item['key']))}"
                )
                lines.append(
                    f"      tool_id: {_yaml(config.get('tool_id', item['key']))}"
                )
                if config.get("box_name"):
                    lines.append(f"      box_name: {_yaml(config['box_name'])}")
            elif section == "mcp_tools":
                lines.append(
                    f"      mcp_id: {_yaml(config.get('mcp_id', item['key']))}"
                )
                lines.append(
                    f"      mcp_name: {_yaml(config.get('mcp_name', item['name']))}"
                )
                lines.append(
                    f"      tool_name: {_yaml(config.get('tool_name', item['name']))}"
                )
    return "\n".join(lines) + "\n"


def build_bkn_package(
    network: dict[str, Any],
    concepts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
    groups: list[dict[str, Any]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
) -> tuple[str, bytes]:
    """Return ``(download_name, tar.gz_bytes)`` for a BKN v3 package."""
    network_id = _network_key(str(network["name"]))
    files: dict[str, str] = {}
    capabilities_block = _capabilities_yaml(capabilities) if capabilities else ""
    files["network.bkn"] = f"""---
type: knowledge_network
id: {network_id}
name: {_yaml(network["name"])}
tags: [knowledge-ontology]
bkn_spec: "3.0"
version: "{network.get("version") or "1.0"}"
{capabilities_block}---

# {network["name"]}

{network.get("description") or ""}

## Network Overview

Exported from the All-Ontology knowledge ontology. {len(concepts)} concepts, {len(relations)} relations, {len(facts)} facts. Domain: {network.get("domain") or "Unspecified"}.
"""
    for concept in concepts:
        files[f"object_types/{concept['key']}.bkn"] = _object_type(concept)
    concepts_by_id = {str(item["id"]): item for item in concepts}
    concept_keys = {str(item["key"]) for item in concepts}
    for relation in relations:
        files[f"relation_types/{relation['key']}.bkn"] = _relation_type(
            relation, concepts_by_id
        )
    for action in actions or []:
        rendered = _action_type(action, concepts_by_id)
        if rendered is not None:
            files[f"action_types/{action['key']}.bkn"] = rendered
    for risk in risks or []:
        files[f"risk_types/{risk['key']}.bkn"] = _risk_type(risk)
    for group in groups or []:
        files[f"concept_groups/{group['key']}.bkn"] = _concept_group(
            group, concept_keys
        )
    for metric in metrics or []:
        rendered = _metric_json(metric, concepts_by_id)
        if rendered is not None:
            files[f"object_metrics/{metric['key']}@1.json"] = rendered

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
        "`object_types/`, `relation_types/`, `action_types/`, `risk_types/`, "
        "`concept_groups/` and `object_metrics/` follow the BKN 3.0 formats "
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
