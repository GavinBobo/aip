// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { gridLayout, layeredLayout } from './layout';
import type { ErdNode, ErdRelationship } from '@/types/erd';

const node = (id: string, name: string): ErdNode => ({
	id,
	table_id: null,
	name,
	x: 0,
	y: 0,
	collapsed: false,
	columns: [],
	indexes: [],
	note: null,
});

const relationship = (id: string, source: string, target: string): ErdRelationship => ({
	id,
	source_node_id: source,
	target_node_id: target,
	source_columns: ['id'],
	target_columns: ['id'],
	cardinality: 'one-to-many',
	label: null,
});

describe('layeredLayout', () => {
	it('places every node of a long chain from a single BFS pass', () => {
		const count = 2000;
		const nodes = Array.from({ length: count }, (_, index) =>
			node(`n${index}`, `table_${index}`),
		);
		const relationships = Array.from({ length: count - 1 }, (_, index) =>
			relationship(`r${index}`, `n${index}`, `n${index + 1}`),
		);

		const placement = layeredLayout(nodes, relationships);

		expect(Object.keys(placement)).toHaveLength(count);
		for (const position of Object.values(placement)) {
			expect(Number.isFinite(position.x)).toBe(true);
			expect(Number.isFinite(position.y)).toBe(true);
		}
		const xs = Object.values(placement).map((position) => position.x);
		expect(Math.max(...xs)).toBeGreaterThan(Math.min(...xs));
	});

	it('keeps every node reachable through one hub', () => {
		const count = 500;
		const nodes = [
			node('hub', 'hub'),
			...Array.from({ length: count }, (_, i) => node(`n${i}`, `t${i}`)),
		];
		const relationships = Array.from({ length: count }, (_, i) =>
			relationship(`r${i}`, 'hub', `n${i}`),
		);

		const placement = layeredLayout(nodes, relationships);

		expect(Object.keys(placement)).toHaveLength(count + 1);
		expect(placement.hub).toBeDefined();
	});
});

describe('gridLayout', () => {
	it('places a large unconnected document on a grid without losing nodes', () => {
		const nodes = Array.from({ length: 1000 }, (_, index) =>
			node(`n${index}`, `table_${index}`),
		);

		const placement = gridLayout(nodes);

		expect(Object.keys(placement)).toHaveLength(nodes.length);
		expect(new Set(Object.values(placement).map((p) => `${p.x}:${p.y}`)).size).toBeGreaterThan(
			1,
		);
	});
});
