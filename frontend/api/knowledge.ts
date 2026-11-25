// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ResponseWithError } from './types';

export type KnowledgeNetwork = {
	id: string;
	name: string;
	description: string | null;
	domain: string | null;
	zone_id: string | null;
	status: 'draft' | 'published' | 'archived' | string;
	version: string;
	created: string | null;
	modified: string | null;
	created_by: string | null;
	modified_by: string | null;
	concept_count: number;
	relation_count: number;
	fact_count: number;
	action_count: number;
	risk_count: number;
	metric_count: number;
	group_count: number;
	capability_count: number;
	document_count: number;
	data_link_count: number;
	permission?: 'read' | 'edit' | 'manage' | null;
};

export type KnowledgeDocument = {
	id: string;
	network_id: string;
	run_id: string | null;
	title: string | null;
	source_name: string | null;
	status: 'queued' | 'extracting' | 'extracted' | 'failed' | string;
	summary: string | null;
	error_message: string | null;
	chunk_count: number | null;
	created: string | null;
	created_by: string | null;
	extracted_at: string | null;
	run_status: string | null;
};

export type KnowledgeEvidence = {
	page: number | null;
	block_index: number | null;
	quote: string;
	document_id?: string;
};

export type KnowledgeDataLink = {
	id: string;
	kind: 'term' | 'table' | string;
	target_id: string;
	name: string;
	detail: string | null;
	confidence: number | null;
	note: string | null;
};

export type KnowledgeConcept = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	description: string | null;
	kind: string;
	aliases: string[];
	attributes: Array<{
		name: string;
		display_name?: string;
		type?: string;
		value?: string | null;
		description?: string;
	}>;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_document_id: string | null;
	created: string | null;
	modified: string | null;
	evidence_count: number;
	evidence: KnowledgeEvidence[];
	data_links: KnowledgeDataLink[];
};

export type KnowledgeRelation = {
	id: string;
	network_id: string;
	key: string;
	source_concept_id: string;
	target_concept_id: string;
	name: string;
	description: string | null;
	kind: string;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_key: string;
	source_name: string;
	target_key: string;
	target_name: string;
	evidence_count: number;
	evidence: KnowledgeEvidence[];
};

export type KnowledgeFact = {
	id: string;
	network_id: string;
	subject_concept_id: string;
	relation_id: string | null;
	object_concept_id: string | null;
	object_text: string | null;
	predicate: string;
	statement: string;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_document_id: string | null;
	subject_name: string;
	subject_key: string;
	object_name: string | null;
	object_key: string | null;
	evidence: KnowledgeEvidence[];
};

export type KnowledgeGraphNode = {
	id: string;
	kind: 'concept' | 'data' | string;
	label: string;
	detail: string | null;
	concept_kind: string | null;
	status: string | null;
	confidence: number | null;
};

export type KnowledgeGraphEdge = {
	id: string;
	source: string;
	target: string;
	kind: string;
	label: string | null;
	confidence: number | null;
};

export type KnowledgeGraph = {
	nodes: KnowledgeGraphNode[];
	edges: KnowledgeGraphEdge[];
};

export type KnowledgeGraphQuery = {
	start_concept_ids: string[];
	depth: number;
	direction: 'out' | 'in' | 'both';
	relation_kinds: string[];
	include_data_links: boolean;
};

export type KnowledgeGraphQueryResult = KnowledgeGraph & {
	seeds: string[];
	depth: number;
	direction: string;
};

export type KnowledgeDataTarget = {
	kind: 'term' | 'table' | string;
	id: string;
	name: string;
	detail: string | null;
};

export type KnowledgeAction = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	description: string | null;
	action_intent: string;
	bound_concept_id: string | null;
	bound_concept_name: string | null;
	bound_concept_key: string | null;
	parameters: Array<{ name?: string; type?: string; description?: string }>;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_document_id: string | null;
	evidence: KnowledgeEvidence[];
	capabilities: Array<{
		id: string;
		key: string;
		name: string;
		kind: string;
		config?: Record<string, unknown>;
	}>;
};

export type KnowledgeExecution = {
	id: string;
	network_id: string;
	action_id: string;
	status: string;
	parameters: Record<string, unknown>;
	plan: Record<string, unknown>;
	result: Record<string, unknown> | null;
	error_message: string | null;
	created: string | null;
	created_by: string | null;
	finished: string | null;
};

