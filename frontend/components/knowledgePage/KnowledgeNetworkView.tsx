// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import {
	knowledgeApi,
	type KnowledgeConcept,
	type KnowledgeDataTarget,
	type KnowledgeDocument,
	type KnowledgeFact,
	type KnowledgeGraph as KnowledgeGraphData,
	type KnowledgeNetwork,
	type KnowledgeRelation,
} from '@/api/knowledge';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

import { KnowledgeDocumentModal } from './KnowledgeDocumentModal';
import { KnowledgeGraph } from './KnowledgeGraph';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

const cardClassName =
	'rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900';

type Tab = 'overview' | 'concepts' | 'relations' | 'facts' | 'documents' | 'graph';

const statusClass = (status: string): string => {
	if (status === 'certified') return 'bg-emerald-100 text-emerald-700';
	if (status === 'reviewed') return 'bg-sky-100 text-sky-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'extracting' || status === 'queued')
		return 'bg-[#76b900]/15 text-[#4b7a00]';
	if (status === 'published') return 'bg-emerald-100 text-emerald-700';
	return 'bg-zinc-100 text-zinc-600';
};

const statusLabel = (status: string): string => t(status);

const StatusSelect = ({
	value,
	onChange,
}: {
	value: string;
	onChange: (value: string) => void;
}) => (
	<select
		value={value}
		onChange={(event) => onChange(event.target.value)}
		className="h-7 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
	>
		<option value="draft">{t('draft')}</option>
		<option value="reviewed">{t('reviewed')}</option>
		<option value="certified">{t('certified')}</option>
	</select>
);

const EvidenceList = ({
	evidence,
}: {
	evidence: Array<{ page: number | null; block_index: number | null; quote: string }>;
}) => {
	if (evidence.length === 0) {
		return <p className="text-xs text-secondary">{t('No evidence quote stored.')}</p>;
	}
	return (
		<ul className="space-y-2">
			{evidence.map((item, index) => (
				<li
					key={`${item.page}-${item.block_index}-${index}`}
					className="rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-2 text-xs leading-5 text-body dark:border-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-300"
				>
					<div className="mb-1 text-[10px] font-medium tracking-wide text-secondary uppercase">
						{item.page != null ? t('Page {page}', { page: item.page }) : t('Page unknown')}
						{item.block_index != null
							? ` · ${t('block {index}', { index: item.block_index })}`
							: ''}
					</div>
					“{item.quote}”
				</li>
			))}
		</ul>
	);
};

