// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useMemo } from 'react';
import dynamic from 'next/dynamic';

import type { KnowledgeGraph as KnowledgeGraphData } from '@/api/knowledge';
import type { CanvasGraph } from '@/components/explorationPage/graph/GraphCanvas';
import { ExplorationLayer } from '@/enums/exploration';
import { t } from '@/i18n';

// The same Sigma/d3-force canvas the Exploration page uses. Dynamic import
// keeps WebGL out of the server bundle and avoids paying for it until this tab
// is opened.
const GraphCanvas = dynamic(
	() =>
		import('@/components/explorationPage/graph/GraphCanvas').then(
			(module) => module.GraphCanvas,
		),
	{
		ssr: false,
		loading: () => (
			<div className="flex h-full items-center justify-center text-sm text-secondary">
				{t('Loading graph…')}
			</div>
		),
	},
);

export const KnowledgeGraph = ({
	graph,
	onSelectConcept,
}: {
	graph: KnowledgeGraphData;
	onSelectConcept?: (conceptId: string) => void;
}) => {
	const canvasGraph = useMemo<CanvasGraph>(() => {
		const degree = new Map<string, number>();
		for (const edge of graph.edges) {
			degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
			degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
		}
		return {
			nodes: graph.nodes.map((node) => ({
				id: node.id,
				name: node.label,
				layer: node.kind === 'data' ? ExplorationLayer.Data : ExplorationLayer.Semantic,
				nodeKind:
					node.kind === 'data'
						? 'knowledgeData'
						: node.kind === 'action'
							? 'knowledgeAction'
							: node.kind === 'risk'
								? 'knowledgeRisk'
								: 'knowledgeConcept',
				relationshipCount: degree.get(node.id) ?? 0,
			})),
			links: graph.edges.map((edge) => ({
				source: edge.source,
				target: edge.target,
				relationshipTypes: [edge.kind],
				kind: edge.kind === 'mapped_to' ? 'structural' : 'relationship',
			})),
		};
	}, [graph]);

	const conceptsById = useMemo(
		() =>
			new Map(
				graph.nodes
					.filter((node) => node.kind === 'concept')
					.map((node) => [node.id, node]),
			),
		[graph.nodes],
	);

	const handleClickNode = useCallback(
		(nodeId: string) => {
			if (conceptsById.has(nodeId)) onSelectConcept?.(nodeId);
		},
		[conceptsById, onSelectConcept],
	);

	const noopNode = useCallback(() => undefined, []);
	const noopEdge = useCallback(() => undefined, []);
	const noopController = useCallback(() => undefined, []);

	if (graph.nodes.length === 0) {
		return (
			<div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-zinc-300 text-sm text-secondary dark:border-zinc-700">
				{t('Add a document to build the first graph.')}
			</div>
		);
	}

	return (
		<div className="relative h-[620px] overflow-hidden rounded-xl border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
			<GraphCanvas
				graph={canvasGraph}
				activeNodeId={null}
				highlightedPath={null}
				onSelectNode={noopNode}
				onSelectEdge={noopEdge}
				onClickNode={handleClickNode}
				onDoubleClickNode={handleClickNode}
				onHoverNode={noopNode}
				onControllerChange={noopController}
			/>
			<div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap items-center gap-4 bg-gradient-to-t from-white/95 to-transparent px-4 pt-8 pb-3 text-[11px] text-secondary dark:from-zinc-950/95">
				<span className="flex items-center gap-1.5">
					<span className="h-3 w-3 rounded-full border border-[#8b5cf6] bg-[#eadcff] dark:bg-[#33224f]" />
					{t('Knowledge concept')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-3 w-3 rounded-full border border-[#76b900] bg-[#dcfce7] dark:bg-[#1d3420]" />
					{t('Data object')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-3 w-3 rounded-full border border-[#f59e0b] bg-[#fef3c7] dark:bg-[#3a2a10]" />
					{t('Knowledge action')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-3 w-3 rounded-full border border-[#ef4444] bg-[#fee2e2] dark:bg-[#3a1d1d]" />
					{t('Knowledge risk')}
				</span>
				<span className="flex items-center gap-1.5">
					<span className="h-px w-5 border-t border-[#76b900]" />
					{t('Mapped to data')}
				</span>
			</div>
		</div>
	);
};
