// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRef, type PointerEvent as ReactPointerEvent } from 'react';

import { t } from '@/i18n';
import { CARD_WIDTH, nodeHeight, type Bounds } from '@/lib/erd/geometry';
import type { ErdArea, ErdNode, ErdNote, ErdViewport } from '@/types/erd';

const WIDTH = 176;
const HEIGHT = 118;
const PADDING = 12;

type MinimapProps = {
	nodes: ErdNode[];
	areas: ErdArea[];
	notes: ErdNote[];
	viewport: ErdViewport;
	containerWidth: number;
	containerHeight: number;
	onNavigate: (world: { x: number; y: number }) => void;
};

/**
 * A small overview that also lets you jump: click or drag inside it to move the
 * viewport. Same model as the canvas, so areas, notes and cards all appear.
 */
export const Minimap = ({
	nodes,
	areas,
	notes,
	viewport,
	containerWidth,
	containerHeight,
	onNavigate,
}: MinimapProps) => {
	const dragging = useRef(false);

	const rects = [
		...nodes.map((node) => ({
			x: node.x,
			y: node.y,
			width: CARD_WIDTH,
			height: nodeHeight(node),
			fill: '#a1a1aa',
		})),
		...areas.map((area) => ({
			x: area.x,
			y: area.y,
			width: area.width,
			height: area.height,
			fill: area.color ?? '#dbeafe',
		})),
		...notes.map((note) => ({
			x: note.x,
			y: note.y,
			width: note.width,
			height: note.height,
			fill: note.color ?? '#fef3c7',
		})),
	];

	// The viewport is part of the extent too, otherwise scrolling far away would
	// put the "you are here" rectangle outside the map.
	const view = {
		x: -viewport.x / viewport.zoom,
		y: -viewport.y / viewport.zoom,
		width: containerWidth / viewport.zoom,
		height: containerHeight / viewport.zoom,
	};
	const all = [...rects, { ...view, fill: 'transparent' }];
	const bounds: Bounds = all.reduce(
		(acc, rect) => ({
			minX: Math.min(acc.minX, rect.x),
			minY: Math.min(acc.minY, rect.y),
			maxX: Math.max(acc.maxX, rect.x + rect.width),
			maxY: Math.max(acc.maxY, rect.y + rect.height),
		}),
		{
			minX: Number.POSITIVE_INFINITY,
			minY: Number.POSITIVE_INFINITY,
			maxX: Number.NEGATIVE_INFINITY,
			maxY: Number.NEGATIVE_INFINITY,
		},
	);
	const spanX = Math.max(1, bounds.maxX - bounds.minX);
	const spanY = Math.max(1, bounds.maxY - bounds.minY);
	const scale = Math.min((WIDTH - PADDING * 2) / spanX, (HEIGHT - PADDING * 2) / spanY);
	const offsetX = PADDING + (WIDTH - PADDING * 2 - spanX * scale) / 2;
	const offsetY = PADDING + (HEIGHT - PADDING * 2 - spanY * scale) / 2;

	const toMini = (x: number, y: number) => ({
		x: offsetX + (x - bounds.minX) * scale,
		y: offsetY + (y - bounds.minY) * scale,
	});

	const navigate = (event: ReactPointerEvent<SVGSVGElement>) => {
		const rect = event.currentTarget.getBoundingClientRect();
		const world = {
			x: bounds.minX + (event.clientX - rect.left - offsetX) / scale,
			y: bounds.minY + (event.clientY - rect.top - offsetY) / scale,
		};
		onNavigate(world);
	};

	return (
		<div
			className="absolute bottom-4 right-4 z-10 overflow-hidden rounded-lg border border-zinc-300 bg-white/95 shadow-md dark:border-zinc-700 dark:bg-zinc-900/95"
			aria-label={t('Minimap')}
			// Without this the canvas would treat the click as background and
			// start panning while the minimap is also moving the viewport.
			onPointerDown={(event) => event.stopPropagation()}
		>
			<svg
				width={WIDTH}
				height={HEIGHT}
				className="cursor-pointer select-none"
				onPointerDown={(event) => {
					dragging.current = true;
					event.currentTarget.setPointerCapture(event.pointerId);
					navigate(event);
				}}
				onPointerMove={(event) => {
					if (dragging.current) navigate(event);
				}}
				onPointerUp={(event) => {
					dragging.current = false;
					event.currentTarget.releasePointerCapture(event.pointerId);
				}}
			>
				{rects.map((rect, index) => {
					const point = toMini(rect.x, rect.y);
					return (
						<rect
							key={index}
							x={point.x}
							y={point.y}
							width={Math.max(1, rect.width * scale)}
							height={Math.max(1, rect.height * scale)}
							rx={1}
							fill={rect.fill}
							opacity={0.85}
						/>
					);
				})}
				<rect
					x={toMini(view.x, view.y).x}
					y={toMini(view.x, view.y).y}
					width={Math.max(2, view.width * scale)}
					height={Math.max(2, view.height * scale)}
					fill="none"
					stroke="#76b900"
					strokeWidth={1.5}
				/>
			</svg>
		</div>
	);
};