const LinkManager = ({
	concept,
	onChanged,
}: {
	concept: KnowledgeConcept;
	onChanged: () => void;
}) => {
	const [query, setQuery] = useState('');
	const [targets, setTargets] = useState<KnowledgeDataTarget[]>([]);
	const [searching, setSearching] = useState(false);
	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	const search = useCallback(async () => {
		setSearching(true);
		setError(null);
		const response = await knowledgeApi.dataTargets(query);
		setSearching(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to search data objects.'));
			return;
		}
		setTargets(response.data.data);
	}, [query]);

	const link = async (target: KnowledgeDataTarget) => {
		setBusy(target.id);
		setError(null);
		const response = await knowledgeApi.linkConcept(concept.id, {
			target_kind: target.kind as 'term' | 'table',
			target_id: target.id,
		});
		setBusy(null);
		if (response.error) {
			setError(response.message ?? t('Failed to link the data object.'));
			return;
		}
		setTargets((current) => current.filter((item) => item.id !== target.id));
		onChanged();
	};

	const unlink = async (linkId: string) => {
		setBusy(linkId);
		const response = await knowledgeApi.unlinkConcept(linkId);
		setBusy(null);
		if (response.error) {
			setError(response.message ?? t('Failed to remove the link.'));
			return;
		}
		onChanged();
	};

	return (
		<div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
			<div className="flex items-center justify-between gap-3">
				<h4 className="text-xs font-semibold tracking-wide text-secondary uppercase">
					{t('Data ontology links')}
				</h4>
				<Link
					href="/terms"
					className="text-xs text-[#5e9400] hover:underline"
				>
					{t('Open terms')}
				</Link>
			</div>
			<div className="mt-3 flex flex-wrap gap-2">
				{concept.data_links.length === 0 && (
					<span className="text-xs text-secondary">{t('Not linked yet.')}</span>
				)}
				{concept.data_links.map((linkItem) => (
					<span
						key={linkItem.id}
						className="inline-flex items-center gap-1 rounded-full border border-[#76b900]/40 bg-[#76b900]/10 px-2.5 py-1 text-xs text-[#4b7a00]"
						title={linkItem.detail || undefined}
					>
						{linkItem.kind === 'term' ? t('Term') : t('Table')} · {linkItem.name}
						<button
							type="button"
							className="ml-1 text-[#4b7a00] hover:text-red-600"
							onClick={() => unlink(linkItem.id)}
							disabled={busy != null}
							aria-label={t('Remove link to {name}', { name: linkItem.name })}
						>
							<Icon name={IconName.Close} className="h-3 w-3" />
						</button>
					</span>
				))}
			</div>
			<div className="mt-3 flex gap-2">
				<input
					className={inputClassName}
					value={query}
					onChange={(event) => setQuery(event.target.value)}
					onKeyDown={(event) => {
						if (event.key === 'Enter') search();
					}}
					placeholder={t('Search a term or catalog table')}
				/>
				<Button theme={ButtonTheme.Secondary} size={Size.SMALL} onClick={search}>
					{t('Search')}
				</Button>
			</div>
			{searching && (
				<div className="mt-2 flex justify-center py-2">
					<Spinner />
				</div>
			)}
			{error && <p className="mt-2 text-xs text-red-600">{error}</p>}
			{targets.length > 0 && (
				<div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
					{targets.map((target) => (
						<button
							key={`${target.kind}:${target.id}`}
							type="button"
							className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800"
							onClick={() => link(target)}
							disabled={busy != null}
						>
							<span className="min-w-0">
								<span className="font-medium text-heading dark:text-zinc-100">
									{target.name}
								</span>
								<span className="ml-2 text-secondary">
									{target.kind === 'term' ? t('Term') : t('Table')} · {target.detail}
								</span>
							</span>
							{busy === target.id ? (
								<Spinner />
							) : (
								<Icon name={IconName.Plus} className="h-3.5 w-3.5 text-[#76b900]" />
							)}
						</button>
					))}
				</div>
			)}
		</div>
	);
};

