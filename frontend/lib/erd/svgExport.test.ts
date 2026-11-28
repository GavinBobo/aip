// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { CARD_WIDTH } from './geometry';
import { buildSvgDiagram } from './svgExport';
import type { ErdNode } from '@/types/erd';

const node = (overrides: Partial<ErdNode> = {}): ErdNode => ({
	id: 'n1',
	table_id: null,
	name: 'public.users',
	x: 0,
	y: 0,
	collapsed: false,
	columns: [],
	indexes: [],
	note: null,
	...overrides,
});

describe('buildSvgDiagram', () => {
	it('paints the background in viewport coordinates when nodes sit at negative x/y', () => {
		// Dragging a table above or left of the origin is normal on an infinite
		// canvas; the sheet used to start at ``padding - minX`` and leave a blank
		// strip instead of covering the export.
		const diagram = buildSvgDiagram([node({ x: -200, y: -100 })], []);

		expect(diagram).not.toBeNull();
		const rect = diagram!.svg.indexOf('<rect x="0" y="0"');
		const group = diagram!.svg.indexOf('<g transform="translate(');
		expect(rect).toBeGreaterThan(-1);
		expect(rect).toBeLessThan(group);
	});

	it('sizes the sheet from the bounding box plus padding', () => {
		const diagram = buildSvgDiagram([node({ x: -200, y: 0 })], [], [], 40);

		expect(diagram!.width).toBe(CARD_WIDTH + 80);
	});

	it('sizes the sheet from a table’s custom width', () => {
		const diagram = buildSvgDiagram([node({ x: -200, width: 420 })], [], [], 40);

		expect(diagram!.width).toBe(420 + 80);
	});

	it('exports the table note as a grey marker and a tooltip', () => {
		const diagram = buildSvgDiagram([node({ note: 'core metrics' })], []);

		expect(diagram!.svg).toContain('<title>core metrics</title>');
		expect(diagram!.svg).toContain('fill="#a1a1aa"');
	});

	it('paints a column with its configured colour and style', () => {
		const diagram = buildSvgDiagram(
			[
				node({
					columns: [
						{
							name: 'id',
							data_type: 'bigint',
							is_primary_key: true,
							is_unique: null,
							is_nullable: false,
							note: null,
							color: '#ff0000',
							style: 'bold',
						},
					],
				}),
			],
			[],
		);

		expect(diagram!.svg).toContain('fill="#ff0000"');
		expect(diagram!.svg).toContain('font-weight="700"');
	});
});
