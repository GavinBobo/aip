// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ErdColumn, ErdNode, ErdViewport } from '@/types/erd';

/** Card metrics shared by the canvas and the hit-testing code. */
export const CARD_WIDTH = 248;
export const CARD_HEADER_HEIGHT = 36;
export const CARD_ROW_HEIGHT = 24;
/** Extra height a column row grows by when it carries an alias. */
export const CARD_COLUMN_NOTE_HEIGHT = 15;
/** Extra header height a table note adds under the table name. */
export const CARD_NOTE_HEIGHT = 10;
/** Padding between the header rule and the first column row (the card's body). */
export const CARD_BODY_PADDING = 2;
export const CARD_FOOTER_PADDING = 6;

export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 2.5;

export type Point = { x: number; y: number };

export type ColumnRef = {
	nodeId: string;
	column: string | null;
};

/** Height of one column row: the name line, plus the alias line when present. */
export const columnRowHeight = (column: ErdColumn): number =>
	CARD_ROW_HEIGHT + (column.note ? CARD_COLUMN_NOTE_HEIGHT : 0);

/** Distance from the card's top edge to the top of a column row. */
export const columnTop = (node: ErdNode, index: number): number => {
	// The rows sit inside a padded body, so a port computed from the header
	// alone lands two pixels above the row it belongs to.
	let top = cardHeaderHeight(node) + CARD_BODY_PADDING;
	const last = Math.min(index, node.columns.length);
	for (let position = 0; position < last; position++) {
		top += columnRowHeight(node.columns[position]);
	}
	return top;
};

/** Header height: the title line, plus the note line when the card shows one. */
export const cardHeaderHeight = (node: ErdNode): number =>
	CARD_HEADER_HEIGHT + (!node.collapsed && node.note ? CARD_NOTE_HEIGHT : 0);

export const nodeHeight = (node: ErdNode): number =>
	node.collapsed
		? cardHeaderHeight(node)
		: cardHeaderHeight(node) +
			node.columns.reduce((total, column) => total + columnRowHeight(column), 0) +
			CARD_FOOTER_PADDING;

/** Centre of a row's connection port, in world coordinates. */
export const columnPort = (node: ErdNode, column: string | null, side: 'left' | 'right'): Point => {
	const index = column == null ? -1 : node.columns.findIndex((row) => row.name === column);
	// A collapsed card has no rows on screen, so a line anchored to one would
	// float below the header. It joins the card's centre instead — the same
	// anchor a table-level relationship uses.
	// The port sits on the name line, not in the middle of a row that an alias
	// has made taller.
	const y =
		node.collapsed || index < 0
			? node.y + nodeHeight(node) / 2
			: node.y + columnTop(node, index) + CARD_ROW_HEIGHT / 2;
	return { x: side === 'right' ? node.x + CARD_WIDTH : node.x, y };
};

/** Which side to leave from and arrive at, so the curve does not loop back. */
export const edgeSides = (source: ErdNode, target: ErdNode) => {
	const forward = target.x >= source.x;
	return {
		source: (forward ? 'right' : 'left') as 'left' | 'right',
		target: (forward ? 'left' : 'right') as 'left' | 'right',
	};
};

/** A cubic Bézier that leaves and arrives horizontally. */
export const bezierPath = (from: Point, to: Point): string => {
	const offset = Math.max(60, Math.abs(to.x - from.x) / 2);
	const direction = to.x >= from.x ? 1 : -1;
	return [
		`M ${from.x} ${from.y}`,
		`C ${from.x + offset * direction} ${from.y},`,
		`${to.x - offset * direction} ${to.y},`,
		`${to.x} ${to.y}`,
	].join(' ');
};

export const screenToWorld = (point: Point, viewport: ErdViewport): Point => ({
	x: (point.x - viewport.x) / viewport.zoom,
	y: (point.y - viewport.y) / viewport.zoom,
});

export const worldToScreen = (point: Point, viewport: ErdViewport): Point => ({
	x: point.x * viewport.zoom + viewport.x,
	y: point.y * viewport.zoom + viewport.y,
});

export const clampZoom = (zoom: number): number => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));

/** Keeps the point under the cursor fixed while the scale changes. */
export const zoomAtPoint = (
	viewport: ErdViewport,
	nextZoom: number,
	anchor: Point,
): ErdViewport => {
	const zoom = clampZoom(nextZoom);
	const world = screenToWorld(anchor, viewport);
	return {
		zoom,
		x: anchor.x - world.x * zoom,
		y: anchor.y - world.y * zoom,
	};
};

export type Bounds = { minX: number; minY: number; maxX: number; maxY: number };

export const nodesBounds = (nodes: ErdNode[]): Bounds | null => {
	if (nodes.length === 0) return null;
	return nodes.reduce<Bounds>(
		(bounds, node) => ({
			minX: Math.min(bounds.minX, node.x),
			minY: Math.min(bounds.minY, node.y),
			maxX: Math.max(bounds.maxX, node.x + CARD_WIDTH),
			maxY: Math.max(bounds.maxY, node.y + nodeHeight(node)),
		}),
		{
			minX: Number.POSITIVE_INFINITY,
			minY: Number.POSITIVE_INFINITY,
			maxX: Number.NEGATIVE_INFINITY,
			maxY: Number.NEGATIVE_INFINITY,
		},
	);
};