const ConceptCard = ({
	concept,
	expanded,
	onToggle,
	onStatus,
	onChanged,
}: {
	concept: KnowledgeConcept;
	expanded: boolean;
	onToggle: () => void;
	onStatus: (status: string) => void;
	onChanged: () => void;
}) => (
	<div className={cardClassName}>
		<div className="flex items-start justify-between gap-3">
			<button type="button" className="min-w-0 flex-1 text-left" onClick={onToggle}>
				<div className="flex flex-wrap items-center gap-2">
					<h3 className="truncate text-sm font-semibold text-heading dark:text-zinc-100">
						{concept.name}
					</h3>
					<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-secondary dark:bg-zinc-800">
						{t(concept.kind)}
					</span>
					<span className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(concept.status)}`}>
						{statusLabel(concept.status)}
					</span>
					<span className="text-[10px] text-secondary">
						{Math.round(concept.confidence * 100)}%
					</span>
				</div>
				<p className="mt-1 line-clamp-2 text-xs leading-5 text-secondary">
					{concept.description || t('No description yet.')}
				</p>
			</button>
			<StatusSelect value={concept.status} onChange={onStatus} />
		</div>
		<div className="mt-2 flex flex-wrap gap-3 text-[11px] text-secondary">
			<span>{t('{count} evidence', { count: concept.evidence_count })}</span>
			<span>{t('{count} data links', { count: concept.data_links.length })}</span>
			{concept.aliases.length > 0 && (
				<span>{t('Aliases: {names}', { names: concept.aliases.join('、') })}</span>
			)}
			<button
				type="button"
				className="text-[#5e9400] hover:underline"
				onClick={onToggle}
			>
				{expanded ? t('Hide details') : t('Show details')}
			</button>
		</div>
		{expanded && (
			<div className="mt-4 space-y-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
				{concept.attributes.length > 0 && (
					<div>
						<h4 className="mb-2 text-xs font-semibold tracking-wide text-secondary uppercase">
							{t('Attributes')}
						</h4>
						<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
							{concept.attributes.map((attribute) => (
								<div
									key={attribute.name}
									className="rounded-lg border border-zinc-200 px-3 py-2 text-xs dark:border-zinc-700"
								>
									<div className="font-medium text-heading dark:text-zinc-100">
										{attribute.display_name || attribute.name}
									</div>
									<div className="mt-0.5 text-secondary">
										{[attribute.value, attribute.description]
											.filter(Boolean)
											.join(' · ') || t('No value')}
									</div>
								</div>
							))}
						</div>
					</div>
				)}
				<div>
					<h4 className="mb-2 text-xs font-semibold tracking-wide text-secondary uppercase">
						{t('Evidence')}
					</h4>
					<EvidenceList evidence={concept.evidence} />
				</div>
				<LinkManager concept={concept} onChanged={onChanged} />
			</div>
		)}
	</div>
);

const RelationRow = ({
	relation,
	onStatus,
}: {
	relation: KnowledgeRelation;
	onStatus: (status: string) => void;
}) => (
	<div className={cardClassName}>
		<div className="flex flex-wrap items-start justify-between gap-3">
			<div className="min-w-0">
				<div className="flex flex-wrap items-center gap-2 text-sm">
					<span className="font-medium text-heading dark:text-zinc-100">
						{relation.source_name}
					</span>
					<span className="rounded-full bg-[#76b900]/15 px-2 py-0.5 text-xs font-medium text-[#4b7a00]">
						{relation.name}
					</span>
					<span className="font-medium text-heading dark:text-zinc-100">
						{relation.target_name}
					</span>
					<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-secondary dark:bg-zinc-800">
						{t(relation.kind)}
					</span>
				</div>
				<p className="mt-1 text-xs text-secondary">
					{relation.description || t('No description yet.')}
				</p>
			</div>
			<div className="flex items-center gap-2">
				<span className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(relation.status)}`}>
					{statusLabel(relation.status)}
				</span>
				<StatusSelect value={relation.status} onChange={onStatus} />
			</div>
		</div>
		{relation.evidence.length > 0 && (
			<div className="mt-3">
				<EvidenceList evidence={relation.evidence} />
			</div>
		)}
	</div>
);

