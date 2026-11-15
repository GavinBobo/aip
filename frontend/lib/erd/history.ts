// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Undo/redo for the ER canvas.
 *
 * A snapshot is what the browser can see: nodes, relationships, sticky notes
 * and areas. Hidden catalog tombstones are *not* part of it — the server keeps
 * those, and answers a restore with the authoritative canvas.
 *
 * This is a plain class rather than a React hook so the stack rules live in one
 * readable place instead of being spread across the handlers that mutate the
 * canvas. Cloning stays at the call site: the caller already holds the live
 * arrays and knows when a copy is needed.
 */

import type { ErdArea, ErdNote, ErdNode, ErdRelationship } from '@/types/erd';

export type CanvasSnapshot = {
	nodes: ErdNode[];
	relationships: ErdRelationship[];
	notes: ErdNote[];
	areas: ErdArea[];
};

export type HistoryCounts = { undo: number; redo: number };

/** How many steps back a user can walk. */
export const HISTORY_LIMIT = 50;

export class CanvasHistory {
	private past: CanvasSnapshot[] = [];
	private future: CanvasSnapshot[] = [];

	constructor(private readonly limit: number = HISTORY_LIMIT) {}

	get counts(): HistoryCounts {
		return { undo: this.past.length, redo: this.future.length };
	}

	/** Remember `snapshot` as the state *before* the mutation the caller is about to make. */
	remember(snapshot: CanvasSnapshot): void {
		this.past = [...this.past.slice(1 - this.limit), snapshot];
		// A new edit invalidates everything that was redoable.
		this.future = [];
	}

	/** Step back, keeping `current` available for redo. ``null`` when at the start. */
	takeUndo(current: CanvasSnapshot): CanvasSnapshot | null {
		const previous = this.past[this.past.length - 1];
		if (!previous) return null;
		this.past = this.past.slice(0, -1);
		this.future = [...this.future, current];
		return previous;
	}

	/** Step forward, keeping `current` undoable again. ``null`` when at the end. */
	takeRedo(current: CanvasSnapshot): CanvasSnapshot | null {
		const next = this.future[this.future.length - 1];
		if (!next) return null;
		this.future = this.future.slice(0, -1);
		this.past = [...this.past, current];
		return next;
	}

	clear(): void {
		this.past = [];
		this.future = [];
	}
}
