// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type ErdCardinality = 'one-to-one' | 'one-to-many' | 'many-to-one' | 'many-to-many';

export type ErdColumnStyle = 'normal' | 'bold' | 'italic' | 'monospace';

export type ErdColumn = {
	name: string;
	data_type: string | null;
	is_primary_key: boolean;
	is_unique: boolean | null;
	is_nullable: boolean | null;
	note?: string | null;
	color?: string | null;
	style?: ErdColumnStyle | null;
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
	category?: string | null;
	x: number;
	y: number;
	width?: number;
	collapsed: boolean;
	columns: ErdColumn[];
	/** Canvas display order for catalog columns, by name. Null follows the catalog. */
	column_order?: string[] | null;
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

export type SqlDialect = 'sqlserver' | 'postgres' | 'mysql' | 'mariadb' | 'oracle' | 'sqlite';

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

export type ErdParsedTable = {
	name: string;
	columns: ErdColumn[];
	indexes: ErdIndex[];
};

export type ErdParsedRelationship = {
	source: string;
	target: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
	label: string | null;
};

export type ErdDdlParseResult = {
	tables: ErdParsedTable[];
	relationships: ErdParsedRelationship[];
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

export type ErdOntologyIssue = {
	code: string;
	severity: 'info' | 'warning' | 'error';
	message: string;
	params?: Record<string, string | number | null | undefined>;
	entity_id?: string | null;
	relationship_id?: string | null;
};

export type ErdOntologyColumn = {
	name: string;
	data_type: string | null;
	description: string | null;
	is_primary_key: boolean | null;
	is_unique: boolean | null;
	is_nullable: boolean | null;
	semantic_hint: string | null;
	sensitivity_hint: string | null;
	sample_values: unknown[];
	distinct_values: unknown[];
};

export type ErdOntologyTerm = {
	id?: string | null;
	name: string;
	description?: string | null;
	synonyms?: string[];
	exists?: boolean | null;
	name_certified?: boolean | null;
	description_certified?: boolean | null;
};

export type ErdOntologyEntity = {
	id: string;
	table_id: string | null;
	name: string;
	table_name: string | null;
	database_name: string | null;
	schema_name: string | null;
	category: string | null;
	semantic_role: string;
	status: 'ready' | 'needs_review' | 'existing' | 'virtual';
	confidence: number;
	description: string | null;
	simulated: boolean;
	primary_keys: string[];
	grain: { columns?: string[]; confidence?: string };
	columns: ErdOntologyColumn[];
	term: ErdOntologyTerm | null;
	existing_column_attributes: number;
	existing_semantic_fks: number;
	proposed_term: ErdOntologyTerm | null;
	warnings: ErdOntologyIssue[];
	signals: string[];
	apply: {
		can_apply?: boolean;
		term_name?: string;
		description?: string;
		synonyms?: string[];
	};
};

export type ErdOntologyRelationship = {
	id: string;
	label: string | null;
	source_node_id: string;
	target_node_id: string;
	source_table: string;
	target_table: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
	referencing_table: string | null;
	referenced_table: string | null;
	referencing_columns: string[];
	referenced_columns: string[];
	status: 'validated' | 'declared' | 'probable' | 'needs_review' | 'logical_only' | 'invalid';
	confidence: number;
	unique: boolean;
	checks: {
		catalog_fk?: boolean;
		type_compatible?: boolean | null;
		target_unique?: boolean | null;
		value_overlap?: number | null;
		type_pairs?: {
			source: string;
			target: string;
			source_family: string;
			target_family: string;
		}[];
	};
	existing_semantic_fk: boolean;
	warnings: ErdOntologyIssue[];
	apply: {
		can_apply?: boolean;
		referencing_table_id?: string | null;
		referenced_table_id?: string | null;
		referencing_columns?: string[];
		referenced_columns?: string[];
		unique?: boolean;
	};
};

export type ErdOntologySummary = {
	node_count: number;
	mapped_node_count: number;
	virtual_node_count: number;
	term_count: number;
	description_count: number;
	relationship_count: number;
	validated_relationship_count: number;
	existing_semantic_fk_count: number;
	issue_count: number;
	gap_count: number;
	readiness: number;
	readiness_label: 'ready' | 'review' | 'early';
};

export type ErdOntologyReport = {
	zone_id: string | null;
	canvas_id: string | null;
	zone_name: string | null;
	generated_at: string | null;
	summary: ErdOntologySummary;
	entities: ErdOntologyEntity[];
	relationships: ErdOntologyRelationship[];
	catalog_fks_not_drawn: {
		source_table_id?: string;
		source_column?: string;
		target_table_id?: string;
		target_column?: string;
	}[];
	gaps: ErdOntologyIssue[];
};

export type ErdOntologyApplyResult = {
	terms_created: { table_id: string; term_id: string; name: string }[];
	terms_updated: { table_id: string; term_id: string; name: string }[];
	terms_reused: { table_id: string; term_id: string; name: string }[];
	semantic_fks_created: {
		relationship_id: string;
		source_table_id: string;
		source_column: string;
		target_table_id: string;
		target_column: string;
		attribute_id: string;
	}[];
	skipped: { id: string; reason: string }[];
	errors: { id: string; reason: string; column?: string }[];
};
