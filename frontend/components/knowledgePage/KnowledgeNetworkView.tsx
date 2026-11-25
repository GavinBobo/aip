// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import {
	knowledgeApi,
	type KnowledgeAction,
	type KnowledgeCapability,
	type KnowledgeConcept,
	type KnowledgeConceptGroup,
	type KnowledgeDataTarget,
	type KnowledgeDocument,
	type KnowledgeEvalCase,
	type KnowledgeEvalRun,
	type KnowledgeFact,
	type KnowledgeGraph as KnowledgeGraphData,
	type KnowledgeMetric,
	type KnowledgeMetricPreview,
	type KnowledgeMetricValidation,
	type KnowledgeNetwork,
	type KnowledgeRelation,
	type KnowledgeRisk,
	type KnowledgeVersion,
	type KnowledgeVersionDiff,
} from '@/api/knowledge';
import { accessApi } from '@/api/access';
import { Button } from '@/common/Button';
import { formatDateTime } from '@/common/date';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

import { KnowledgeDocumentModal } from './KnowledgeDocumentModal';
import { KnowledgeCapabilityModal } from './KnowledgeCapabilityModal';
import { KnowledgeExecutionModal } from './KnowledgeExecutionModal';
import { KnowledgeGrantModal } from './KnowledgeGrantModal';
import { KnowledgeGraph } from './KnowledgeGraph';
import { KnowledgeGroupModal } from './KnowledgeGroupModal';
import { KnowledgeMetricModal } from './KnowledgeMetricModal';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

const cardClassName =
	'rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900';

type Tab =
	| 'overview'
	| 'concepts'
	| 'relations'
	| 'actions'
	| 'risks'
	| 'metrics'
	| 'groups'
	| 'capabilities'
	| 'versions'
	| 'evals'
	| 'facts'
	| 'documents'
	| 'graph';

