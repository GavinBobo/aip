// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type ErdCardinality = 'one-to-one' | 'one-to-many' | 'many-to-one' | 'many-to-many';

export type ErdColumn = {
	name: string;
	data_type: string | null;
	is_primary_key: boolean;
	is_unique: boolean | null;
	is_nullable: boolean | null;
	note?: string | null;
};

export type ErdIndex = {
	name: string | null;
	columns: string[];
	unique: boolean;
};

export type ErdNode = {
	id: string;
	/** Null for a table that exists only on the canvas (imported or drawn by hand). */
	table_id: string | null;
	name: string;
	x: number;
	y: number;
	collapsed: boolean;
	columns: ErdColumn[];
	indexes: ErdIndex[];
	note: string | null;
};

export type ErdRelationship = {
	id: string;
	source_node_id: string;
	target_node_id: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
	label: string | null;
};

export type ErdViewport = {
	x: number;
	y: number;
	zoom: number;
};

export type ErdHiddenNode = {
	id: string;
	table_id: string | null;
	name: string;
};

export type ErdNote = {
	id: string;
	text: string;
	x: number;
	y: number;
	width: number;
	height: number;
	color: string | null;
};

export type ErdArea = {
	id: string;
	name: string;
	color: string | null;
	x: number;
	y: number;
	width: number;
	height: number;
};

export type ErdVersion = {
	id: string;
	label: string;
	created: string | null;
	created_by: string | null;
	node_count: number;
	relationship_count: number;
};

export type ErdCanvas = {
	id: string;
	zone_id: string;
	zone_name: string | null;
	viewport: ErdViewport;
	nodes: ErdNode[];
	relationships: ErdRelationship[];
	hidden_nodes: ErdHiddenNode[];
	notes: ErdNote[];
	areas: ErdArea[];
};

export type ErdExportFormat = 'json' | 'dbml' | 'sql';

export type SqlDialect = 'postgres' | 'mysql' | 'sqlite';

export type ErdExport = {
	format: ErdExportFormat;
	filename: string;
	content: string;
};

export type ErdImportResult = {
	canvas: ErdCanvas;
	imported_nodes: number;
	imported_relationships: number;
	warnings: string[];
};

/** What the canvas assistant can ask the browser to do.
 *
 * Flat with a `kind` tag, mirroring the backend model: the payload is generated
 * by a model, crosses JSON, and lands in a `switch` that calls `erdApi` — one
 * shape serves all three. The backend has already validated every action
 * against the canvas it was shown, so a kind with missing fields here is a bug
 * in that validator rather than something the UI has to defend against.
 */
export type ErdAssistantAction = {
	kind:
		| 'create_table'
		| 'add_column'
		| 'update_column'
		| 'rename_table'
		| 'set_table_note'
		| 'move_node'
		| 'delete_table'
		| 'bind_relationship'
		| 'delete_relationship';
	summary?: string | null;
	name?: string | null;
	columns?: { name: string; data_type?: string | null; note?: string | null }[];
	node_id?: string | null;
	column?: string | null;
	data_type?: string | null;
	note?: string | null;
	x?: number | null;
	y?: number | null;
	relationship_id?: string | null;
	source_node_id?: string | null;
	target_node_id?: string | null;
	source_columns?: string[];
	target_columns?: string[];
	cardinality?: ErdCardinality | null;
	label?: string | null;
};

export type ErdAssistantReply = {
	reply: string;
	actions: ErdAssistantAction[];
	/** Actions the server dropped because they could not be applied. */
	warnings: string[];
};
