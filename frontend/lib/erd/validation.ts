// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ErdNode, ErdRelationship } from '@/types/erd';

export type ErdIssueSeverity = 'error' | 'warning';

export type ErdIssue = {
	id: string;
	severity: ErdIssueSeverity;
	/** English template, translated at the display site. */
	message: string;
	params: Record<string, string>;
	nodeId?: string;
	relationshipId?: string;
};

/**
 * Checks a diagram can actually be trusted.
 *
 * The important one is the dangling reference: editing or importing a table can
 * remove a column a line still points at, and a line drawn to a column that no
 * longer exists is worse than no line at all — it looks intentional.
 */
export const validateCanvas = (nodes: ErdNode[], relationships: ErdRelationship[]): ErdIssue[] => {
	const issues: ErdIssue[] = [];
	const byId = new Map(nodes.map((node) => [node.id, node]));

	const byName = new Map<string, ErdNode[]>();
	for (const node of nodes) {
		const key = node.name.trim().toLowerCase();
		byName.set(key, [...(byName.get(key) ?? []), node]);

		const seen = new Set<string>();
		for (const column of node.columns) {
			const columnKey = column.name.trim().toLowerCase();
			if (seen.has(columnKey)) {
				issues.push({
					id: `dup-column-${node.id}-${columnKey}`,
					severity: 'error',
					message: 'Duplicate column "{0}" in "{1}"',
					params: { 0: column.name, 1: node.name },
					nodeId: node.id,
				});
			}
			seen.add(columnKey);
		}
		if (node.columns.length === 0) {
			issues.push({
				id: `empty-${node.id}`,
				severity: 'warning',
				message: 'Table "{0}" has no columns',
				params: { 0: node.name },
				nodeId: node.id,
			});
		}

		const columnNames = new Set(node.columns.map((column) => column.name));
		const seenIndexNames = new Set<string>();
		for (const index of node.indexes) {
			const missing = index.columns.filter((name) => !columnNames.has(name));
			if (missing.length > 0) {
				issues.push({
					id: `index-column-${node.id}-${index.columns.join('-')}`,
					severity: 'error',
					message: 'Index on "{0}" references a column that does not exist: {1}',
					params: { 0: node.name, 1: missing.join(', ') },
					nodeId: node.id,
				});
			}
			if (index.name) {
				const key = index.name.toLowerCase();
				if (seenIndexNames.has(key)) {
					issues.push({
						id: `index-name-${node.id}-${key}`,
						severity: 'warning',
						message: 'Two indexes on "{0}" are named "{1}"',
						params: { 0: node.name, 1: index.name },
						nodeId: node.id,
					});
				}
				seenIndexNames.add(key);
			}
		}
	}

	for (const [name, group] of byName) {
		if (group.length > 1) {
			issues.push({
				id: `dup-name-${name}`,
				severity: 'warning',
				message: 'Two tables are named "{0}"',
				params: { 0: group[0].name },
				nodeId: group[0].id,
			});
		}
	}

	for (const relationship of relationships) {
		const source = byId.get(relationship.source_node_id);
		const target = byId.get(relationship.target_node_id);
		if (!source || !target) {
			issues.push({
				id: `missing-node-${relationship.id}`,
				severity: 'error',
				message: 'Relationship {0} → {1} points at a missing table',
				params: { 0: source?.name ?? '?', 1: target?.name ?? '?' },
				relationshipId: relationship.id,
			});
			continue;
		}
		const sourceColumns = new Set(source.columns.map((column) => column.name));
		const targetColumns = new Set(target.columns.map((column) => column.name));
		const missing =
			relationship.source_columns.some((name) => !sourceColumns.has(name)) ||
			relationship.target_columns.some((name) => !targetColumns.has(name));
		if (missing) {
			issues.push({
				id: `dangling-${relationship.id}`,
				severity: 'error',
				message: 'Relationship {0} → {1} references a column that no longer exists',
				params: { 0: source.name, 1: target.name },
				relationshipId: relationship.id,
			});
		}
	}

	return issues;
};
