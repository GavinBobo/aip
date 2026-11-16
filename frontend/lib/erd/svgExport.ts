// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
	bezierPath,
	CARD_COLUMN_NOTE_HEIGHT,
	CARD_HEADER_HEIGHT,
	CARD_ROW_HEIGHT,
	CARD_WIDTH,
	columnPort,
	columnTop,
	edgeSides,
	nodeHeight,
} from './geometry';
import type { ErdCardinality, ErdNode, ErdNote, ErdRelationship } from '@/types/erd';

const CARDINALITY_LABEL: Record<ErdCardinality, string> = {
	'one-to-one': '1 : 1',
	'one-to-many': '1 : N',
	'many-to-one': 'N : 1',
	'many-to-many': 'N : M',
};

const ENDS: Record<ErdCardinality, { source: 'one' | 'many'; target: 'one' | 'many' }> = {
	'one-to-one': { source: 'one', target: 'one' },
	'one-to-many': { source: 'one', target: 'many' },
	'many-to-one': { source: 'many', target: 'one' },
	'many-to-many': { source: 'many', target: 'many' },
};

const crowFoot = (
	point: { x: number; y: number },
	kind: 'one' | 'many',
	direction: 1 | -1,
): string => {
	if (kind === 'one') {
		return `<path d="M ${point.x} ${point.y - 6} L ${point.x} ${point.y + 6}" stroke="#a1a1aa" stroke-width="1.5"/>`;
	}
	const baseX = point.x + direction * 9;
	return `<path d="M ${baseX} ${point.y} L ${point.x} ${point.y - 6} M ${baseX} ${point.y} L ${point.x} ${point.y} M ${baseX} ${point.y} L ${point.x} ${point.y + 6}" stroke="#a1a1aa" stroke-width="1.5" fill="none"/>`;
};

const escapeXml = (value: string) =>
	value
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');

export type SvgDiagram = {
	svg: string;
	width: number;
	height: number;
};

/**
 * Render the diagram as a standalone SVG.
 *
 * Separate from the interactive canvas on purpose: the canvas is HTML cards in
 * a transformed div, which `foreignObject` would capture badly and every
 * browser would rasterise differently. This draws the same model directly, so
 * the export is deterministic and opens in any vector tool.
 */
