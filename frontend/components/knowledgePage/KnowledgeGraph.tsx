// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo } from 'react';

import type { KnowledgeGraph as KnowledgeGraphData } from '@/api/knowledge';
import { t } from '@/i18n';

const WIDTH = 960;
const HEIGHT = 600;

const shortLabel = (label: string): string =>
	label.length > 14 ? `${label.slice(0, 13)}…` : label;

export const KnowledgeGraph = ({
	graph,
	onSelectConcept,
}: {
	graph: KnowledgeGraphData;
	onSelectConcept?: (conceptId: string) => void;
}) => {
	const layout = useMemo(() => {
		const concepts = graph.nodes.filter((node) => node.kind === 'concept');
		const dataNodes = graph.nodes.filter((node) => node.kind === 'data');
		const positions = new Map<string, { x: number; y: number; node: typeof graph.nodes[number] }>();
		const conceptRadius = Math.min(210, 120 + concepts.length * 3);
		concepts.forEach((node, index) => {
			const angle = (Math.PI * 2 * index) / Math.max(1, concepts.length) - Math.PI / 2;
			positions.set(node.id, {
				x: WIDTH / 2 + Math.cos(angle) * conceptRadius,
				y: HEIGHT / 2 + Math.sin(angle) * conceptRadius,
				node,
			});
		});
		dataNodes.forEach((node, index) => {
			const angle = (Math.PI * 2 * index) / Math.max(1, dataNodes.length) - Math.PI / 2;
			positions.set(node.id, {
				x: WIDTH / 2 + Math.cos(angle) * 330,
				y: HEIGHT / 2 + Math.sin(angle) * 230,
				node,
			});
		});
		return positions;
	}, [graph.nodes]);

	if (graph.nodes.length === 0) {
		return (
			<div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-zinc-300 text-sm text-secondary dark:border-zinc-700">
				{t('Add a document to build the first graph.')}
			</div>
		);
	}

	return (
		<div className="rounded-xl border border-zinc-200 bg-zinc-50/40 p-2 dark:border-zinc-800 dark:bg-zinc-900/40">
			<svg
				viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
				className="h-auto w-full"
				role="img"
				aria-label={t('Knowledge graph')}
			>
				<defs>
					<marker
						id="knowledge-arrow"
						viewBox="0 0 10 10"
						refX="9"
						refY="5"
						markerWidth="6"
						markerHeight="6"
						orient="auto-start-reverse"
					>
						<path d="M 0 0 L 10 5 L 0 10 z" fill="#a1a1aa" />
					</marker>
				</defs>
				{graph.edges.map((edge) => {
					const source = layout.get(edge.source);
					const target = layout.get(edge.target);
					if (!source || !target) return null;
					const mapped = edge.kind === 'mapped_to';
					return (
						<g key={edge.id}>
							<line
								x1={source.x}
								y1={source.y}
								x2={target.x}
								y2={target.y}
								stroke={mapped ? '#76b900' : '#a1a1aa'}
								strokeWidth={mapped ? 1.8 : 1.2}
								strokeDasharray={mapped ? '5 4' : undefined}
								markerEnd={mapped ? undefined : 'url(#knowledge-arrow)'}
								opacity={0.75}
							/>
							{edge.label && (
								<text
									x={(source.x + target.x) / 2}
									y={(source.y + target.y) / 2 - 4}
									textAnchor="middle"
									className="fill-zinc-500 text-[10px]"
								>
									{edge.label}
								</text>
							)}
						</g>
					);
				})}
				{Array.from(layout.values()).map(({ x, y, node }) => {
					const isData = node.kind === 'data';
					const certified = node.status === 'certified';
					const fill = isData ? '#f4f4f5' : certified ? '#ecfccb' : '#ffffff';
					const stroke = isData
						? '#76b900'
						: certified
							? '#65a30d'
							: '#d4d4d8';
					return (
						<g
							key={node.id}
							transform={`translate(${x} ${y})`}
							className={isData ? '' : 'cursor-pointer'}
							onClick={() => {
								if (!isData) onSelectConcept?.(node.id);
							}}
						>
							<title>{node.detail || node.label}</title>
							{isData ? (
								<rect
									x={-46}
									y={-16}
									width={92}
									height={32}
									rx={8}
									fill={fill}
									stroke={stroke}
									strokeWidth={1.2}
								/>
							) : (
								<circle r={34} fill={fill} stroke={stroke} strokeWidth={1.6} />
							)}
							<text
								y={isData ? 4 : 4}
								textAnchor="middle"
								className="fill-zinc-800 text-[11px] font-medium"
							>
								{shortLabel(node.label)}
							</text>
						</g>
					);
				})}
			</svg>
			<div className="flex flex-wrap items-center gap-4 px-3 pb-2 text-[11px] text-secondary">
				<span className="flex items-center gap-1.5">
					<span className="h-2.5 w-2.5 rounded-full border border-zinc-400 bg-white" />
					{t('Concept')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-2.5 w-2.5 rounded-full border border-[#65a30d] bg-[#ecfccb]" />
					{t('Certified concept')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-2.5 w-2.5 rounded-sm border border-[#76b900] bg-zinc-100" />
					{t('Data object')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-px w-5 border-t border-dashed border-[#76b900]" />
					{t('Mapped to data')}
				</span>
			</div>
		</div>
	);
};