export type KnowledgeRisk = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	description: string | null;
	severity: string;
	mitigation: string | null;
	related_concept_id: string | null;
	related_concept_name: string | null;
	related_concept_key: string | null;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_document_id: string | null;
	evidence: KnowledgeEvidence[];
};

export type KnowledgeConceptGroup = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	description: string | null;
	concepts: Array<{ id: string; key: string; name: string }>;
	created: string | null;
	modified: string | null;
};

export type KnowledgeMetric = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	description: string | null;
	expression: string | null;
	unit: string | null;
	concept_id: string | null;
	concept_name: string | null;
	concept_key: string | null;
	sql_attribute_id: string | null;
	sql_attribute_name: string | null;
	sql_attribute_expression: string | null;
	status: 'draft' | 'reviewed' | 'certified' | string;
	confidence: number;
	source_document_id: string | null;
};

export type KnowledgeCapability = {
	id: string;
	network_id: string;
	key: string;
	name: string;
	kind: 'skill' | 'function' | 'mcp_tool' | 'knowledge_base' | string;
	description: string | null;
	config: Record<string, unknown>;
	enabled: boolean;
	created: string | null;
	modified: string | null;
};

export type KnowledgeVersion = {
	id: string;
	network_id: string;
	version: number;
	label: string | null;
	created: string | null;
	created_by: string | null;
};

export type KnowledgeVersionDiff = {
	version_id: string;
	version: number;
	label: string | null;
	network_changed: boolean;
	network_before: Record<string, unknown>;
	network_after: Record<string, unknown>;
	collections: Record<
		string,
		{
			before_count: number;
			after_count: number;
			added: Array<{ key: string; label: string }>;
			removed: Array<{ key: string; label: string }>;
			changed: Array<{
				key: string;
				label: string;
				fields: string[];
				before: Record<string, unknown>;
				after: Record<string, unknown>;
			}>;
		}
	>;
};

export type KnowledgeGrants = {
	user_ids: string[];
	dept_ids: string[];
	grants: Array<{
		id: string;
		user_id: string | null;
		dept_id: string | null;
		dept_name: string | null;
		permission: 'read' | 'edit' | 'manage' | string;
		expires_at: string | null;
	}>;
};

export type KnowledgeGrantAudit = {
	id: string;
	network_id: string;
	actor_user_id: string | null;
	action: string;
	before: Array<Record<string, unknown>>;
	after: Array<Record<string, unknown>>;
	created: string | null;
};

export type KnowledgeEvalCase = {
	id: string;
	network_id: string;
	question: string;
	expected_concepts: string[];
	expected_facts: string[];
	notes: string | null;
	created: string | null;
	modified: string | null;
};

export type KnowledgeEvalRun = {
	id: string;
	network_id: string;
	total: number;
	passed: number;
	details: Array<{
		case_id: string;
		question: string;
		passed: boolean;
		missing_concepts: string[];
		missing_facts: string[];
		context_chars: number;
	}>;
	created: string | null;
	created_by: string | null;
};

export type KnowledgeMetricValidation = {
	valid: boolean | null;
	mode: 'sql' | 'sql_syntax' | 'formula' | 'empty' | string;
	message: string;
	expression: string | null;
};

export type KnowledgeMetricPreview = {
	expression: string;
	sql: string;
	columns: string[];
	rows: Array<Record<string, unknown>>;
	row_count: number;
};

export type KnowledgeImportResult = {
	network_name: string | null;
	concept_count: number;
	relation_count: number;
	action_count: number;
	risk_count: number;
	group_count: number;
};

type Single<T> = Promise<ResponseWithError<{ data: T }>>;
type List<T> = Promise<ResponseWithError<{ data: T[]; count: number }>>;

