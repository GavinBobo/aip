// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { nodeHeight, nodeWidth } from './geometry';
import type { ErdNode, ErdRelationship } from '@/types/erd';

const COLUMN_GAP = 120;
const ROW_GAP = 48;
const ORIGIN = 40;

export type Placement = { x: number; y: number };

/**
 * A layered ("left to right by reference depth") arrangement.
 *
 * Deliberately simple: breadth-first from the most connected table, one column
 * per hop, stacked vertically. It gives a readable starting point for a
 * document that arrived without positions, and the user can drag from there.
 */
export const layeredLayout = (
	nodes: ErdNode[],
	relationships: ErdRelationship[],
): Record<string, Placement> => {
	if (nodes.length === 0) return {};

	const byId = new Map(nodes.map((node) => [node.id, node]));
	const adjacency = new Map<string, Set<string>>(nodes.map((node) => [node.id, new Set()]));
	for (const rel of relationships) {
		if (!byId.has(rel.source_node_id) || !byId.has(rel.target_node_id)) continue;
		adjacency.get(rel.source_node_id)?.add(rel.target_node_id);
		adjacency.get(rel.target_node_id)?.add(rel.source_node_id);
	}

	const degree = (id: string) => adjacency.get(id)?.size ?? 0;
	const ordered = [...nodes].sort(
		(a, b) => degree(b.id) - degree(a.id) || a.name.localeCompare(b.name),
	);

	const depth = new Map<string, number>();
	for (const start of ordered) {
		if (depth.has(start.id)) continue;
		depth.set(start.id, 0);
		const queue = [start.id];
		// An index cursor, not shift(): shift() re-indexes the whole array on
		// every pop, which turns this BFS into O(n²) on a large canvas.
		for (let cursor = 0; cursor < queue.length; cursor += 1) {
			const current = queue[cursor];
			const next = (depth.get(current) ?? 0) + 1;
			for (const neighbour of adjacency.get(current) ?? []) {
				if (depth.has(neighbour)) continue;
				depth.set(neighbour, next);
				queue.push(neighbour);
			}
		}
	}

	const columns = new Map<number, ErdNode[]>();
	for (const node of ordered) {
		const level = depth.get(node.id) ?? 0;
		const column = columns.get(level) ?? [];
		column.push(node);
		columns.set(level, column);
	}

	const placement: Record<string, Placement> = {};
	let levelX = ORIGIN;
	for (const column of [...columns.entries()]
		.sort((a, b) => a[0] - b[0])
		.map((entry) => entry[1])) {
		let y = ORIGIN;
		let width = 0;
		for (const node of column.sort((a, b) => a.name.localeCompare(b.name))) {
			placement[node.id] = { x: levelX, y };
			y += nodeHeight(node) + ROW_GAP;
			width = Math.max(width, nodeWidth(node));
		}
		levelX += width + COLUMN_GAP;
	}
	return placement;
};

/** A plain grid, used when a document has tables but no references to follow. */
export const gridLayout = (nodes: ErdNode[]): Record<string, Placement> => {
	const columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
	const placement: Record<string, Placement> = {};
	const widths = Array.from({ length: columns }, () => 0);
	const heights: number[] = [];
	nodes.forEach((node, index) => {
		const column = index % columns;
		const row = Math.floor(index / columns);
		widths[column] = Math.max(widths[column], nodeWidth(node));
		heights[row] = Math.max(heights[row] ?? 0, nodeHeight(node));
	});
	const xOffsets: number[] = [];
	let x = ORIGIN;
	for (const width of widths) {
		xOffsets.push(x);
		x += width + COLUMN_GAP;
	}
	const yOffsets: number[] = [];
	let y = ORIGIN;
	for (const height of heights) {
		yOffsets.push(y);
		y += height + ROW_GAP;
	}
	nodes.forEach((node, index) => {
		placement[node.id] = {
			x: xOffsets[index % columns],
			y: yOffsets[Math.floor(index / columns)],
		};
	});
	return placement;
};
