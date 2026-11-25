# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Controlled graph traversal over a knowledge network.

This is intentionally not an arbitrary Cypher executor. The query surface is a
typed traversal (seeds, direction, relation kinds, depth), so it can never
escape the network or run write operations.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from all_ontology.dal import knowledge as knowledge_dal


def query_graph(
    network_id: str,
    *,
    start_concept_ids: list[str],
    depth: int = 2,
    direction: str = "both",
    relation_kinds: list[str] | None = None,
    include_data_links: bool = False,
    zone_ids: list[str] | None = None,
) -> dict[str, Any]:
    concepts = knowledge_dal.list_concepts(network_id, zone_ids)
    concept_map = {str(item["id"]): item for item in concepts}
    relations = knowledge_dal.list_relations(network_id)
    allowed_kinds = {item for item in relation_kinds or [] if item}
    adjacency: dict[str, list[dict[str, Any]]] = {key: [] for key in concept_map}
    for relation in relations:
        if allowed_kinds and relation.get("kind") not in allowed_kinds:
            continue
        source = str(relation["source_concept_id"])
        target = str(relation["target_concept_id"])
        if source not in concept_map or target not in concept_map:
            continue
        if direction in {"out", "both"}:
            adjacency[source].append(relation)
        if direction in {"in", "both"}:
            adjacency[target].append(relation)

    seeds = [item for item in start_concept_ids if item in concept_map]
    if not seeds:
        seeds = list(concept_map)
    depth = max(0, min(int(depth), 4))
    visited = set(seeds)
    queue = deque((seed, 0) for seed in seeds)
    selected_relations: dict[str, dict[str, Any]] = {}
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for relation in adjacency.get(current, []):
            selected_relations[str(relation["id"])] = relation
            source = str(relation["source_concept_id"])
            target = str(relation["target_concept_id"])
            for neighbor in (source, target):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, current_depth + 1))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    data_nodes: dict[str, str] = {}
    for concept_id in visited:
        concept = concept_map[concept_id]
        nodes.append(
            {
                "id": concept_id,
                "kind": "concept",
                "label": concept["name"],
                "detail": concept.get("description"),
                "concept_kind": concept.get("kind"),
                "status": concept.get("status"),
                "confidence": concept.get("confidence"),
            }
        )
        if include_data_links:
            for link in concept.get("data_links") or []:
                node_id = f"{link['kind']}:{link['target_id']}"
                data_nodes[node_id] = link.get("name") or link["target_id"]
                edges.append(
                    {
                        "id": f"map:{link['id']}",
                        "source": concept_id,
                        "target": node_id,
                        "kind": "mapped_to",
                        "label": "mapped to",
                        "confidence": link.get("confidence"),
                    }
                )
    for node_id, label in data_nodes.items():
        nodes.append(
            {
                "id": node_id,
                "kind": "data",
                "label": label,
                "detail": node_id.split(":", 1)[0],
            }
        )
    for relation in selected_relations.values():
        edges.append(
            {
                "id": relation["id"],
                "source": relation["source_concept_id"],
                "target": relation["target_concept_id"],
                "kind": relation.get("kind") or "association",
                "label": relation["name"],
                "confidence": relation.get("confidence"),
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "seeds": seeds,
        "depth": depth,
        "direction": direction,
    }
