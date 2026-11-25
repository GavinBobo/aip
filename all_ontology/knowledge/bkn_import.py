# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import a BKN 3.x package into an existing knowledge network.

This is deliberately a structural importer, not a full BKN validator. It reads
the definition files `aip` exports and the common BKN shapes produced by
bkn-foundry, then upserts them by their BKN id. Unsupported content stays in
the file rather than being silently invented; the importer returns counts so
the UI can show what landed.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from typing import Any

import yaml

from all_ontology.dal import knowledge as knowledge_dal

MAX_ENTRIES = 10_000
MAX_BYTES = 64 * 1024 * 1024


@dataclass
class ParsedBkn:
    network_name: str | None = None
    network_description: str | None = None
    concepts: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)


def _read_files(payload: bytes, filename: str) -> dict[str, str]:
    if len(payload) > MAX_BYTES:
        raise ValueError("The BKN package exceeds the 64 MB limit.")
    files: dict[str, str] = {}
    if payload.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_ENTRIES:
                raise ValueError("The BKN package has too many entries.")
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    continue
                if name.startswith("__MACOSX/") or not name.endswith(
                    (".bkn", ".md", ".json")
                ):
                    continue
                files[name] = archive.read(info).decode("utf-8-sig", errors="replace")
        return files

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        if len(members) > MAX_ENTRIES:
            raise ValueError("The BKN package has too many entries.")
        for member in members:
            name = member.name.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue
            if not name.endswith((".bkn", ".md", ".json")):
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            files[name] = stream.read().decode("utf-8-sig", errors="replace")
    if not files:
        raise ValueError(f"Could not read {filename or 'BKN package'}.")
    return files


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        loaded = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _description(text: str) -> str:
    match = re.search(r"(?m)^##\s+[^\n]+\n(.*?)(?=^###\s|^##\s|\Z)", text, re.S)
    return match.group(1).strip() if match else ""


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(heading)}\s*\n(.*?)(?=^###\s|^##\s|\Z)",
        text,
    )
    return match.group(1) if match else ""


def _table(section: str) -> list[dict[str, str]]:
    lines = [
        line.strip() for line in section.splitlines() if line.strip().startswith("|")
    ]
    if len(lines) < 2:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def _kind_from_properties(properties: list[dict[str, str]]) -> str:
    semantics = {row.get("Semantic", "") for row in properties}
    if "event_time" in semantics:
        return "event"
    return "entity"