const FactCard = ({
	fact,
	onStatus,
}: {
	fact: KnowledgeFact;
	onStatus: (status: string) => void;
}) => (
	<div className={cardClassName}>
		<div className="flex items-start justify-between gap-3">
			<div className="min-w-0">
				<p className="text-sm leading-6 text-heading dark:text-zinc-100">{fact.statement}</p>
				<div className="mt-1 flex flex-wrap gap-2 text-[11px] text-secondary">
					<span>{t('Subject')}: {fact.subject_name}</span>
					<span>{t('Predicate')}: {fact.predicate}</span>
					<span>
						{t('Object')}: {fact.object_name || fact.object_text || '—'}
					</span>
					<span>{Math.round(fact.confidence * 100)}%</span>
				</div>
			</div>
			<div className="flex items-center gap-2">
				<span className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(fact.status)}`}>
					{statusLabel(fact.status)}
				</span>
				<StatusSelect value={fact.status} onChange={onStatus} />
			</div>
		</div>
		<div className="mt-3">
			<EvidenceList evidence={fact.evidence} />
		</div>
	</div>
);

export const KnowledgeNetworkView = ({ networkId }: { networkId: string }) => {
	const router = useRouter();
	const [network, setNetwork] = useState<KnowledgeNetwork | null>(null);
	const [concepts, setConcepts] = useState<KnowledgeConcept[]>([]);
	const [relations, setRelations] = useState<KnowledgeRelation[]>([]);
	const [facts, setFacts] = useState<KnowledgeFact[]>([]);
	const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
	const [graph, setGraph] = useState<KnowledgeGraphData>({ nodes: [], edges: [] });
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<Tab>('overview');
	const [conceptQuery, setConceptQuery] = useState('');
	const [expandedConcept, setExpandedConcept] = useState<string | null>(null);
	const [showDocumentModal, setShowDocumentModal] = useState(false);
	const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);

	const loadAll = useCallback(async () => {
		const [networkResponse, conceptResponse, relationResponse, factResponse, documentResponse, graphResponse] =
			await Promise.all([
				knowledgeApi.getNetwork(networkId),
				knowledgeApi.listConcepts(networkId),
				knowledgeApi.listRelations(networkId),
				knowledgeApi.listFacts(networkId),
				knowledgeApi.listDocuments(networkId),
				knowledgeApi.graph(networkId),
			]);
		if (
			networkResponse.error ||
			!networkResponse.data ||
			conceptResponse.error ||
			!conceptResponse.data ||
			relationResponse.error ||
			!relationResponse.data ||
			factResponse.error ||
			!factResponse.data ||
			documentResponse.error ||
			!documentResponse.data ||
			graphResponse.error ||
			!graphResponse.data
		) {
			setError(
				networkResponse.message ??
					conceptResponse.message ??
					t('Failed to load the knowledge network.'),
			);
			return;
		}
		setError(null);
		setNetwork(networkResponse.data.data);
		setConcepts(conceptResponse.data.data);
		setRelations(relationResponse.data.data);
		setFacts(factResponse.data.data);
		setDocuments(documentResponse.data.data);
		setGraph(graphResponse.data.data);
	}, [networkId]);

	useEffect(() => {
		setLoading(true);
		loadAll().finally(() => setLoading(false));
	}, [loadAll]);

	const pendingDocuments = documents.some(
		(document) => document.status === 'queued' || document.status === 'extracting',
	);

	useEffect(() => {
		if (!pendingDocuments) return;
		const timer = window.setInterval(async () => {
			const response = await knowledgeApi.listDocuments(networkId);
			if (response.error || !response.data) return;
			setDocuments(response.data.data);
			if (
				!response.data.data.some(
					(document) =>
						document.status === 'queued' || document.status === 'extracting',
				)
			) {
				await loadAll();
			}
		}, 3000);
		return () => window.clearInterval(timer);
	}, [pendingDocuments, networkId, loadAll]);

	useEffect(() => {
		if (!toast) return;
		const timer = window.setTimeout(() => setToast(null), 3200);
		return () => window.clearTimeout(timer);
	}, [toast]);

	const setConceptStatus = async (concept: KnowledgeConcept, status: string) => {
		const response = await knowledgeApi.updateConcept(concept.id, { status });
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to update the concept.'), error: true });
			return;
		}
		setConcepts((current) =>
			current.map((item) => (item.id === concept.id ? { ...item, status } : item)),
		);
	};

	const setRelationStatus = async (relation: KnowledgeRelation, status: string) => {
		const response = await knowledgeApi.updateRelation(relation.id, { status });
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to update the relation.'), error: true });
			return;
		}
		setRelations((current) =>
			current.map((item) => (item.id === relation.id ? { ...item, status } : item)),
		);
	};

	const setFactStatus = async (fact: KnowledgeFact, status: string) => {
		const response = await knowledgeApi.updateFact(fact.id, { status });
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to update the fact.'), error: true });
			return;
		}
		setFacts((current) =>
			current.map((item) => (item.id === fact.id ? { ...item, status } : item)),
		);
	};

	const togglePublish = async () => {
		if (!network) return;
		const next = network.status === 'published' ? 'draft' : 'published';
		const response = await knowledgeApi.updateNetwork(network.id, { status: next });
		if (response.error || !response.data) {
			setToast({ message: response.message ?? t('Failed to update the network.'), error: true });
			return;
		}
		setNetwork(response.data.data);
		setToast({
			message:
				next === 'published'
					? t('Knowledge network published.')
					: t('Knowledge network moved back to draft.'),
		});
	};

	const reextract = async (document: KnowledgeDocument) => {
		const response = await knowledgeApi.reextractDocument(document.id);
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to start extraction.'), error: true });
			return;
		}
		setDocuments((current) =>
			current.map((item) =>
				item.id === document.id ? { ...item, status: 'queued', error_message: null } : item,
			),
		);
	};

	const removeDocument = async (document: KnowledgeDocument) => {
		if (!window.confirm(t('Remove {name} from this network?', { name: document.title || document.id })))
			return;
		const response = await knowledgeApi.deleteDocument(document.id);
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to remove the document.'), error: true });
			return;
		}
		setToast({ message: t('Document removed.') });
		await loadAll();
	};

	const removeNetwork = async () => {
		if (!network) return;
		if (
			!window.confirm(
				t('Delete the knowledge network “{name}” and all of its concepts?', {
					name: network.name,
				}),
			)
		)
			return;
		const response = await knowledgeApi.deleteNetwork(network.id);
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to delete the network.'), error: true });
			return;
		}
		router.push('/knowledge');
	};

	const filteredConcepts = useMemo(() => {
		const query = conceptQuery.trim().toLowerCase();
		if (!query) return concepts;
		return concepts.filter(
			(concept) =>
				concept.name.toLowerCase().includes(query) ||
				concept.description?.toLowerCase().includes(query) ||
				concept.aliases.some((alias) => alias.toLowerCase().includes(query)),
		);
	}, [conceptQuery, concepts]);

	const draftCount = concepts.filter((concept) => concept.status === 'draft').length;

	if (loading) {
		return (
			<div className="flex h-full items-center justify-center">
				<Spinner />
			</div>
		);
	}

	if (error || !network) {
		return (
			<div className="m-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
				{error || t('Knowledge network not found.')}
			</div>
		);
	}

	const tabs: Array<{ id: Tab; label: string; count?: number }> = [
		{ id: 'overview', label: t('Overview') },
		{ id: 'concepts', label: t('Concepts'), count: concepts.length },
		{ id: 'relations', label: t('Relations'), count: relations.length },
		{ id: 'facts', label: t('Facts'), count: facts.length },
		{ id: 'documents', label: t('Documents'), count: documents.length },
		{ id: 'graph', label: t('Graph') },
	];

	return (
		<div className="flex h-full w-full flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div className="min-w-0">
						<div className="flex flex-wrap items-center gap-2">
							<h1 className="truncate text-xl font-semibold tracking-tight text-heading dark:text-zinc-100">
								{network.name}
							</h1>
							<span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${statusClass(network.status)}`}>
								{statusLabel(network.status)}
							</span>
							<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-secondary dark:bg-zinc-800">
								{network.domain || t('No domain')}
							</span>
						</div>
						<p className="mt-1 max-w-3xl text-sm leading-6 text-secondary">
							{network.description || t('No description yet.')}
						</p>
						<p className="mt-2 text-xs text-secondary">
							{t('{documents} documents · {drafts} draft concepts · {links} data links', {
								documents: documents.length,
								drafts: draftCount,
								links: network.data_link_count,
							})}
						</p>
					</div>
					<div className="flex flex-wrap items-center gap-2">
						<Button onClick={() => setShowDocumentModal(true)}>
							<Icon name={IconName.Plus} className="mr-1.5 h-4 w-4" />
							{t('Add parsed document')}
						</Button>
						<a
							href={knowledgeApi.exportUrl(network.id)}
							className="inline-flex h-9 items-center rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-body no-underline transition-colors hover:border-[#76b900] hover:bg-[#76b900]/10 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						>
							<Icon name={IconName.Download} className="mr-1.5 h-4 w-4" />
							{t('Export BKN')}
						</a>
						<Button
							theme={ButtonTheme.Secondary}
							onClick={togglePublish}
						>
							{network.status === 'published' ? t('Back to draft') : t('Publish')}
						</Button>
					</div>
				</div>
			</header>

			<div className="border-b border-zinc-200 px-6 dark:border-zinc-800">
				<div className="flex gap-1 overflow-x-auto">
					{tabs.map((item) => (
						<button
							key={item.id}
							type="button"
							onClick={() => setTab(item.id)}
							className={`relative px-3 py-3 text-sm font-medium transition-colors ${
								tab === item.id
									? 'text-[#5e9400]'
									: 'text-secondary hover:text-heading dark:hover:text-zinc-100'
							}`}
						>
							{item.label}
							{item.count != null && (
								<span className="ml-1 text-[11px] text-secondary">{item.count}</span>
							)}
							{tab === item.id && (
								<span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-[#76b900]" />
							)}
						</button>
					))}
				</div>
			</div>

			<main className="flex-1 px-6 py-6">
				{tab === 'overview' && (
					<div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
						<section className={`${cardClassName} xl:col-span-2`}>
							<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
								{t('From documents to governed knowledge')}
							</h2>
							<ol className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
								{[
									[t('1. Parse'), t('Run OXR on a PDF or image and keep the Markdown and page blocks.')],
									[t('2. Extract'), t('The extractor proposes concepts, relations and facts with quotes.')],
									[t('3. Review'), t('Certify concepts, relations and facts; unsupported claims are dropped.')],
									[t('4. Connect'), t('Link concepts to glossary terms or catalog tables.')],
								].map(([title, description]) => (
									<li
										key={title}
										className="rounded-xl border border-zinc-200 bg-zinc-50/60 p-3 dark:border-zinc-700 dark:bg-zinc-800/40"
									>
										<div className="text-sm font-medium text-heading dark:text-zinc-100">
											{title}
										</div>
										<p className="mt-1 text-xs leading-5 text-secondary">{description}</p>
									</li>
								))}
							</ol>
							<div className="mt-4 rounded-xl border border-[#76b900]/30 bg-[#76b900]/5 p-3 text-xs leading-5 text-secondary">
								{t(
									'BKN export packages the same graph as object_types, relation_types and an evidence companion file, so bkn-foundry tools can consume it.',
								)}
							</div>
						</section>
						<section className={cardClassName}>
							<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
								{t('Network facts')}
							</h2>
							<dl className="mt-3 space-y-3">
								{[
									[t('Concepts'), network.concept_count],
									[t('Relations'), network.relation_count],
									[t('Facts'), network.fact_count],
									[t('Documents'), network.document_count],
									[t('Data links'), network.data_link_count],
								].map(([label, value]) => (
									<div
										key={String(label)}
										className="flex items-center justify-between border-b border-zinc-100 pb-2 text-sm last:border-0 dark:border-zinc-800"
									>
										<dt className="text-secondary">{label}</dt>
										<dd className="font-semibold text-heading dark:text-zinc-100">{value}</dd>
									</div>
								))}
							</dl>
							<Button
								theme={ButtonTheme.DangerSubtle}
								size={Size.SMALL}
								className="mt-4"
								onClick={removeNetwork}
							>
								{t('Delete network')}
							</Button>
						</section>
					</div>
				)}

				{tab === 'concepts' && (
					<div className="space-y-4">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<input
								className={`${inputClassName} max-w-md`}
								value={conceptQuery}
								onChange={(event) => setConceptQuery(event.target.value)}
								placeholder={t('Search concepts and aliases')}
							/>
							<p className="text-xs text-secondary">
								{t(
									'Certified concepts are the stable vocabulary agents should prefer.',
								)}
							</p>
						</div>
						{filteredConcepts.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No concepts yet. Add a parsed document to extract them.')}
							</div>
						) : (
							<div className="space-y-3">
								{filteredConcepts.map((concept) => (
									<ConceptCard
										key={concept.id}
										concept={concept}
										expanded={expandedConcept === concept.id}
										onToggle={() =>
											setExpandedConcept((current) =>
												current === concept.id ? null : concept.id,
											)
										}
										onStatus={(status) => setConceptStatus(concept, status)}
										onChanged={() => void loadAll()}
									/>
								))}
							</div>
						)}
					</div>
				)}

				{tab === 'relations' && (
					<div className="space-y-3">
						{relations.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No relations yet.')}
							</div>
						) : (
							relations.map((relation) => (
								<RelationRow
									key={relation.id}
									relation={relation}
									onStatus={(status) => setRelationStatus(relation, status)}
								/>
							))
						)}
					</div>
				)}

				{tab === 'facts' && (
					<div className="space-y-3">
						{facts.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No facts yet.')}
							</div>
						) : (
							facts.map((fact) => (
								<FactCard
									key={fact.id}
									fact={fact}
									onStatus={(status) => setFactStatus(fact, status)}
								/>
							))
						)}
					</div>
				)}

				{tab === 'documents' && (
					<div className="space-y-3">
						<div className="flex items-center justify-between">
							<p className="text-xs text-secondary">
								{t(
									'Re-extracting replaces this document’s claims and evidence; certified concepts from it stay.',
								)}
							</p>
							<Button size={Size.SMALL} onClick={() => setShowDocumentModal(true)}>
								{t('Add document')}
							</Button>
						</div>
						{documents.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No documents yet.')}
							</div>
						) : (
							documents.map((document) => (
								<div key={document.id} className={cardClassName}>
									<div className="flex flex-wrap items-start justify-between gap-3">
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<h3 className="truncate text-sm font-semibold text-heading dark:text-zinc-100">
													{document.title || document.id}
												</h3>
												<span
													className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(document.status)}`}
												>
													{statusLabel(document.status)}
												</span>
												<span className="text-[11px] text-secondary">
													{document.chunk_count ?? 0} {t('chunks')}
												</span>
											</div>
											<p className="mt-1 line-clamp-2 text-xs leading-5 text-secondary">
												{document.summary || document.error_message || t('Not extracted yet.')}
											</p>
											<div className="mt-1 flex flex-wrap gap-3 text-[11px] text-secondary">
												{document.source_name && <span>{document.source_name}</span>}
												{document.extracted_at && (
													<span>{new Date(document.extracted_at).toLocaleString()}</span>
												)}
											</div>
										</div>
										<div className="flex items-center gap-2">
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												onClick={() => reextract(document)}
												disabled={
													document.status === 'queued' ||
													document.status === 'extracting'
												}
											>
												{t('Re-extract')}
											</Button>
											<Button
												theme={ButtonTheme.DangerSubtle}
												size={Size.SMALL}
												onClick={() => removeDocument(document)}
											>
												{t('Remove')}
											</Button>
										</div>
									</div>
								</div>
							))
						)}
					</div>
				)}

				{tab === 'graph' && (
					<KnowledgeGraph
						graph={graph}
						onSelectConcept={(conceptId) => {
							setExpandedConcept(conceptId);
							setTab('concepts');
						}}
					/>
				)}
			</main>

			{showDocumentModal && (
				<KnowledgeDocumentModal
					networkId={network.id}
					onClose={() => setShowDocumentModal(false)}
					onAdded={() => {
						setShowDocumentModal(false);
						setTab('documents');
						void loadAll();
					}}
				/>
			)}

			{toast && (
				<div
					className={`fixed right-6 bottom-6 z-50 rounded-lg px-4 py-3 text-sm shadow-lg ${
						toast.error ? 'bg-red-600 text-white' : 'bg-zinc-900 text-white'
					}`}
				>
					{toast.message}
				</div>
			)}
		</div>
	);
};