const statusClass = (status: string): string => {
	if (status === 'certified') return 'bg-emerald-100 text-emerald-700';
	if (status === 'reviewed') return 'bg-sky-100 text-sky-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'extracting' || status === 'queued') return 'bg-[#76b900]/15 text-[#4b7a00]';
	if (status === 'published') return 'bg-emerald-100 text-emerald-700';
	return 'bg-zinc-100 text-zinc-600';
};

const statusLabel = (status: string): string => t(status);

/** Documents created without a usable file name share one sentinel title. */
const documentTitle = (document: { title?: string | null }): string =>
	!document.title || document.title === 'Untitled document'
		? t('Untitled document')
		: document.title;

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
	evidence: Array<{
		page: number | null;
		block_index: number | null;
		quote: string;
		image_path?: string | null;
		source_path?: string | null;
	}>;
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
						{item.page != null
							? t('Page {page}', { page: item.page })
							: t('Page unknown')}
						{item.block_index != null
							? ` · ${t('block {index}', { index: item.block_index })}`
							: ''}
					</div>
					“{item.quote}”
					{item.image_path ? (
						// eslint-disable-next-line @next/next/no-img-element -- runtime parse assets, not build-time images
						<img
							src={item.image_path}
							alt={t('Evidence image')}
							className="mt-2 max-h-56 w-auto rounded-md border border-zinc-200 object-contain dark:border-zinc-700"
						/>
					) : null}
					{item.source_path ? (
						<div className="mt-1 truncate text-[10px] text-secondary">
							{item.source_path}
						</div>
					) : null}
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
		setTargets(response.data);
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
				<Link href="/terms" className="text-xs text-[#5e9400] hover:underline">
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
									{target.kind === 'term' ? t('Term') : t('Table')}
									{target.detail ? ` · ${target.detail}` : ''}
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
					<span
						className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(concept.status)}`}
					>
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
			<button type="button" className="text-[#5e9400] hover:underline" onClick={onToggle}>
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
				<span
					className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(relation.status)}`}
				>
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
				<p className="text-sm leading-6 text-heading dark:text-zinc-100">
					{fact.statement}
				</p>
				<div className="mt-1 flex flex-wrap gap-2 text-[11px] text-secondary">
					<span>
						{t('Subject')}: {fact.subject_name}
					</span>
					<span>
						{t('Predicate')}: {fact.predicate}
					</span>
					<span>
						{t('Object')}: {fact.object_name || fact.object_text || '—'}
					</span>
					<span>{Math.round(fact.confidence * 100)}%</span>
				</div>
			</div>
			<div className="flex items-center gap-2">
				<span
					className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(fact.status)}`}
				>
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
	const [actions, setActions] = useState<KnowledgeAction[]>([]);
	const [risks, setRisks] = useState<KnowledgeRisk[]>([]);
	const [metrics, setMetrics] = useState<KnowledgeMetric[]>([]);
	const [metricValidations, setMetricValidations] = useState<
		Record<string, KnowledgeMetricValidation>
	>({});
	const [metricPreviews, setMetricPreviews] = useState<Record<string, KnowledgeMetricPreview>>(
		{},
	);
	const [groups, setGroups] = useState<KnowledgeConceptGroup[]>([]);
	const [capabilities, setCapabilities] = useState<KnowledgeCapability[]>([]);
	const [versions, setVersions] = useState<KnowledgeVersion[]>([]);
	const [versionDiffs, setVersionDiffs] = useState<Record<string, KnowledgeVersionDiff>>({});
	const [versionLabel, setVersionLabel] = useState('');
	const [evalCases, setEvalCases] = useState<KnowledgeEvalCase[]>([]);
	const [evalRuns, setEvalRuns] = useState<KnowledgeEvalRun[]>([]);
	const [evalQuestion, setEvalQuestion] = useState('');
	const [evalConcepts, setEvalConcepts] = useState('');
	const [evalFacts, setEvalFacts] = useState('');
	const [graphSeed, setGraphSeed] = useState('');
	const [graphDepth, setGraphDepth] = useState(2);
	const [graphDirection, setGraphDirection] = useState<'out' | 'in' | 'both'>('both');
	const [graphIncludeData, setGraphIncludeData] = useState(false);
	const [facts, setFacts] = useState<KnowledgeFact[]>([]);
	const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
	const [graph, setGraph] = useState<KnowledgeGraphData>({ nodes: [], edges: [] });
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<Tab>('overview');
	const [conceptQuery, setConceptQuery] = useState('');
	const [expandedConcept, setExpandedConcept] = useState<string | null>(null);
	const [showDocumentModal, setShowDocumentModal] = useState(false);
	const [showGroupModal, setShowGroupModal] = useState(false);
	const [showMetricModal, setShowMetricModal] = useState(false);
	const [showCapabilityModal, setShowCapabilityModal] = useState(false);
	const [executionAction, setExecutionAction] = useState<KnowledgeAction | null>(null);
	const [isAdmin, setIsAdmin] = useState(false);
	const [showGrantModal, setShowGrantModal] = useState(false);
	const [importing, setImporting] = useState(false);
	const importInputRef = useRef<HTMLInputElement>(null);
	const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);

	const loadAll = useCallback(async () => {
		const [
			networkResponse,
			conceptResponse,
			relationResponse,
			factResponse,
			actionResponse,
			riskResponse,
			metricResponse,
			groupResponse,
			capabilityResponse,
			versionResponse,
			evalCaseResponse,
			evalRunResponse,
			documentResponse,
			graphResponse,
		] = await Promise.all([
			knowledgeApi.getNetwork(networkId),
			knowledgeApi.listConcepts(networkId),
			knowledgeApi.listRelations(networkId),
			knowledgeApi.listFacts(networkId),
			knowledgeApi.listActions(networkId),
			knowledgeApi.listRisks(networkId),
			knowledgeApi.listMetrics(networkId),
			knowledgeApi.listConceptGroups(networkId),
			knowledgeApi.listCapabilities(networkId),
			knowledgeApi.listVersions(networkId),
			knowledgeApi.listEvalCases(networkId),
			knowledgeApi.listEvalRuns(networkId),
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
			actionResponse.error ||
			!actionResponse.data ||
			riskResponse.error ||
			!riskResponse.data ||
			metricResponse.error ||
			!metricResponse.data ||
			groupResponse.error ||
			!groupResponse.data ||
			capabilityResponse.error ||
			!capabilityResponse.data ||
			versionResponse.error ||
			!versionResponse.data ||
			evalCaseResponse.error ||
			!evalCaseResponse.data ||
			evalRunResponse.error ||
			!evalRunResponse.data ||
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
		setNetwork(networkResponse.data);
		setConcepts(conceptResponse.data);
		setRelations(relationResponse.data);
		setFacts(factResponse.data);
		setActions(actionResponse.data);
		setRisks(riskResponse.data);
		setMetrics(metricResponse.data);
		setGroups(groupResponse.data);
		setCapabilities(capabilityResponse.data);
		setVersions(versionResponse.data);
		setEvalCases(evalCaseResponse.data);
		setEvalRuns(evalRunResponse.data);
		setDocuments(documentResponse.data);
		setGraph(graphResponse.data);
	}, [networkId]);

	useEffect(() => {
		let cancelled = false;
		accessApi.me().then((response) => {
			if (!cancelled && !response.error && response.data) {
				setIsAdmin(response.data.is_admin);
			}
		});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		const timer = window.setTimeout(() => {
			void loadAll().finally(() => setLoading(false));
		}, 0);
		return () => window.clearTimeout(timer);
	}, [loadAll]);

	const pendingDocuments = documents.some(
		(document) => document.status === 'queued' || document.status === 'extracting',
	);

	useEffect(() => {
		if (!pendingDocuments) return;
		const timer = window.setInterval(async () => {
			const response = await knowledgeApi.listDocuments(networkId);
			if (response.error || !response.data) return;
			setDocuments(response.data);
			if (
				!response.data.some(
					(document) => document.status === 'queued' || document.status === 'extracting',
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
			setToast({
				message: response.message ?? t('Failed to update the concept.'),
				error: true,
			});
			return;
		}
		setConcepts((current) =>
			current.map((item) => (item.id === concept.id ? { ...item, status } : item)),
		);
	};

	const setRelationStatus = async (relation: KnowledgeRelation, status: string) => {
		const response = await knowledgeApi.updateRelation(relation.id, { status });
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to update the relation.'),
				error: true,
			});
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

	const setActionStatus = async (action: KnowledgeAction, status: string) => {
		const response = await knowledgeApi.updateAction(action.id, { status });
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to update the action.'),
				error: true,
			});
			return;
		}
		setActions((current) =>
			current.map((item) => (item.id === action.id ? { ...item, status } : item)),
		);
	};

	const mountActionCapability = async (action: KnowledgeAction, capabilityId: string) => {
		if (!capabilityId) return;
		const response = await knowledgeApi.linkActionCapability(action.id, capabilityId);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to mount the capability.'),
				error: true,
			});
			return;
		}
		await loadAll();
	};

	const unmountActionCapability = async (action: KnowledgeAction, capabilityId: string) => {
		const response = await knowledgeApi.unlinkActionCapability(action.id, capabilityId);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to unmount the capability.'),
				error: true,
			});
			return;
		}
		await loadAll();
	};

	const setRiskStatus = async (risk: KnowledgeRisk, status: string) => {
		const response = await knowledgeApi.updateRisk(risk.id, { status });
		if (response.error) {
			setToast({ message: response.message ?? t('Failed to update the risk.'), error: true });
			return;
		}
		setRisks((current) =>
			current.map((item) => (item.id === risk.id ? { ...item, status } : item)),
		);
	};

	const setMetricStatus = async (metric: KnowledgeMetric, status: string) => {
		const response = await knowledgeApi.updateMetric(metric.id, { status });
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to update the metric.'),
				error: true,
			});
			return;
		}
		setMetrics((current) =>
			current.map((item) => (item.id === metric.id ? { ...item, status } : item)),
		);
	};

	const removeMetric = async (metric: KnowledgeMetric) => {
		if (!window.confirm(t('Delete the metric “{name}”?', { name: metric.name }))) return;
		const response = await knowledgeApi.deleteMetric(metric.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to delete the metric.'),
				error: true,
			});
			return;
		}
		setMetrics((current) => current.filter((item) => item.id !== metric.id));
	};

	const removeCapability = async (capability: KnowledgeCapability) => {
		if (!window.confirm(t('Delete the capability “{name}”?', { name: capability.name })))
			return;
		const response = await knowledgeApi.deleteCapability(capability.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to delete the capability.'),
				error: true,
			});
			return;
		}
		setCapabilities((current) => current.filter((item) => item.id !== capability.id));
	};

	const createVersion = async () => {
		const response = await knowledgeApi.createVersion(
			networkId,
			versionLabel.trim() || undefined,
		);
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to create the version.'),
				error: true,
			});
			return;
		}
		setVersions((current) => [response.data, ...current]);
		setVersionLabel('');
		setToast({ message: t('Version {version} created.', { version: response.data.version }) });
	};

	const restoreVersion = async (version: KnowledgeVersion) => {
		if (
			!window.confirm(
				t('Restore version {version}? Current definitions will be replaced.', {
					version: version.version,
				}),
			)
		)
			return;
		const response = await knowledgeApi.restoreVersion(version.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to restore the version.'),
				error: true,
			});
			return;
		}
		setToast({ message: t('Version {version} restored.', { version: version.version }) });
		await loadAll();
	};

	const compareVersion = async (version: KnowledgeVersion) => {
		const response = await knowledgeApi.diffVersion(version.id);
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to compare the version.'),
				error: true,
			});
			return;
		}
		setVersionDiffs((current) => ({ ...current, [version.id]: response.data }));
	};

	const addEvalCase = async () => {
		if (!evalQuestion.trim()) return;
		const response = await knowledgeApi.createEvalCase(networkId, {
			question: evalQuestion.trim(),
			expected_concepts: evalConcepts
				.split(',')
				.map((item) => item.trim())
				.filter(Boolean),
			expected_facts: evalFacts
				.split(',')
				.map((item) => item.trim())
				.filter(Boolean),
		});
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to create the eval case.'),
				error: true,
			});
			return;
		}
		setEvalCases((current) => [response.data, ...current]);
		setEvalQuestion('');
		setEvalConcepts('');
		setEvalFacts('');
	};

	const removeEvalCase = async (item: KnowledgeEvalCase) => {
		const response = await knowledgeApi.deleteEvalCase(item.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to delete the eval case.'),
				error: true,
			});
			return;
		}
		setEvalCases((current) => current.filter((entry) => entry.id !== item.id));
	};

	const runEvals = async () => {
		const response = await knowledgeApi.runEvals(networkId);
		if (response.error || !response.data) {
			setToast({ message: response.message ?? t('Failed to run evals.'), error: true });
			return;
		}
		setEvalRuns((current) => [response.data, ...current]);
		setToast({
			message: t('Evals finished: {passed}/{total} passed.', {
				passed: response.data.passed,
				total: response.data.total,
			}),
		});
	};

	const applyGraphQuery = async () => {
		const response = await knowledgeApi.queryGraph(networkId, {
			start_concept_ids: graphSeed ? [graphSeed] : [],
			depth: graphDepth,
			direction: graphDirection,
			relation_kinds: [],
			include_data_links: graphIncludeData,
		});
		if (response.error || !response.data) {
			setToast({ message: response.message ?? t('Failed to query the graph.'), error: true });
			return;
		}
		setGraph({ nodes: response.data.nodes, edges: response.data.edges });
	};

	const resetGraphQuery = async () => {
		const response = await knowledgeApi.graph(networkId);
		if (!response.error && response.data) setGraph(response.data);
		setGraphSeed('');
	};

	const validateMetric = async (metric: KnowledgeMetric) => {
		const response = await knowledgeApi.validateMetric(metric.id);
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to validate the metric.'),
				error: true,
			});
			return;
		}
		setMetricValidations((current) => ({ ...current, [metric.id]: response.data }));
	};

	const previewMetric = async (metric: KnowledgeMetric) => {
		const response = await knowledgeApi.previewMetric(metric.id);
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to preview the metric.'),
				error: true,
			});
			return;
		}
		setMetricPreviews((current) => ({ ...current, [metric.id]: response.data }));
	};

	const removeGroup = async (group: KnowledgeConceptGroup) => {
		if (!window.confirm(t('Delete the concept group “{name}”?', { name: group.name }))) return;
		const response = await knowledgeApi.deleteConceptGroup(group.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to delete the concept group.'),
				error: true,
			});
			return;
		}
		setGroups((current) => current.filter((item) => item.id !== group.id));
	};

	const importBkn = async (file: File) => {
		if (importing) return;
		setImporting(true);
		const response = await knowledgeApi.importBkn(networkId, file);
		setImporting(false);
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to import the BKN package.'),
				error: true,
			});
			return;
		}
		const result = response.data;
		setToast({
			message: t(
				'Imported {concepts} concepts, {relations} relations, {actions} actions and {risks} risks.',
				{
					concepts: result.concept_count,
					relations: result.relation_count,
					actions: result.action_count,
					risks: result.risk_count,
				},
			),
		});
		await loadAll();
	};

	const togglePublish = async () => {
		if (!network) return;
		const next = network.status === 'published' ? 'draft' : 'published';
		const response = await knowledgeApi.updateNetwork(network.id, { status: next });
		if (response.error || !response.data) {
			setToast({
				message: response.message ?? t('Failed to update the network.'),
				error: true,
			});
			return;
		}
		setNetwork(response.data);
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
			setToast({
				message: response.message ?? t('Failed to start extraction.'),
				error: true,
			});
			return;
		}
		setDocuments((current) =>
			current.map((item) =>
				item.id === document.id ? { ...item, status: 'queued', error_message: null } : item,
			),
		);
	};

	const removeDocument = async (document: KnowledgeDocument) => {
		if (
			!window.confirm(
				t('Remove {name} from this network?', { name: documentTitle(document) }),
			)
		)
			return;
		const response = await knowledgeApi.deleteDocument(document.id);
		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to remove the document.'),
				error: true,
			});
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
			setToast({
				message: response.message ?? t('Failed to delete the network.'),
				error: true,
			});
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
		{ id: 'actions', label: t('Action types'), count: actions.length },
		{ id: 'risks', label: t('Risks'), count: risks.length },
		{ id: 'metrics', label: t('Metrics'), count: metrics.length },
		{ id: 'groups', label: t('Concept groups'), count: groups.length },
		{ id: 'capabilities', label: t('Capabilities'), count: capabilities.length },
		{ id: 'versions', label: t('Versions'), count: versions.length },
		{ id: 'evals', label: t('Evals'), count: evalCases.length },
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
							<span
								className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${statusClass(network.status)}`}
							>
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
							{t(
								'{documents} documents · {drafts} draft concepts · {links} data links',
								{
									documents: documents.length,
									drafts: draftCount,
									links: network.data_link_count,
								},
							)}
						</p>
					</div>
					<div className="flex flex-wrap items-center gap-2">
						<Button onClick={() => setShowDocumentModal(true)}>
							<Icon name={IconName.Plus} className="mr-1.5 h-4 w-4" />
							{t('Add parsed document')}
						</Button>
						<input
							ref={importInputRef}
							type="file"
							accept=".tar,.tgz,.tar.gz,.zip"
							className="hidden"
							onChange={(event) => {
								const file = event.target.files?.[0];
								event.target.value = '';
								if (file) void importBkn(file);
							}}
						/>
						<Button
							theme={ButtonTheme.Secondary}
							loading={importing}
							onClick={() => importInputRef.current?.click()}
						>
							<Icon name={IconName.Upload} className="mr-1.5 h-4 w-4" />
							{t('Import BKN')}
						</Button>
						<a
							href={knowledgeApi.exportUrl(network.id)}
							download={`${network.name}.bkn.tar.gz`}
							className="inline-flex h-9 items-center rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-body no-underline transition-colors hover:border-[#76b900] hover:bg-[#76b900]/10 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						>
							<Icon name={IconName.Download} className="mr-1.5 h-4 w-4" />
							{t('Export BKN')}
						</a>
						<Button theme={ButtonTheme.Secondary} onClick={togglePublish}>
							{network.status === 'published' ? t('Back to draft') : t('Publish')}
						</Button>
						{isAdmin && (
							<Button
								theme={ButtonTheme.Secondary}
								onClick={() => setShowGrantModal(true)}
							>
								{t('Access')}
							</Button>
						)}
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
								<span className="ml-1 text-[11px] text-secondary">
									{item.count}
								</span>
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
									[
										t('1. Parse'),
										t(
											'Run OXR on a PDF or image and keep the Markdown and page blocks.',
										),
									],
									[
										t('2. Extract'),
										t(
											'The extractor proposes concepts, relations and facts with quotes.',
										),
									],
									[
										t('3. Review'),
										t(
											'Certify concepts, relations and facts; unsupported claims are dropped.',
										),
									],
									[
										t('4. Connect'),
										t('Link concepts to glossary terms or catalog tables.'),
									],
								].map(([title, description]) => (
									<li
										key={title}
										className="rounded-xl border border-zinc-200 bg-zinc-50/60 p-3 dark:border-zinc-700 dark:bg-zinc-800/40"
									>
										<div className="text-sm font-medium text-heading dark:text-zinc-100">
											{title}
										</div>
										<p className="mt-1 text-xs leading-5 text-secondary">
											{description}
										</p>
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
									[t('Action types'), network.action_count],
									[t('Risks'), network.risk_count],
									[t('Metrics'), network.metric_count],
									[t('Concept groups'), network.group_count],
									[t('Capabilities'), network.capability_count],
									[t('Facts'), network.fact_count],
									[t('Documents'), network.document_count],
									[t('Data links'), network.data_link_count],
								].map(([label, value]) => (
									<div
										key={String(label)}
										className="flex items-center justify-between border-b border-zinc-100 pb-2 text-sm last:border-0 dark:border-zinc-800"
									>
										<dt className="text-secondary">{label}</dt>
										<dd className="font-semibold text-heading dark:text-zinc-100">
											{value}
										</dd>
									</div>
								))}
							</dl>
							<div className="mt-4">
								<Button
									theme={ButtonTheme.DangerSubtle}
									size={Size.SMALL}
									onClick={removeNetwork}
								>
									{t('Delete network')}
								</Button>
							</div>
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

				{tab === 'actions' && (
					<div className="space-y-3">
						<p className="text-xs text-secondary">
							{t(
								'Actions are document-grounded operations. They become BKN action types when exported.',
							)}
						</p>
						{actions.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No actions yet.')}
							</div>
						) : (
							actions.map((action) => (
								<div key={action.id} className={cardClassName}>
									<div className="flex flex-wrap items-start justify-between gap-3">
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
													{action.name}
												</h3>
												<span className="rounded-full bg-[#76b900]/15 px-2 py-0.5 text-[10px] text-[#4b7a00]">
													{t(action.action_intent)}
												</span>
												{action.bound_concept_name && (
													<span className="text-[11px] text-secondary">
														{t('Bound to {name}', {
															name: action.bound_concept_name,
														})}
													</span>
												)}
											</div>
											<p className="mt-1 text-xs leading-5 text-secondary">
												{action.description || t('No description yet.')}
											</p>
											{action.parameters.length > 0 && (
												<div className="mt-2 flex flex-wrap gap-1.5">
													{action.parameters.map((parameter, index) => (
														<span
															key={`${parameter.name}-${index}`}
															className="rounded bg-zinc-100 px-2 py-0.5 text-[10px] text-secondary dark:bg-zinc-800"
														>
															{parameter.name || '—'}
															{parameter.type
																? `: ${parameter.type}`
																: ''}
														</span>
													))}
												</div>
											)}
											<div className="mt-2 flex flex-wrap items-center gap-1.5">
												{action.capabilities.map((capability) => (
													<span
														key={capability.id}
														className="inline-flex items-center gap-1 rounded-full border border-[#76b900]/40 bg-[#76b900]/10 px-2 py-0.5 text-[10px] text-[#4b7a00]"
													>
														{t(capability.kind)} · {capability.name}
														<button
															type="button"
															onClick={() =>
																unmountActionCapability(
																	action,
																	capability.id,
																)
															}
															aria-label={t('Unmount {name}', {
																name: capability.name,
															})}
														>
															<Icon
																name={IconName.Close}
																className="h-3 w-3"
															/>
														</button>
													</span>
												))}
												<select
													className="h-6 rounded-md border border-zinc-300 bg-white px-1 text-[10px] text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
													value=""
													onChange={(event) => {
														const value = event.target.value;
														event.target.value = '';
														mountActionCapability(action, value);
													}}
												>
													<option value="">
														{t('Mount capability…')}
													</option>
													{capabilities
														.filter(
															(item) =>
																item.enabled &&
																!action.capabilities.some(
																	(bound) => bound.id === item.id,
																),
														)
														.map((item) => (
															<option key={item.id} value={item.id}>
																{t(item.kind)} · {item.name}
															</option>
														))}
												</select>
											</div>
										</div>
										<div className="flex items-center gap-2">
											<span
												className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(action.status)}`}
											>
												{statusLabel(action.status)}
											</span>
											<StatusSelect
												value={action.status}
												onChange={(status) =>
													setActionStatus(action, status)
												}
											/>
										</div>
									</div>
									{action.evidence.length > 0 && (
										<div className="mt-3">
											<EvidenceList evidence={action.evidence} />
										</div>
									)}
									<div className="mt-3 flex justify-end">
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											onClick={() => setExecutionAction(action)}
										>
											{t('Prepare execution')}
										</Button>
									</div>
								</div>
							))
						)}
					</div>
				)}

				{tab === 'risks' && (
					<div className="space-y-3">
						<p className="text-xs text-secondary">
							{t(
								'Risks capture what can go wrong, how severe it is and the mitigation found in the source.',
							)}
						</p>
						{risks.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No risks yet.')}
							</div>
						) : (
							risks.map((risk) => (
								<div key={risk.id} className={cardClassName}>
									<div className="flex flex-wrap items-start justify-between gap-3">
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
													{risk.name}
												</h3>
												<span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700">
													{t(risk.severity)}
												</span>
												{risk.related_concept_name && (
													<span className="text-[11px] text-secondary">
														{t('Related to {name}', {
															name: risk.related_concept_name,
														})}
													</span>
												)}
											</div>
											<p className="mt-1 text-xs leading-5 text-secondary">
												{risk.description || t('No description yet.')}
											</p>
											{risk.mitigation && (
												<p className="mt-1 text-xs leading-5 text-secondary">
													<span className="font-medium">
														{t('Mitigation')}:{' '}
													</span>
													{risk.mitigation}
												</p>
											)}
										</div>
										<div className="flex items-center gap-2">
											<span
												className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(risk.status)}`}
											>
												{statusLabel(risk.status)}
											</span>
											<StatusSelect
												value={risk.status}
												onChange={(status) => setRiskStatus(risk, status)}
											/>
										</div>
									</div>
									{risk.evidence.length > 0 && (
										<div className="mt-3">
											<EvidenceList evidence={risk.evidence} />
										</div>
									)}
								</div>
							))
						)}
					</div>
				)}

				{tab === 'metrics' && (
					<div className="space-y-3">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<p className="text-xs text-secondary">
								{t(
									'Object metrics turn a concept into a computable measure. The expression can be SQL or a documented formula.',
								)}
							</p>
							<Button size={Size.SMALL} onClick={() => setShowMetricModal(true)}>
								{t('New object metric')}
							</Button>
						</div>
						{metrics.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No metrics yet.')}
							</div>
						) : (
							metrics.map((metric) => (
								<div key={metric.id} className={cardClassName}>
									<div className="flex flex-wrap items-start justify-between gap-3">
										<div className="min-w-0 flex-1">
											<div className="flex flex-wrap items-center gap-2">
												<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
													{metric.name}
												</h3>
												{metric.unit && (
													<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-secondary dark:bg-zinc-800">
														{metric.unit}
													</span>
												)}
												{metric.concept_name && (
													<span className="text-[11px] text-secondary">
														{t('Owned by {name}', {
															name: metric.concept_name,
														})}
													</span>
												)}
											</div>
											<p className="mt-1 text-xs text-secondary">
												{metric.description || t('No description yet.')}
											</p>
											{metric.expression && (
												<pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-950 px-3 py-2 text-[11px] text-zinc-100">
													{metric.expression}
												</pre>
											)}
											{metricValidations[metric.id] && (
												<p
													className={`mt-2 text-[11px] ${
														metricValidations[metric.id].valid === false
															? 'text-red-600'
															: metricValidations[metric.id].valid ===
																  true
																? 'text-emerald-600'
																: 'text-secondary'
													}`}
												>
													{t(metricValidations[metric.id].message)}
												</p>
											)}
											{metricPreviews[metric.id] && (
												<div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
													<table className="min-w-full text-left text-[11px]">
														<thead className="bg-zinc-50 text-secondary dark:bg-zinc-800">
															<tr>
																{metricPreviews[
																	metric.id
																].columns.map((column) => (
																	<th
																		key={column}
																		className="px-2 py-1 font-medium"
																	>
																		{column}
																	</th>
																))}
															</tr>
														</thead>
														<tbody>
															{metricPreviews[metric.id].rows.map(
																(row, index) => (
																	<tr
																		key={index}
																		className="border-t border-zinc-100 dark:border-zinc-800"
																	>
																		{metricPreviews[
																			metric.id
																		].columns.map((column) => (
																			<td
																				key={column}
																				className="px-2 py-1"
																			>
																				{String(
																					row[column] ??
																						'—',
																				)}
																			</td>
																		))}
																	</tr>
																),
															)}
														</tbody>
													</table>
												</div>
											)}
										</div>
										<div className="flex items-center gap-2">
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												onClick={() => validateMetric(metric)}
											>
												{t('Validate')}
											</Button>
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												onClick={() => previewMetric(metric)}
											>
												{t('Preview')}
											</Button>
											<span
												className={`rounded-full px-2 py-0.5 text-[10px] ${statusClass(metric.status)}`}
											>
												{statusLabel(metric.status)}
											</span>
											<StatusSelect
												value={metric.status}
												onChange={(status) =>
													setMetricStatus(metric, status)
												}
											/>
											<Button
												theme={ButtonTheme.DangerSubtle}
												size={Size.SMALL}
												onClick={() => removeMetric(metric)}
											>
												{t('Delete')}
											</Button>
										</div>
									</div>
								</div>
							))
						)}
					</div>
				)}

				{tab === 'groups' && (
					<div className="space-y-3">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<p className="text-xs text-secondary">
								{t(
									'Concept groups organise related object types for navigation and BKN context loading.',
								)}
							</p>
							<Button size={Size.SMALL} onClick={() => setShowGroupModal(true)}>
								{t('New concept group')}
							</Button>
						</div>
						{groups.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No concept groups yet.')}
							</div>
						) : (
							groups.map((group) => (
								<div key={group.id} className={cardClassName}>
									<div className="flex items-start justify-between gap-3">
										<div className="min-w-0">
											<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
												{group.name}
											</h3>
											<p className="mt-1 text-xs text-secondary">
												{group.description || t('No description yet.')}
											</p>
											<div className="mt-2 flex flex-wrap gap-1.5">
												{group.concepts.map((concept) => (
													<span
														key={concept.id}
														className="rounded-full border border-zinc-200 px-2 py-0.5 text-[10px] text-secondary dark:border-zinc-700"
													>
														{concept.name}
													</span>
												))}
											</div>
										</div>
										<Button
											theme={ButtonTheme.DangerSubtle}
											size={Size.SMALL}
											onClick={() => removeGroup(group)}
										>
											{t('Delete')}
										</Button>
									</div>
								</div>
							))
						)}
					</div>
				)}

				{tab === 'capabilities' && (
					<div className="space-y-3">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<p className="text-xs text-secondary">
								{t(
									'Capabilities declare the Skills, Functions, MCP tools and knowledge bases this network depends on.',
								)}
							</p>
							<Button size={Size.SMALL} onClick={() => setShowCapabilityModal(true)}>
								{t('New capability')}
							</Button>
						</div>
						{capabilities.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No capabilities yet.')}
							</div>
						) : (
							capabilities.map((capability) => (
								<div key={capability.id} className={cardClassName}>
									<div className="flex items-start justify-between gap-3">
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
													{capability.name}
												</h3>
												<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-secondary dark:bg-zinc-800">
													{t(capability.kind)}
												</span>
												<span className="text-[10px] text-secondary">
													{capability.enabled
														? t('Enabled')
														: t('Disabled')}
												</span>
											</div>
											<p className="mt-1 text-xs text-secondary">
												{capability.description || t('No description yet.')}
											</p>
											{Object.keys(capability.config ?? {}).length > 0 && (
												<pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-50 px-3 py-2 text-[10px] text-secondary dark:bg-zinc-800">
													{JSON.stringify(capability.config, null, 2)}
												</pre>
											)}
										</div>
										<Button
											theme={ButtonTheme.DangerSubtle}
											size={Size.SMALL}
											onClick={() => removeCapability(capability)}
										>
											{t('Delete')}
										</Button>
									</div>
								</div>
							))
						)}
					</div>
				)}

				{tab === 'versions' && (
					<div className="space-y-3">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<p className="text-xs text-secondary">
								{t(
									'Versions snapshot the whole network. Restoring replaces current concepts, relations, actions, risks, metrics, groups and capabilities.',
								)}
							</p>
							<div className="flex items-center gap-2">
								<input
									className={`${inputClassName} w-56`}
									value={versionLabel}
									onChange={(event) => setVersionLabel(event.target.value)}
									placeholder={t('Version label (optional)')}
								/>
								<Button size={Size.SMALL} onClick={createVersion}>
									{t('Create version')}
								</Button>
							</div>
						</div>
						{versions.length === 0 ? (
							<div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-secondary dark:border-zinc-700">
								{t('No versions yet.')}
							</div>
						) : (
							versions.map((version) => (
								<div key={version.id} className={cardClassName}>
									<div className="flex flex-wrap items-center justify-between gap-3">
										<div>
											<div className="flex items-center gap-2">
												<span className="rounded-full bg-[#76b900]/15 px-2 py-0.5 text-xs font-medium text-[#4b7a00]">
													v{version.version}
												</span>
												<span className="text-sm font-medium text-heading dark:text-zinc-100">
													{version.label || t('Untitled version')}
												</span>
											</div>
											<div className="mt-1 text-[11px] text-secondary">
												{version.created
													? formatDateTime(version.created)
													: '—'}
												{version.created_by
													? ` · ${version.created_by}`
													: ''}
											</div>
										</div>
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											onClick={() => restoreVersion(version)}
										>
											{t('Restore')}
										</Button>
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											onClick={() => compareVersion(version)}
										>
											{t('Compare')}
										</Button>
									</div>
									{versionDiffs[version.id] && (
										<div className="mt-3 space-y-2 border-t border-zinc-100 pt-3 text-[11px] dark:border-zinc-800">
											{versionDiffs[version.id].network_changed && (
												<p className="text-amber-600">
													{t('Network metadata changed.')}
												</p>
											)}
											{Object.entries(
												versionDiffs[version.id].collections,
											).map(
												([name, diff]) =>
													diff.added.length +
														diff.removed.length +
														diff.changed.length >
														0 && (
														<div key={name} className="text-secondary">
															<span className="font-medium text-heading dark:text-zinc-100">
																{t(name)}
															</span>
															: +{diff.added.length} / -
															{diff.removed.length} / ~
															{diff.changed.length}
															{diff.added.length > 0 && (
																<span className="ml-2 text-emerald-600">
																	{t('Added')}:{' '}
																	{diff.added
																		.map((item) => item.label)
																		.join('、')}
																</span>
															)}
															{diff.removed.length > 0 && (
																<span className="ml-2 text-red-600">
																	{t('Removed')}:{' '}
																	{diff.removed
																		.map((item) => item.label)
																		.join('、')}
																</span>
															)}
															{diff.changed.length > 0 && (
																<span className="ml-2 text-amber-600">
																	{t('Changed')}:{' '}
																	{diff.changed
																		.map(
																			(item) =>
																				`${item.label} (${item.fields.join(', ')})`,
																		)
																		.join('、')}
																</span>
															)}
														</div>
													),
											)}
										</div>
									)}
								</div>
							))
						)}
					</div>
				)}

				{tab === 'evals' && (
					<div className="space-y-4">
						<div className={cardClassName}>
							<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
								{t('Add eval case')}
							</h3>
							<p className="mt-1 text-xs text-secondary">
								{t(
									'Expected concepts and facts are comma-separated; each is checked against the knowledge context retrieved for the question.',
								)}
							</p>
							<div className="mt-3 space-y-2">
								<input
									className={inputClassName}
									value={evalQuestion}
									onChange={(event) => setEvalQuestion(event.target.value)}
									placeholder={t('Question to evaluate')}
								/>
								<div className="grid grid-cols-1 gap-2 md:grid-cols-2">
									<input
										className={inputClassName}
										value={evalConcepts}
										onChange={(event) => setEvalConcepts(event.target.value)}
										placeholder={t('Expected concepts, comma separated')}
									/>
									<input
										className={inputClassName}
										value={evalFacts}
										onChange={(event) => setEvalFacts(event.target.value)}
										placeholder={t('Expected fact keywords, comma separated')}
									/>
								</div>
								<div className="flex justify-end gap-2">
									<Button size={Size.SMALL} onClick={addEvalCase}>
										{t('Add case')}
									</Button>
									<Button
										theme={ButtonTheme.Secondary}
										size={Size.SMALL}
										onClick={runEvals}
									>
										{t('Run evals')}
									</Button>
								</div>
							</div>
						</div>

						{evalRuns.length > 0 && (
							<div className={cardClassName}>
								<h3 className="text-sm font-semibold text-heading dark:text-zinc-100">
									{t('Latest eval run')}
								</h3>
								<div className="mt-2 flex items-baseline gap-3">
									<span className="text-2xl font-semibold text-heading dark:text-zinc-100">
										{evalRuns[0].passed}/{evalRuns[0].total}
									</span>
									<span className="text-xs text-secondary">{t('passed')}</span>
								</div>
								<div className="mt-3 space-y-2">
									{evalRuns[0].details.map((detail) => (
										<div
											key={detail.case_id}
											className="rounded-lg border border-zinc-200 px-3 py-2 text-xs dark:border-zinc-700"
										>
											<div className="flex items-center justify-between gap-2">
												<span className="font-medium text-heading dark:text-zinc-100">
													{detail.question}
												</span>
												<span
													className={
														detail.passed
															? 'text-emerald-600'
															: 'text-red-600'
													}
												>
													{detail.passed ? t('Passed') : t('Failed')}
												</span>
											</div>
											{!detail.passed && (
												<div className="mt-1 text-secondary">
													{detail.missing_concepts.length > 0 && (
														<div>
															{t('Missing concepts')}:{' '}
															{detail.missing_concepts.join('、')}
														</div>
													)}
													{detail.missing_facts.length > 0 && (
														<div>
															{t('Missing facts')}:{' '}
															{detail.missing_facts.join('、')}
														</div>
													)}
												</div>
											)}
										</div>
									))}
								</div>
							</div>
						)}

						<div className="space-y-2">
							{evalCases.map((item) => (
								<div key={item.id} className={cardClassName}>
									<div className="flex items-start justify-between gap-3">
										<div>
											<div className="text-sm font-medium text-heading dark:text-zinc-100">
												{item.question}
											</div>
											<div className="mt-1 text-[11px] text-secondary">
												{t('Concepts')}:{' '}
												{item.expected_concepts.join('、') || '—'}
												{' · '}
												{t('Facts')}:{' '}
												{item.expected_facts.join('、') || '—'}
											</div>
										</div>
										<Button
											theme={ButtonTheme.DangerSubtle}
											size={Size.SMALL}
											onClick={() => removeEvalCase(item)}
										>
											{t('Delete')}
										</Button>
									</div>
								</div>
							))}
							{evalCases.length === 0 && (
								<div className="rounded-xl border border-dashed border-zinc-300 py-10 text-center text-sm text-secondary dark:border-zinc-700">
									{t('No eval cases yet.')}
								</div>
							)}
						</div>
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
													{documentTitle(document)}
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
												{document.summary ||
													(document.error_message
														? t(document.error_message)
														: t('Not extracted yet.'))}
											</p>
											<div className="mt-1 flex flex-wrap gap-3 text-[11px] text-secondary">
												{document.source_name && (
													<span>{document.source_name}</span>
												)}
												{document.extracted_at && (
													<span>
														{formatDateTime(document.extracted_at)}
													</span>
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
					<div className="space-y-3">
						<div className={`${cardClassName} flex flex-wrap items-end gap-3`}>
							<label className="text-xs text-secondary">
								<span className="mb-1 block">{t('Start concept')}</span>
								<select
									className="h-8 min-w-52 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
									value={graphSeed}
									onChange={(event) => setGraphSeed(event.target.value)}
								>
									<option value="">{t('All concepts')}</option>
									{concepts.map((concept) => (
										<option key={concept.id} value={concept.id}>
											{concept.name}
										</option>
									))}
								</select>
							</label>
							<label className="text-xs text-secondary">
								<span className="mb-1 block">{t('Depth')}</span>
								<select
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
									value={graphDepth}
									onChange={(event) => setGraphDepth(Number(event.target.value))}
								>
									{[1, 2, 3, 4].map((value) => (
										<option key={value} value={value}>
											{value}
										</option>
									))}
								</select>
							</label>
							<label className="text-xs text-secondary">
								<span className="mb-1 block">{t('Direction')}</span>
								<select
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
									value={graphDirection}
									onChange={(event) =>
										setGraphDirection(
											event.target.value as 'out' | 'in' | 'both',
										)
									}
								>
									<option value="both">{t('Both')}</option>
									<option value="out">{t('Outgoing')}</option>
									<option value="in">{t('Incoming')}</option>
								</select>
							</label>
							<label className="flex items-center gap-1 text-xs text-secondary">
								<input
									type="checkbox"
									checked={graphIncludeData}
									onChange={(event) => setGraphIncludeData(event.target.checked)}
								/>
								{t('Include data links')}
							</label>
							<Button size={Size.SMALL} onClick={applyGraphQuery}>
								{t('Apply')}
							</Button>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								onClick={resetGraphQuery}
							>
								{t('Reset')}
							</Button>
						</div>
						<KnowledgeGraph
							graph={graph}
							onSelectConcept={(conceptId) => {
								setExpandedConcept(conceptId);
								setTab('concepts');
							}}
						/>
					</div>
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
			{showGroupModal && (
				<KnowledgeGroupModal
					networkId={network.id}
					concepts={concepts}
					onClose={() => setShowGroupModal(false)}
					onCreated={(group) => {
						setGroups((current) => [...current, group]);
						setShowGroupModal(false);
					}}
				/>
			)}
			{showMetricModal && (
				<KnowledgeMetricModal
					networkId={network.id}
					concepts={concepts}
					onClose={() => setShowMetricModal(false)}
					onCreated={(metric) => {
						setMetrics((current) => [...current, metric]);
						setShowMetricModal(false);
					}}
				/>
			)}
			{showCapabilityModal && (
				<KnowledgeCapabilityModal
					networkId={network.id}
					onClose={() => setShowCapabilityModal(false)}
					onCreated={(capability) => {
						setCapabilities((current) => [...current, capability]);
						setShowCapabilityModal(false);
					}}
				/>
			)}
			{executionAction && (
				<KnowledgeExecutionModal
					action={executionAction}
					onClose={() => setExecutionAction(null)}
					onCreated={() => {
						setToast({ message: t('Execution plan saved as dry-run.') });
					}}
				/>
			)}
			{showGrantModal && (
				<KnowledgeGrantModal
					networkId={network.id}
					onClose={() => {
						setShowGrantModal(false);
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