def parse_bkn_package(payload: bytes, filename: str = "") -> ParsedBkn:
    files = _read_files(payload, filename)
    network_file = next(
        (name for name in files if name.rsplit("/", 1)[-1] == "network.bkn"),
        None,
    )
    if network_file is None:
        raise ValueError("The BKN package is missing network.bkn.")
    network_front = _frontmatter(files[network_file])
    parsed = ParsedBkn(
        network_name=str(network_front.get("name") or "") or None,
        network_description=_description(files[network_file]) or None,
    )
    raw_capabilities = network_front.get("capabilities")
    if isinstance(raw_capabilities, dict):
        for section, kind in (
            ("skills", "skill"),
            ("functions", "function"),
            ("mcp_tools", "mcp_tool"),
            ("knowledge_bases", "knowledge_base"),
        ):
            for item in raw_capabilities.get(section) or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("id") or item.get("mcp_id") or "").strip()
                name = str(item.get("name") or item.get("mcp_name") or key).strip()
                if not key:
                    continue
                parsed.capabilities.append(
                    {
                        "key": key,
                        "name": name,
                        "kind": kind,
                        "description": None,
                        "config": item,
                    }
                )
    concepts: dict[str, dict[str, Any]] = {}
    relation_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []

    def ensure_concept(key: str) -> None:
        if key and key not in concepts:
            concepts[key] = {
                "key": key,
                "name": key,
                "description": "",
                "kind": "entity",
                "aliases": [],
                "attributes": [],
            }

    for name, text in files.items():
        if name.startswith("object_metrics/") and name.endswith(".json"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            definition = (
                payload.get("definition") if isinstance(payload, dict) else None
            )
            if not isinstance(definition, dict):
                continue
            key = str(definition.get("id") or "").strip()
            if not key:
                continue
            concept_key = str(definition.get("owner_object_type_id") or "").strip()
            if concept_key:
                ensure_concept(concept_key)
            metric_rows.append(
                {
                    "key": key,
                    "name": str(definition.get("name") or key),
                    "description": str(definition.get("description") or ""),
                    "expression": definition.get("expression"),
                    "unit": definition.get("unit"),
                    "concept_key": concept_key or None,
                }
            )
            continue
        if name.endswith("network.bkn") or name.rsplit("/", 1)[-1] in {
            "SKILL.md",
            "README.md",
        }:
            continue
        front = _frontmatter(text)
        key = str(front.get("id") or "").strip()
        if not key:
            continue
        display_name = str(front.get("name") or key)
        if name.startswith("object_types/"):
            properties = _table(_section(text, "Data Properties"))
            concepts[key] = {
                "key": key,
                "name": display_name,
                "description": _description(text),
                "kind": _kind_from_properties(properties),
                "aliases": [
                    str(alias)
                    for alias in front.get("aliases") or []
                    if str(alias).strip()
                ][:20],
                "attributes": [
                    {
                        "name": row.get("Name") or row.get("Display Name") or "",
                        "display_name": row.get("Display Name")
                        or row.get("Name")
                        or "",
                        "type": row.get("Type") or "string",
                        "description": row.get("Description") or "",
                    }
                    for row in properties
                    if row.get("Name")
                ][:200],
            }
        elif name.startswith("relation_types/"):
            endpoint = (_table(_section(text, "Endpoint")) or [{}])[0]
            source = endpoint.get("Source", "").strip()
            target = endpoint.get("Target", "").strip()
            if source and target:
                ensure_concept(source)
                ensure_concept(target)
                relation_rows.append(
                    {
                        "key": key,
                        "name": display_name,
                        "description": _description(text),
                        "kind": "association",
                        "source_key": source,
                        "target_key": target,
                    }
                )
        elif name.startswith("action_types/"):
            bound = (_table(_section(text, "Bound Object")) or [{}])[0]
            bound_key = bound.get("Bound Object", "").strip()
            if bound_key:
                ensure_concept(bound_key)
            action_rows.append(
                {
                    "key": key,
                    "name": display_name,
                    "description": _description(text),
                    "action_intent": str(front.get("action_intent") or "execute"),
                    "bound_key": bound_key or None,
                    "parameters": [],
                }
            )
        elif name.startswith("risk_types/"):
            description = _description(text)
            severity_match = re.search(
                r"(?:严重度|Severity)[：:]\s*(low|medium|high|critical)",
                description,
                re.I,
            )
            mitigation_match = re.search(
                r"(?:缓解措施|Mitigation)[：:]\s*(.+)", description
            )
            risk_rows.append(
                {
                    "key": key,
                    "name": display_name,
                    "description": description,
                    "severity": (
                        severity_match.group(1).lower() if severity_match else "medium"
                    ),
                    "mitigation": (
                        mitigation_match.group(1).strip().rstrip("。.")
                        if mitigation_match
                        else None
                    ),
                    "related_key": None,
                }
            )
        elif name.startswith("concept_groups/"):
            member_ids = [
                row.get("ID", "").strip()
                for row in _table(_section(text, "Object Types"))
                if row.get("ID")
            ]
            for member_id in member_ids:
                ensure_concept(member_id)
            group_rows.append(
                {
                    "key": key,
                    "name": display_name,
                    "description": _description(text),
                    "concept_keys": member_ids,
                }
            )

    parsed.concepts = list(concepts.values())
    parsed.relations = relation_rows
    parsed.actions = action_rows
    parsed.risks = risk_rows
    parsed.metrics = metric_rows
    parsed.groups = group_rows
    return parsed


def import_bkn_package(
    network_id: str, payload: bytes, filename: str = ""
) -> dict[str, Any]:
    parsed = parse_bkn_package(payload, filename)
    result = knowledge_dal.import_bkn_definitions(
        network_id,
        concepts=parsed.concepts,
        relations=parsed.relations,
        actions=parsed.actions,
        risks=parsed.risks,
        metrics=parsed.metrics,
        groups=parsed.groups,
        capabilities=parsed.capabilities,
    )
    return {
        **result,
        "network_name": parsed.network_name,
    }
