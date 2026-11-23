// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type {
	ErdAssistantReply,
	ErdCanvas,
	ErdArea,
	ErdExport,
	ErdExportFormat,
	ErdIndex,
	ErdImportResult,
	ErdNode,
	ErdNote,
	ErdRelationship,
	ErdViewport,
	ErdVersion,
	SqlDialect,
} from '@/types/erd';

export type NodePatch = {
	x?: number;
	y?: number;
	collapsed?: boolean;
	width?: number;
	name?: string;
	columns?:
		| {
				name: string;
				data_type: string;
				is_primary_key?: boolean;
				is_unique?: boolean;
				is_nullable?: boolean;
				note?: string | null;
		  }[]
		| null;
	/** Canvas display order by column name. Works for catalog tables too. */
	column_order?: string[] | null;
	/** `column name -> alias`. Accepted for catalog tables as well. */
	column_notes?: Record<string, string> | null;
	indexes?: ErdIndex[] | null;
	note?: string | null;
};

export type NodeCreateInput = {
	canvas_id: string;
	name: string;
	table_id?: string | null;
	columns?: { name: string; data_type?: string | null }[] | null;
	column_order?: string[] | null;
	indexes?: ErdIndex[] | null;
	note?: string | null;
	x: number;
	y: number;
	width?: number;
};

export type RelationshipInput = {
	canvas_id: string;
	source_node_id: string;
	target_node_id: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: string;
	label?: string | null;
};

export type RelationshipPatch = {
	cardinality?: string;
	label?: string;
	source_columns?: string[];
	target_columns?: string[];
};

/** The canvas as the assistant sees it — ids, names, columns, lines. */
export type AssistantCanvasInput = {
	nodes: {
		id: string;
		name: string;
		table_id: string | null;
		columns: { name: string; data_type: string | null; note: string | null }[];
		note: string | null;
	}[];
	relationships: {
		id: string;
		source: string;
		target: string;
		source_columns: string[];
		target_columns: string[];
		cardinality: string;
		label: string | null;
	}[];
};

export const erdApi = {
	getCanvas: (zoneId: string) =>
		requests.get<{ data: ErdCanvas }>(`erd/canvases/${encodeURIComponent(zoneId)}`),

	updateViewport: (zoneId: string, viewport: ErdViewport) =>
		requests.patch<{ data: ErdCanvas }>(`erd/canvases/${encodeURIComponent(zoneId)}`, viewport),

	updateNode: (nodeId: string, patch: NodePatch) =>
		requests.patch<{ data: ErdNode }>(`erd/nodes/${encodeURIComponent(nodeId)}`, patch),

	createNode: (input: NodeCreateInput) => requests.post<{ data: ErdNode }>('erd/nodes', input),

	deleteNode: (nodeId: string) =>
		requests.delete<{ data: { id: string } }>(`erd/nodes/${encodeURIComponent(nodeId)}`),

	restoreNode: (nodeId: string) =>
		requests.post<{ data: ErdNode }>(`erd/nodes/${encodeURIComponent(nodeId)}/restore`, {}),

	createRelationship: (input: RelationshipInput) =>
		requests.post<{ data: ErdRelationship }>('erd/relationships', input),

	updateRelationship: (relId: string, patch: RelationshipPatch) =>
		requests.patch<{ data: ErdRelationship }>(
			`erd/relationships/${encodeURIComponent(relId)}`,
			patch,
		),

	deleteRelationship: (relId: string) =>
		requests.delete<{ data: { id: string } }>(`erd/relationships/${encodeURIComponent(relId)}`),

	importCanvas: (
		zoneId: string,
		body: { format: ErdExportFormat; content: string; replace: boolean },
	) =>
		requests.post<{ data: ErdImportResult }>(
			`erd/canvases/${encodeURIComponent(zoneId)}/import`,
			body,
		),

	exportCanvas: (zoneId: string, format: ErdExportFormat, dialect: SqlDialect = 'postgres') =>
		requests.get<{ data: ErdExport }>(
			`erd/canvases/${encodeURIComponent(zoneId)}/export`,
			format === 'sql' ? { format, dialect } : { format },
		),

	restoreState: (
		zoneId: string,
		body: {
			nodes: ErdNode[];
			relationships: ErdRelationship[];
			notes: ErdNote[];
			areas: ErdArea[];
		},
	) =>
		requests.put<{ data: ErdCanvas }>(`erd/canvases/${encodeURIComponent(zoneId)}/state`, body),

	createNote: (input: { canvas_id: string; text: string; x: number; y: number }) =>
		requests.post<{ data: ErdNote }>('erd/notes', input),

	updateNote: (
		noteId: string,
		patch: { text?: string; x?: number; y?: number; width?: number; height?: number },
	) => requests.patch<{ data: ErdNote }>(`erd/notes/${encodeURIComponent(noteId)}`, patch),

	deleteNote: (noteId: string) =>
		requests.delete<{ data: { id: string } }>(`erd/notes/${encodeURIComponent(noteId)}`),

	createArea: (input: { canvas_id: string; name: string; x: number; y: number }) =>
		requests.post<{ data: ErdArea }>('erd/areas', input),

	updateArea: (
		areaId: string,
		patch: {
			name?: string;
			x?: number;
			y?: number;
			width?: number;
			height?: number;
		},
	) => requests.patch<{ data: ErdArea }>(`erd/areas/${encodeURIComponent(areaId)}`, patch),

	deleteArea: (areaId: string) =>
		requests.delete<{ data: { id: string } }>(`erd/areas/${encodeURIComponent(areaId)}`),

	listVersions: (zoneId: string) =>
		requests.get<{ data: ErdVersion[]; count: number }>(
			`erd/canvases/${encodeURIComponent(zoneId)}/versions`,
		),

	createVersion: (zoneId: string, label: string, uid?: string) =>
		requests.post<{ data: ErdVersion }>(
			`erd/canvases/${encodeURIComponent(zoneId)}/versions${
				uid ? `?uid=${encodeURIComponent(uid)}` : ''
			}`,
			{ label },
		),

	restoreVersion: (versionId: string) =>
		requests.post<{ data: ErdCanvas }>(
			`erd/versions/${encodeURIComponent(versionId)}/restore`,
			{},
		),

	deleteVersion: (versionId: string) =>
		requests.delete<{ data: { id: string } }>(`erd/versions/${encodeURIComponent(versionId)}`),

	/** Ask the canvas assistant what to change. Nothing is written by this call. */
	askAssistant: (input: {
		zone_id: string;
		message: string;
		canvas: AssistantCanvasInput;
		history: { role: 'user' | 'assistant'; content: string }[];
	}) => requests.post<{ data: ErdAssistantReply }>('erd/assistant', input),
};
