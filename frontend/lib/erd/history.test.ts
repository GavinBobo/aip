// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { CanvasHistory, HISTORY_LIMIT, type CanvasSnapshot } from './history';

const snapshot = (tag: string): CanvasSnapshot => ({
	nodes: [{ id: tag } as CanvasSnapshot['nodes'][number]],
	relationships: [],
	notes: [],
	areas: [],
});

const tagOf = (value: CanvasSnapshot): string => value.nodes[0].id;

describe('CanvasHistory', () => {
	it('starts empty and refuses to undo or redo', () => {
		const history = new CanvasHistory();
		expect(history.counts).toEqual({ undo: 0, redo: 0 });
		expect(history.takeUndo(snapshot('current'))).toBeNull();
		expect(history.takeRedo(snapshot('current'))).toBeNull();
	});

	it('walks back through remembered states and forwards again', () => {
		const history = new CanvasHistory();
		history.remember(snapshot('a'));
		history.remember(snapshot('b'));

		const previous = history.takeUndo(snapshot('c'));
		expect(previous && tagOf(previous)).toBe('b');
		expect(history.counts).toEqual({ undo: 1, redo: 1 });

		const next = history.takeRedo(snapshot('b'));
		expect(next && tagOf(next)).toBe('c');
		expect(history.counts).toEqual({ undo: 2, redo: 0 });
	});

	it('drops the redo branch as soon as a new edit is remembered', () => {
		const history = new CanvasHistory();
		history.remember(snapshot('a'));
		history.takeUndo(snapshot('b'));
		expect(history.counts.redo).toBe(1);

		history.remember(snapshot('a2'));
		expect(history.counts).toEqual({ undo: 1, redo: 0 });
	});

	it('keeps at most HISTORY_LIMIT steps', () => {
		const history = new CanvasHistory();
		for (let step = 0; step < HISTORY_LIMIT + 10; step++) {
			history.remember(snapshot(`s${step}`));
		}
		expect(history.counts.undo).toBe(HISTORY_LIMIT);
		// The oldest entries fell off; the newest one is still the last undo.
		expect(tagOf(history.takeUndo(snapshot('now')) as CanvasSnapshot)).toBe(
			`s${HISTORY_LIMIT + 9}`,
		);
	});

	it('clears both stacks', () => {
		const history = new CanvasHistory();
		history.remember(snapshot('a'));
		history.takeUndo(snapshot('b'));
		history.clear();
		expect(history.counts).toEqual({ undo: 0, redo: 0 });
	});
});