export const buildSvgDiagram = (
	nodes: ErdNode[],
	relationships: ErdRelationship[],
	notes: ErdNote[] = [],
	padding = 40,
): SvgDiagram | null => {
	if (nodes.length === 0 && notes.length === 0) return null;
	const minX = Math.min(
		...(nodes.length ? nodes.map((node) => node.x) : [0]),
		...(notes.length ? notes.map((note) => note.x) : [0]),
	);
	const minY = Math.min(
		...(nodes.length ? nodes.map((node) => node.y) : [0]),
		...(notes.length ? notes.map((note) => note.y) : [0]),
	);
	const maxX = Math.max(
		...(nodes.length ? nodes.map((node) => node.x + CARD_WIDTH) : [0]),
		...(notes.length ? notes.map((note) => note.x + note.width) : [0]),
	);
	const maxY = Math.max(
		...(nodes.length ? nodes.map((node) => node.y + nodeHeight(node)) : [0]),
		...(notes.length ? notes.map((note) => note.y + note.height) : [0]),
	);
	const width = maxX - minX + padding * 2;
	const height = maxY - minY + padding * 2;
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const parts: string[] = [];

	parts.push(`<rect x="0" y="0" width="${width}" height="${height}" fill="#fafafa"/>`);

	for (const relationship of relationships) {
		const source = byId.get(relationship.source_node_id);
		const target = byId.get(relationship.target_node_id);
		if (!source || !target) continue;
		const sides = edgeSides(source, target);
		const from = columnPort(source, relationship.source_columns[0] ?? null, sides.source);
		const to = columnPort(target, relationship.target_columns[0] ?? null, sides.target);
		const path = bezierPath(from, to);
		const forward = to.x >= from.x ? 1 : -1;
		const ends = ENDS[relationship.cardinality];
		parts.push(
			`<path d="${path}" fill="none" stroke="#a1a1aa" stroke-width="1.5"${
				relationship.source_columns.length === 0 ? ' stroke-dasharray="6 4"' : ''
			}/>`,
			crowFoot(from, ends.source, forward as 1 | -1),
			crowFoot(to, ends.target, -forward as 1 | -1),
		);
		const middle = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
		parts.push(
			`<g transform="translate(${middle.x}, ${middle.y})">`,
			'<rect x="-18" y="-9" width="36" height="18" rx="9" fill="#ffffff" stroke="#d4d4d8"/>',
			`<text text-anchor="middle" dominant-baseline="middle" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="#52525b">${
				CARDINALITY_LABEL[relationship.cardinality]
			}</text>`,
			'</g>',
		);
	}

	for (const node of nodes) {
		const heightOfNode = nodeHeight(node);
		parts.push(
			`<g transform="translate(${node.x}, ${node.y})">`,
			`<rect width="${CARD_WIDTH}" height="${heightOfNode}" rx="8" fill="#ffffff" stroke="#d4d4d8"/>`,
			`<path d="M0 8 a8 8 0 0 1 8 -8 H${CARD_WIDTH - 8} a8 8 0 0 1 8 8 V${CARD_HEADER_HEIGHT} H0 Z" fill="#f4f4f5"/>`,
			`<text x="10" y="${CARD_HEADER_HEIGHT / 2 + 4}" font-family="system-ui, sans-serif" font-size="12" font-weight="600" fill="#18181b">${escapeXml(
				node.name,
			)}</text>`,
		);
		if (node.table_id == null) {
			parts.push(
				`<text x="${CARD_WIDTH - 10}" y="${CARD_HEADER_HEIGHT / 2 + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="9" fill="#b45309">virtual</text>`,
			);
		}
		if (!node.collapsed) {
			node.columns.forEach((column, index) => {
				const rowY = columnTop(node, index);
				parts.push(
					`<text x="10" y="${rowY + CARD_ROW_HEIGHT / 2 + 4}" font-family="system-ui, sans-serif" font-size="10" fill="#3f3f46">${
						column.is_primary_key ? '◆ ' : ''
					}${escapeXml(column.name)}</text>`,
				);
				parts.push(
					`<text x="${CARD_WIDTH - 10}" y="${rowY + CARD_ROW_HEIGHT / 2 + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="9" fill="#71717a">${escapeXml(
						column.data_type ?? '',
					)}</text>`,
				);
				if (column.note) {
					parts.push(
						`<text x="10" y="${rowY + CARD_ROW_HEIGHT + CARD_COLUMN_NOTE_HEIGHT - 4}" font-family="system-ui, sans-serif" font-size="9" fill="#a1a1aa">${escapeXml(
							column.note,
						)}</text>`,
					);
				}
			});
		}
		parts.push('</g>');
	}

	for (const note of notes) {
		const wrapWidth = Math.max(12, Math.floor(note.width / 7.2));
		const lines: string[] = [];
		for (const paragraph of (note.text || '').split('\n')) {
			let remaining = paragraph;
			while (remaining.length > wrapWidth) {
				lines.push(remaining.slice(0, wrapWidth));
				remaining = remaining.slice(wrapWidth);
			}
			lines.push(remaining);
		}
		const visible = lines.slice(0, Math.max(1, Math.floor((note.height - 20) / 15)));
		parts.push(
			`<g transform="translate(${note.x}, ${note.y})">`,
			`<rect width="${note.width}" height="${note.height}" rx="8" fill="${note.color ?? '#fef3c7'}" stroke="rgba(180,83,9,0.35)"/>`,
			visible
				.map(
					(line, index) =>
						`<text x="10" y="${22 + index * 15}" font-family="system-ui, sans-serif" font-size="11" fill="#78350f">${escapeXml(line)}</text>`,
				)
				.join(''),
			'</g>',
		);
	}

	const svg = [
		`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
		`<g transform="translate(${-minX + padding}, ${-minY + padding})">`,
		...parts,
		'</g>',
		'</svg>',
	].join('\n');

	return { svg, width, height };
};

export const downloadSvg = (diagram: SvgDiagram, filename: string) => {
	const blob = new Blob([diagram.svg], { type: 'image/svg+xml;charset=utf-8' });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = filename;
	document.body.appendChild(anchor);
	anchor.click();
	anchor.remove();
	URL.revokeObjectURL(url);
};

/** Rasterise the SVG at 2x so the PNG is readable when pasted into a doc. */
export const downloadPng = async (
	diagram: SvgDiagram,
	filename: string,
	scale = 2,
): Promise<void> => {
	const image = new Image();
	const blob = new Blob([diagram.svg], { type: 'image/svg+xml;charset=utf-8' });
	const url = URL.createObjectURL(blob);
	try {
		await new Promise<void>((resolve, reject) => {
			image.onload = () => resolve();
			image.onerror = () => reject(new Error('Could not render the diagram'));
			image.src = url;
		});
		const canvas = document.createElement('canvas');
		canvas.width = diagram.width * scale;
		canvas.height = diagram.height * scale;
		const context = canvas.getContext('2d');
		if (!context) throw new Error('Canvas is unavailable');
		context.scale(scale, scale);
		context.drawImage(image, 0, 0);
		const pngBlob = await new Promise<Blob | null>((resolve) =>
			canvas.toBlob(resolve, 'image/png'),
		);
		if (!pngBlob) throw new Error('Could not encode the PNG');
		const pngUrl = URL.createObjectURL(pngBlob);
		const anchor = document.createElement('a');
		anchor.href = pngUrl;
		anchor.download = filename;
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
		URL.revokeObjectURL(pngUrl);
	} finally {
		URL.revokeObjectURL(url);
	}
};