export const knowledgeApi = {
	listNetworks: (): List<KnowledgeNetwork> =>
		requests.get<{ data: KnowledgeNetwork[]; count: number }>(`knowledge/networks`),
	getNetwork: (id: string): Single<KnowledgeNetwork> =>
		requests.get<{ data: KnowledgeNetwork }>(`knowledge/networks/${encodeURIComponent(id)}`),
	createNetwork: (payload: {
		name: string;
		description?: string;
		domain?: string;
		zone_id?: string;
	}): Single<KnowledgeNetwork> =>
		requests.post<{ data: KnowledgeNetwork }>(`knowledge/networks`, payload),
	updateNetwork: (
		id: string,
		payload: Partial<
			Pick<
				KnowledgeNetwork,
				'name' | 'description' | 'domain' | 'zone_id' | 'status' | 'version'
			>
		>,
	): Single<KnowledgeNetwork> =>
		requests.patch<{ data: KnowledgeNetwork }>(
			`knowledge/networks/${encodeURIComponent(id)}`,
			payload,
		),
	deleteNetwork: (id: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(`knowledge/networks/${encodeURIComponent(id)}`),

	listDocuments: (networkId: string): List<KnowledgeDocument> =>
		requests.get<{ data: KnowledgeDocument[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/documents`,
		),
	addDocument: (networkId: string, runId: string): Single<KnowledgeDocument> =>
		requests.post<{ data: KnowledgeDocument }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/documents`,
			{ run_id: runId },
		),
	reextractDocument: (documentId: string): Single<KnowledgeDocument> =>
		requests.post<{ data: KnowledgeDocument }>(
			`knowledge/documents/${encodeURIComponent(documentId)}/extract`,
		),
	deleteDocument: (documentId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/documents/${encodeURIComponent(documentId)}`,
		),

	listConcepts: (networkId: string): List<KnowledgeConcept> =>
		requests.get<{ data: KnowledgeConcept[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/concepts`,
		),
	updateConcept: (
		conceptId: string,
		payload: Partial<
			Pick<
				KnowledgeConcept,
				'name' | 'description' | 'kind' | 'status' | 'aliases' | 'attributes' | 'confidence'
			>
		>,
	): Single<KnowledgeConcept> =>
		requests.patch<{ data: KnowledgeConcept }>(
			`knowledge/concepts/${encodeURIComponent(conceptId)}`,
			payload,
		),
	deleteConcept: (conceptId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/concepts/${encodeURIComponent(conceptId)}`,
		),

	listRelations: (networkId: string): List<KnowledgeRelation> =>
		requests.get<{ data: KnowledgeRelation[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/relations`,
		),
	updateRelation: (
		relationId: string,
		payload: Partial<
			Pick<KnowledgeRelation, 'name' | 'description' | 'kind' | 'status' | 'confidence'>
		>,
	): Single<KnowledgeRelation> =>
		requests.patch<{ data: KnowledgeRelation }>(
			`knowledge/relations/${encodeURIComponent(relationId)}`,
			payload,
		),
	deleteRelation: (relationId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/relations/${encodeURIComponent(relationId)}`,
		),

	listFacts: (networkId: string): List<KnowledgeFact> =>
		requests.get<{ data: KnowledgeFact[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/facts`,
		),
	updateFact: (
		factId: string,
		payload: Partial<Pick<KnowledgeFact, 'predicate' | 'statement' | 'status' | 'confidence'>>,
	): Single<KnowledgeFact> =>
		requests.patch<{ data: KnowledgeFact }>(
			`knowledge/facts/${encodeURIComponent(factId)}`,
			payload,
		),
	deleteFact: (factId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(`knowledge/facts/${encodeURIComponent(factId)}`),

	graph: (networkId: string): Single<KnowledgeGraph> =>
		requests.get<{ data: KnowledgeGraph }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/graph`,
		),
	queryGraph: (
		networkId: string,
		payload: KnowledgeGraphQuery,
	): Single<KnowledgeGraphQueryResult> =>
		requests.post<{ data: KnowledgeGraphQueryResult }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/query`,
			payload,
		),

	listActions: (networkId: string): List<KnowledgeAction> =>
		requests.get<{ data: KnowledgeAction[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/actions`,
		),
	updateAction: (
		actionId: string,
		payload: Partial<
			Pick<
				KnowledgeAction,
				'name' | 'description' | 'action_intent' | 'status' | 'confidence'
			>
		>,
	): Single<KnowledgeAction> =>
		requests.patch<{ data: KnowledgeAction }>(
			`knowledge/actions/${encodeURIComponent(actionId)}`,
			payload,
		),
	deleteAction: (actionId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/actions/${encodeURIComponent(actionId)}`,
		),
	linkActionCapability: (
		actionId: string,
		capabilityId: string,
	): Single<Record<string, unknown>> =>
		requests.post<{ data: Record<string, unknown> }>(
			`knowledge/actions/${encodeURIComponent(actionId)}/capabilities`,
			{ capability_id: capabilityId },
		),
	unlinkActionCapability: (
		actionId: string,
		capabilityId: string,
	): Single<Record<string, unknown>> =>
		requests.delete<{ data: Record<string, unknown> }>(
			`knowledge/actions/${encodeURIComponent(actionId)}/capabilities/${encodeURIComponent(capabilityId)}`,
		),
	executeAction: (
		actionId: string,
		parameters: Record<string, unknown>,
		dryRun = true,
	): Single<KnowledgeExecution> =>
		requests.post<{ data: KnowledgeExecution }>(
			`knowledge/actions/${encodeURIComponent(actionId)}/execute`,
			{ parameters, dry_run: dryRun },
		),
	listExecutions: (networkId: string): List<KnowledgeExecution> =>
		requests.get<{ data: KnowledgeExecution[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/executions`,
		),

	listRisks: (networkId: string): List<KnowledgeRisk> =>
		requests.get<{ data: KnowledgeRisk[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/risks`,
		),
	updateRisk: (
		riskId: string,
		payload: Partial<
			Pick<KnowledgeRisk, 'name' | 'description' | 'severity' | 'status' | 'confidence'>
		>,
	): Single<KnowledgeRisk> =>
		requests.patch<{ data: KnowledgeRisk }>(
			`knowledge/risks/${encodeURIComponent(riskId)}`,
			payload,
		),
	deleteRisk: (riskId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(`knowledge/risks/${encodeURIComponent(riskId)}`),

	listConceptGroups: (networkId: string): List<KnowledgeConceptGroup> =>
		requests.get<{ data: KnowledgeConceptGroup[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/concept-groups`,
		),
	createConceptGroup: (
		networkId: string,
		payload: { name: string; description?: string; concept_ids: string[] },
	): Single<KnowledgeConceptGroup> =>
		requests.post<{ data: KnowledgeConceptGroup }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/concept-groups`,
			payload,
		),
	updateConceptGroup: (
		groupId: string,
		payload: { name?: string; description?: string | null },
	): Single<KnowledgeConceptGroup> =>
		requests.patch<{ data: KnowledgeConceptGroup }>(
			`knowledge/concept-groups/${encodeURIComponent(groupId)}`,
			payload,
		),
	deleteConceptGroup: (groupId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/concept-groups/${encodeURIComponent(groupId)}`,
		),

	listMetrics: (networkId: string): List<KnowledgeMetric> =>
		requests.get<{ data: KnowledgeMetric[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/metrics`,
		),
	createMetric: (
		networkId: string,
		payload: {
			name: string;
			description?: string;
			expression?: string;
			unit?: string;
			concept_id?: string;
		},
	): Single<KnowledgeMetric> =>
		requests.post<{ data: KnowledgeMetric }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/metrics`,
			payload,
		),
	updateMetric: (
		metricId: string,
		payload: Partial<
			Pick<
				KnowledgeMetric,
				'name' | 'description' | 'expression' | 'unit' | 'status' | 'confidence'
			>
		>,
	): Single<KnowledgeMetric> =>
		requests.patch<{ data: KnowledgeMetric }>(
			`knowledge/metrics/${encodeURIComponent(metricId)}`,
			payload,
		),
	deleteMetric: (metricId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/metrics/${encodeURIComponent(metricId)}`,
		),
	validateMetric: (metricId: string): Single<KnowledgeMetricValidation> =>
		requests.post<{ data: KnowledgeMetricValidation }>(
			`knowledge/metrics/${encodeURIComponent(metricId)}/validate`,
		),
	previewMetric: (metricId: string): Single<KnowledgeMetricPreview> =>
		requests.post<{ data: KnowledgeMetricPreview }>(
			`knowledge/metrics/${encodeURIComponent(metricId)}/preview`,
		),

	listCapabilities: (networkId: string): List<KnowledgeCapability> =>
		requests.get<{ data: KnowledgeCapability[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/capabilities`,
		),
	createCapability: (
		networkId: string,
		payload: {
			name: string;
			kind: KnowledgeCapability['kind'];
			description?: string;
			config?: Record<string, unknown>;
		},
	): Single<KnowledgeCapability> =>
		requests.post<{ data: KnowledgeCapability }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/capabilities`,
			payload,
		),
	updateCapability: (
		capabilityId: string,
		payload: Partial<Pick<KnowledgeCapability, 'name' | 'description' | 'enabled' | 'config'>>,
	): Single<KnowledgeCapability> =>
		requests.patch<{ data: KnowledgeCapability }>(
			`knowledge/capabilities/${encodeURIComponent(capabilityId)}`,
			payload,
		),
	deleteCapability: (capabilityId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/capabilities/${encodeURIComponent(capabilityId)}`,
		),

	listVersions: (networkId: string): List<KnowledgeVersion> =>
		requests.get<{ data: KnowledgeVersion[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/versions`,
		),
	createVersion: (networkId: string, label?: string): Single<KnowledgeVersion> =>
		requests.post<{ data: KnowledgeVersion }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/versions`,
			{ label },
		),
	restoreVersion: (versionId: string): Single<Record<string, unknown>> =>
		requests.post<{ data: Record<string, unknown> }>(
			`knowledge/versions/${encodeURIComponent(versionId)}/restore`,
		),
	diffVersion: (versionId: string): Single<KnowledgeVersionDiff> =>
		requests.get<{ data: KnowledgeVersionDiff }>(
			`knowledge/versions/${encodeURIComponent(versionId)}/diff`,
		),

	listEvalCases: (networkId: string): List<KnowledgeEvalCase> =>
		requests.get<{ data: KnowledgeEvalCase[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/eval-cases`,
		),
	createEvalCase: (
		networkId: string,
		payload: {
			question: string;
			expected_concepts: string[];
			expected_facts: string[];
			notes?: string;
		},
	): Single<KnowledgeEvalCase> =>
		requests.post<{ data: KnowledgeEvalCase }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/eval-cases`,
			payload,
		),
	deleteEvalCase: (caseId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(
			`knowledge/eval-cases/${encodeURIComponent(caseId)}`,
		),
	listEvalRuns: (networkId: string): List<KnowledgeEvalRun> =>
		requests.get<{ data: KnowledgeEvalRun[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/eval-runs`,
		),
	runEvals: (networkId: string): Single<KnowledgeEvalRun> =>
		requests.post<{ data: KnowledgeEvalRun }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/eval-runs`,
		),
	getGrants: (networkId: string): Single<KnowledgeGrants> =>
		requests.get<{ data: KnowledgeGrants }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/grants`,
		),
	replaceGrants: (
		networkId: string,
		payload: {
			grants: Array<{
				subject_type: 'user' | 'department';
				subject_id: string;
				permission: 'read' | 'edit' | 'manage';
				expires_at?: string | null;
			}>;
		},
	): Single<KnowledgeGrants> =>
		requests.put<{ data: KnowledgeGrants }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/grants`,
			payload,
		),
	listGrantAudit: (networkId: string): List<KnowledgeGrantAudit> =>
		requests.get<{ data: KnowledgeGrantAudit[]; count: number }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/grant-audit`,
		),
	dataTargets: (q: string): List<KnowledgeDataTarget> =>
		requests.get<{ data: KnowledgeDataTarget[]; count: number }>(`knowledge/data-targets`, {
			q,
		}),
	linkConcept: (
		conceptId: string,
		payload: { target_kind: 'term' | 'table'; target_id: string; note?: string },
	): Single<KnowledgeDataLink> =>
		requests.post<{ data: KnowledgeDataLink }>(
			`knowledge/concepts/${encodeURIComponent(conceptId)}/links`,
			payload,
		),
	unlinkConcept: (linkId: string): Single<{ id: string }> =>
		requests.delete<{ data: { id: string } }>(`knowledge/links/${encodeURIComponent(linkId)}`),

	exportUrl: (networkId: string): string =>
		`/api/knowledge/networks/${encodeURIComponent(networkId)}/export`,

	importBkn: (networkId: string, file: File): Single<KnowledgeImportResult> => {
		const form = new FormData();
		form.append('file', file);
		return requests.postForm<{ data: KnowledgeImportResult }>(
			`knowledge/networks/${encodeURIComponent(networkId)}/import`,
			form,
		);
	},
};
