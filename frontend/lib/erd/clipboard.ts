// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * The ER canvas clipboard.
 *
 * Copy/paste is deliberately name-addressed rather than id-addressed: it has to
 * survive a switch to another zone, where none of the original ids exist. The
 * payload therefore carries table names, whole column lists and the
 * relationships that sit *between* the copied tables.
 */

import type { ErdCardinality, ErdColumn, ErdIndex } from '@/types/erd';

export const ERD_CLIPBOARD_KEY = 'all-ontology-erd-clipboard';

export type ClipboardNode = {
	name: string;
	columns: ErdColumn[];
	indexes: ErdIndex[];
	note: string | null;
	x: number;
	y: number;
	width?: number;
};

export type ClipboardRelationship = {
	source: string;
	target: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
	label: string | null;
};

export type ErdClipboard = {
	nodes: ClipboardNode[];
	relationships: ClipboardRelationship[];
	/** How far the paste is offset from the copied position, so it lands visibly. */
	offset: number;
};

/** The clipboard, or ``null`` when nothing usable was copied yet. */
export const readClipboard = (): ErdClipboard | null => {
	if (typeof window === 'undefined') return null;
	try {
		const raw = window.localStorage.getItem(ERD_CLIPBOARD_KEY);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as ErdClipboard;
		return Array.isArray(parsed?.nodes) ? parsed : null;
	} catch {
		// Storage can be blocked or hold something another build wrote.
		return null;
	}
};

export const writeClipboard = (payload: ErdClipboard): void => {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(ERD_CLIPBOARD_KEY, JSON.stringify(payload));
	} catch {
		// A full or disabled store just means paste is unavailable this session.
	}
};
