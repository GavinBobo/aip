// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import {
	CARD_COLUMN_NOTE_HEIGHT,
	CARD_HEADER_HEIGHT,
	CARD_NOTE_HEIGHT,
	CARD_ROW_HEIGHT,
	CARD_WIDTH,
	cardHeaderHeight,
	columnPort,
	columnRowHeight,
	columnTop,
	nodeHeight,
} from './geometry';
import type { ErdColumn, ErdNode } from '@/types/erd';

const column = (name: string, note: string | null = null): ErdColumn => ({
	name,
	data_type: 'text',
	is_primary_key: false,
	is_unique: null,
	is_nullable: true,
	note,
});

const node = (columns: ErdColumn[], collapsed = false): ErdNode => ({
	id: 'n1',
	table_id: null,
	name: 'public.t',
	x: 100,
	y: 50,
	collapsed,
	columns,
	indexes: [],
	note: null,
});

describe('card geometry', () => {
	it('reserves a header line for the table note, unless the card is collapsed', () => {
		const noted = { ...node([column('a')]), note: '核心看板指标' };

		expect(cardHeaderHeight(noted)).toBe(CARD_HEADER_HEIGHT + CARD_NOTE_HEIGHT);
		expect(columnTop(noted, 0)).toBe(CARD_HEADER_HEIGHT + CARD_NOTE_HEIGHT);
		expect(nodeHeight(noted)).toBe(
			CARD_HEADER_HEIGHT + CARD_NOTE_HEIGHT + CARD_ROW_HEIGHT + 6,
		);
		// A collapsed card is the compact header only: no note line, no rows.
		expect(cardHeaderHeight({ ...noted, collapsed: true })).toBe(CARD_HEADER_HEIGHT);
	});

	it('grows a row by exactly the alias height when a column has one', () => {
		expect(columnRowHeight(column('a'))).toBe(CARD_ROW_HEIGHT);
		expect(columnRowHeight(column('a', 'alias'))).toBe(
			CARD_ROW_HEIGHT + CARD_COLUMN_NOTE_HEIGHT,
		);
	});

	it('stacks rows so later rows start below an alias', () => {
		const table = node([column('a', 'first'), column('b')]);
		expect(columnTop(table, 0)).toBe(CARD_HEADER_HEIGHT);
		expect(columnTop(table, 1)).toBe(
			CARD_HEADER_HEIGHT + CARD_ROW_HEIGHT + CARD_COLUMN_NOTE_HEIGHT,
		);
	});

	it('reports the full card height including the footer, and only the header when collapsed', () => {
		const table = node([column('a', 'x'), column('b')]);
		expect(nodeHeight(table)).toBe(
			CARD_HEADER_HEIGHT + (CARD_ROW_HEIGHT + CARD_COLUMN_NOTE_HEIGHT) + CARD_ROW_HEIGHT + 6,
		);
		expect(nodeHeight(node([column('a')], true))).toBe(CARD_HEADER_HEIGHT);
	});

	it('anchors a column port on the name line, not the middle of an alias row', () => {
		const table = node([column('a', 'alias')]);
		const port = columnPort(table, 'a', 'right');
		expect(port.x).toBe(100 + CARD_WIDTH);
		expect(port.y).toBe(50 + CARD_HEADER_HEIGHT + CARD_ROW_HEIGHT / 2);
	});

	it('falls back to the card centre for table-level and collapsed anchors', () => {
		const table = node([column('a')]);
		expect(columnPort(table, null, 'left').y).toBe(50 + nodeHeight(table) / 2);
		expect(columnPort(table, 'missing', 'left').y).toBe(50 + nodeHeight(table) / 2);
		expect(columnPort(node([column('a')], true), 'a', 'left').y).toBe(
			50 + CARD_HEADER_HEIGHT / 2,
		);
	});
});
