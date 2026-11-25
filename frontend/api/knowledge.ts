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
	status: 'draft' | 'published' | 'archived' | string;
	version: string;
	created: string | null;
	modified: string | null;
	created_by: string | null;
	modified_by: string | null;
	concept_count: number;
	relation_count: number;
	fact_count: number;
	document_count: number;
	data_link_count: number;
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

export type KnowledgeDataTarget = {
	kind: 'term' | 'table' | string;
	id: string;
	name: string;
	detail: string | null;
};

type Single<T> = ResponseWithError<{ data: T }>;
type List<T> = ResponseWithError<{ data: T[]; count: number }>;

export const knowledgeApi = {
	listNetworks: (): List<KnowledgeNetwork> => requests.get(`knowledge/networks`),
	getNetwork: (id: string): Single<KnowledgeNetwork> =>
		requests.get(`knowledge/networks/${encodeURIComponent(id)}`),
	createNetwork: (payload: {
		name: string;
		description?: string;
		domain?: string;
	}): Single<KnowledgeNetwork> => requests.post(`knowledge/networks`, payload),
	updateNetwork: (
		id: string,
		payload: Partial<
			Pick<KnowledgeNetwork, 'name' | 'description' | 'domain' | 'status' | 'version'>
		>,
	): Single<KnowledgeNetwork> =>
		requests.patch(`knowledge/networks/${encodeURIComponent(id)}`, payload),
	deleteNetwork: (id: string): Single<{ id: string }> =>
		requests.delete(`knowledge/networks/${encodeURIComponent(id)}`),

	listDocuments: (networkId: string): List<KnowledgeDocument> =>
		requests.get(`knowledge/networks/${encodeURIComponent(networkId)}/documents`),
	addDocument: (networkId: string, runId: string): Single<KnowledgeDocument> =>
		requests.post(`knowledge/networks/${encodeURIComponent(networkId)}/documents`, {
			run_id: runId,
		}),
	reextractDocument: (documentId: string): Single<KnowledgeDocument> =>
		requests.post(`knowledge/documents/${encodeURIComponent(documentId)}/extract`),
	deleteDocument: (documentId: string): Single<{ id: string }> =>
		requests.delete(`knowledge/documents/${encodeURIComponent(documentId)}`),

	listConcepts: (networkId: string): List<KnowledgeConcept> =>
		requests.get(`knowledge/networks/${encodeURIComponent(networkId)}/concepts`),
	updateConcept: (
		conceptId: string,
		payload: Partial<
			Pick<
				KnowledgeConcept,
				'name' | 'description' | 'kind' | 'status' | 'aliases' | 'attributes' | 'confidence'
			>
		>,
	): Single<KnowledgeConcept> =>
		requests.patch(`knowledge/concepts/${encodeURIComponent(conceptId)}`, payload),
	deleteConcept: (conceptId: string): Single<{ id: string }> =>
		requests.delete(`knowledge/concepts/${encodeURIComponent(conceptId)}`),

	listRelations: (networkId: string): List<KnowledgeRelation> =>
		requests.get(`knowledge/networks/${encodeURIComponent(networkId)}/relations`),
	updateRelation: (
		relationId: string,
		payload: Partial<
			Pick<KnowledgeRelation, 'name' | 'description' | 'kind' | 'status' | 'confidence'>
		>,
	): Single<KnowledgeRelation> =>
		requests.patch(`knowledge/relations/${encodeURIComponent(relationId)}`, payload),
	deleteRelation: (relationId: string): Single<{ id: string }> =>
		requests.delete(`knowledge/relations/${encodeURIComponent(relationId)}`),

	listFacts: (networkId: string): List<KnowledgeFact> =>
		requests.get(`knowledge/networks/${encodeURIComponent(networkId)}/facts`),
	updateFact: (
		factId: string,
		payload: Partial<Pick<KnowledgeFact, 'predicate' | 'statement' | 'status' | 'confidence'>>,
	): Single<KnowledgeFact> =>
		requests.patch(`knowledge/facts/${encodeURIComponent(factId)}`, payload),
	deleteFact: (factId: string): Single<{ id: string }> =>
		requests.delete(`knowledge/facts/${encodeURIComponent(factId)}`),

	graph: (networkId: string): Single<KnowledgeGraph> =>
		requests.get(`knowledge/networks/${encodeURIComponent(networkId)}/graph`),
	dataTargets: (q: string): List<KnowledgeDataTarget> =>
		requests.get(`knowledge/data-targets`, { q }),
	linkConcept: (
		conceptId: string,
		payload: { target_kind: 'term' | 'table'; target_id: string; note?: string },
	): Single<KnowledgeDataLink> =>
		requests.post(`knowledge/concepts/${encodeURIComponent(conceptId)}/links`, payload),
	unlinkConcept: (linkId: string): Single<{ id: string }> =>
		requests.delete(`knowledge/links/${encodeURIComponent(linkId)}`),

	exportUrl: (networkId: string): string =>
		`/api/knowledge/networks/${encodeURIComponent(networkId)}/export`,
};
