// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { bezierPath, columnPort, edgeSides } from '@/lib/erd/geometry';
import type { ErdCardinality, ErdNode, ErdRelationship } from '@/types/erd';
import type { Point } from '@/lib/erd/geometry';

const CARDINALITY_LABEL: Record<ErdCardinality, string> = {
	'one-to-one': '1 : 1',
	'one-to-many': '1 : N',
	'many-to-one': 'N : 1',
	'many-to-many': 'N : M',
};

/** Which end of the line is "many" for each cardinality. */
const ENDS: Record<ErdCardinality, { source: 'one' | 'many'; target: 'one' | 'many' }> = {
	'one-to-one': { source: 'one', target: 'one' },
	'one-to-many': { source: 'one', target: 'many' },
	'many-to-one': { source: 'many', target: 'one' },
	'many-to-many': { source: 'many', target: 'many' },
};

/** Crow's-foot glyph: a tick for "one", a three-pronged fork for "many". */
const CrowFoot = ({
	point,
	kind,
	direction,
	color,
}: {
	point: Point;
	kind: 'one' | 'many';
	direction: 1 | -1;
	color: string;
}) => {
	if (kind === 'one') {
		return (
			<path
				d={`M ${point.x} ${point.y - 6} L ${point.x} ${point.y + 6}`}
				stroke={color}
				strokeWidth={1.5}
			/>
		);
	}
	const baseX = point.x + direction * 9;
	return (
		<path
			d={[
				`M ${baseX} ${point.y} L ${point.x} ${point.y - 6}`,
				`M ${baseX} ${point.y} L ${point.x} ${point.y}`,
				`M ${baseX} ${point.y} L ${point.x} ${point.y + 6}`,
			].join(' ')}
			stroke={color}
			strokeWidth={1.5}
			fill="none"
		/>
	);
};

type RelationshipEdgeProps = {
	relationship: ErdRelationship;
	source: ErdNode;
	target: ErdNode;
	selected: boolean;
	onSelect: (id: string) => void;
};

export const RelationshipEdge = ({
	relationship,
	source,
	target,
	selected,
	onSelect,
}: RelationshipEdgeProps) => {
	const sides = edgeSides(source, target);
	const from = columnPort(source, relationship.source_columns[0] ?? null, sides.source);
	const to = columnPort(target, relationship.target_columns[0] ?? null, sides.target);
	const path = bezierPath(from, to);
	const middle = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
	const color = selected ? '#76b900' : '#a1a1aa';
	const ends = ENDS[relationship.cardinality];
	const forward = to.x >= from.x ? 1 : -1;

	return (
		<g>
			<path
				d={path}
				fill="none"
				stroke={color}
				strokeWidth={selected ? 2.5 : 1.5}
				strokeDasharray={relationship.source_columns.length === 0 ? '6 4' : undefined}
				className="transition-[stroke]"
			/>
			<CrowFoot point={from} kind={ends.source} direction={forward as 1 | -1} color={color} />
			<CrowFoot point={to} kind={ends.target} direction={-forward as 1 | -1} color={color} />
			<path
				d={path}
				fill="none"
				stroke="transparent"
				strokeWidth={14}
				className="cursor-pointer"
				onClick={(event) => {
					event.stopPropagation();
					onSelect(relationship.id);
				}}
			/>
			<g transform={`translate(${middle.x}, ${middle.y})`} pointerEvents="none">
				<rect
					x={-18}
					y={-9}
					width={36}
					height={18}
					rx={9}
					fill={selected ? '#76b900' : '#ffffff'}
					stroke={selected ? '#76b900' : '#d4d4d8'}
				/>
				<text
					textAnchor="middle"
					dominantBaseline="middle"
					fontSize={10}
					fontWeight={600}
					fill={selected ? '#ffffff' : '#52525b'}
				>
					{CARDINALITY_LABEL[relationship.cardinality]}
				</text>
			</g>
		</g>
	);
};
