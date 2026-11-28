// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';

import {
	knowledgeApi,
	type KnowledgeNetwork,
	type KnowledgeSearchItem,
	type KnowledgeSearchKind,
	type KnowledgeSearchResult,
} from '@/api/knowledge';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

const ALL_KINDS: KnowledgeSearchKind[] = [
	'chunk',
	'document',
	'concept',
	'relation',
	'fact',
	'action',
	'risk',
	'metric',
	'evidence',
];

const KIND_STYLES: Record<KnowledgeSearchKind, string> = {
	chunk: 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300',
	document:
		'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300',
	concept:
		'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300',
	relation:
		'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-300',
	fact: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
	action: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300',
	risk: 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300',
	metric: 'border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-800 dark:bg-cyan-950/30 dark:text-cyan-300',
	evidence:
		'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950/30 dark:text-orange-300',
};

const kindLabel = (kind: KnowledgeSearchKind): string =>
	t(
		kind === 'chunk'
			? 'Passage'
			: kind === 'document'
				? 'Document'
				: kind === 'concept'
					? 'Concept'
					: kind === 'relation'
						? 'Relation'
						: kind === 'fact'
							? 'Knowledge fact'
							: kind === 'action'
								? 'Action'
								: kind === 'risk'
									? 'Risk'
									: kind === 'metric'
										? 'Metric'
										: 'Evidence',
	);

const statusLabel = (status: string | null): string =>
	t(
		status === 'certified'
			? 'Certified'
			: status === 'reviewed'
				? 'Reviewed'
				: status === 'draft'
					? 'Draft'
					: status === 'extracted'
						? 'Extracted'
						: '',
	);

const KindBadge = ({ kind }: { kind: KnowledgeSearchKind }) => (
	<span
		className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${KIND_STYLES[kind]}`}
	>
		{kindLabel(kind)}
	</span>
);

const ResultCard = ({ item }: { item: KnowledgeSearchItem }) => (
	<article className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md dark:border-zinc-700 dark:bg-zinc-900">
		<div className="flex flex-wrap items-start gap-2">
			<KindBadge kind={item.kind} />
			{statusLabel(item.status) && (
				<span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
					{statusLabel(item.status)}
				</span>
			)}
			<span className="ml-auto text-[11px] text-zinc-500 dark:text-zinc-400">
				{Math.round(item.score * 100) / 100}
			</span>
		</div>
		<h3 className="mt-2 text-sm font-semibold text-heading dark:text-zinc-100">
			{item.title || item.document_title || t('Untitled result')}
		</h3>
		{item.snippet && (
			<p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-body dark:text-zinc-300">
				{item.snippet}
			</p>
		)}
		<div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-secondary dark:text-zinc-400">
			{item.network_id && (
				<Link
					href={`/knowledge/${encodeURIComponent(item.network_id)}`}
					className="inline-flex items-center gap-1 text-[#4d7a00] no-underline hover:underline dark:text-[#a3d63a]"
				>
					<Icon name={IconName.Knowledge} className="h-3.5 w-3.5" />
					{item.network_name || t('Knowledge network')}
				</Link>
			)}
			{item.document_title && item.kind !== 'document' && (
				<span className="truncate">{item.document_title}</span>
			)}
			{item.page != null && (
				<span>
					{t('Page {page}', { page: item.page })}
					{item.page_end != null && item.page_end !== item.page
						? `–${item.page_end}`
						: ''}
				</span>
			)}
			{item.source_name && <span className="truncate">{item.source_name}</span>}
		</div>
		{item.evidence.length > 0 && (
			<div className="mt-3 space-y-1 border-t border-zinc-100 pt-2 dark:border-zinc-800">
				{item.evidence.slice(0, 2).map((evidence) => (
					<p
						key={evidence.id}
						className="text-[11px] leading-5 text-secondary dark:text-zinc-400"
					>
						<span className="font-semibold text-body dark:text-zinc-300">
							{t('Evidence')}
							{evidence.page != null
								? ` ${t('p.{page}', { page: evidence.page })}`
								: ''}
							:
						</span>{' '}
						“{evidence.quote}”
					</p>
				))}
			</div>
		)}
	</article>
);

export const KnowledgeSearchView = ({ initialQuery = '' }: { initialQuery?: string }) => {
	const [query, setQuery] = useState(initialQuery);
	const [networks, setNetworks] = useState<KnowledgeNetwork[]>([]);
	const [networkId, setNetworkId] = useState('');
	const [mode, setMode] = useState<'human' | 'agent'>('human');
	const [selectedKinds, setSelectedKinds] = useState<Set<KnowledgeSearchKind>>(new Set());
	const [result, setResult] = useState<KnowledgeSearchResult | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [copied, setCopied] = useState(false);
	const initialSearchRun = useRef(false);

	useEffect(() => {
		let cancelled = false;
		knowledgeApi.listNetworks().then((response) => {
			if (!cancelled && !response.error && response.data) setNetworks(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	const runSearch = useCallback(
		async (term?: string) => {
			const nextQuery = (term ?? query).trim();
			if (!nextQuery) return;
			setLoading(true);
			setError(null);
			const response = await knowledgeApi.search({
				query: nextQuery,
				network_id: networkId || undefined,
				mode,
				kinds: selectedKinds.size ? [...selectedKinds] : undefined,
				limit: 30,
				include_evidence: true,
			});
			setLoading(false);
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to search knowledge.'));
				return;
			}
			setResult(response.data);
		},
		[query, networkId, mode, selectedKinds],
	);

	useEffect(() => {
		if (initialSearchRun.current || !initialQuery.trim()) return;
		initialSearchRun.current = true;
		const id = window.setTimeout(() => {
			void runSearch(initialQuery);
		}, 0);
		return () => window.clearTimeout(id);
	}, [initialQuery, runSearch]);

	const toggleKind = (kind: KnowledgeSearchKind) => {
		setSelectedKinds((current) => {
			const next = new Set(current);
			if (next.has(kind)) next.delete(kind);
			else next.add(kind);
			return next;
		});
	};

	const kindCounts = result?.facets.kinds ?? {};
	const activeFilterCount = useMemo(
		() => (networkId ? 1 : 0) + (selectedKinds.size > 0 ? 1 : 0),
		[networkId, selectedKinds],
	);

	const copyContext = async () => {
		if (!result?.context) return;
		try {
			await navigator.clipboard.writeText(result.context);
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1500);
		} catch {
			setCopied(false);
		}
	};

	return (
		<div className="flex h-full w-full flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-6 dark:border-zinc-800">
				<div className="flex items-center gap-2">
					<Icon name={IconName.Discovery} className="h-5 w-5 text-[#76b900]" />
					<h1 className="text-xl font-semibold tracking-tight text-heading dark:text-zinc-100">
						{t('Knowledge search')}
					</h1>
				</div>
				<p className="mt-2 max-w-3xl text-sm leading-6 text-secondary dark:text-zinc-400">
					{t(
						'Search across document passages, concepts, facts and citations. Use Human search while curating; use Agent-ready for reviewed, conservative context.',
					)}
				</p>
				<form
					className="mt-5 flex flex-wrap items-center gap-2"
					onSubmit={(event) => {
						event.preventDefault();
						void runSearch();
					}}
				>
					<input
						value={query}
						onChange={(event) => setQuery(event.target.value)}
						placeholder={t('Search policies, manuals, roles, facts…')}
						className="h-10 min-w-[260px] flex-1 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
					/>
					<select
						value={networkId}
						onChange={(event) => setNetworkId(event.target.value)}
						aria-label={t('Knowledge network')}
						className="h-10 max-w-52 rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
					>
						<option value="">{t('All networks')}</option>
						{networks.map((network) => (
							<option key={network.id} value={network.id}>
								{network.name}
							</option>
						))}
					</select>
					<div className="flex h-10 items-center rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 dark:border-zinc-700 dark:bg-zinc-900">
						<button
							type="button"
							onClick={() => setMode('human')}
							className={`h-9 rounded-md px-3 text-xs font-medium transition-colors ${
								mode === 'human'
									? 'bg-white text-heading shadow-sm dark:bg-zinc-800 dark:text-zinc-100'
									: 'text-secondary dark:text-zinc-400'
							}`}
						>
							{t('Human search')}
						</button>
						<button
							type="button"
							onClick={() => setMode('agent')}
							className={`h-9 rounded-md px-3 text-xs font-medium transition-colors ${
								mode === 'agent'
									? 'bg-white text-heading shadow-sm dark:bg-zinc-800 dark:text-zinc-100'
									: 'text-secondary dark:text-zinc-400'
							}`}
						>
							{t('Agent-ready')}
						</button>
					</div>
					<Button type="submit" loading={loading} disabled={!query.trim()}>
						{t('Search')}
					</Button>
				</form>
				<div className="mt-3 flex flex-wrap items-center gap-1.5">
					<span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-secondary dark:text-zinc-400">
						{t('Types')}
					</span>
					{ALL_KINDS.map((kind) => {
						const active = selectedKinds.has(kind);
						return (
							<button
								key={kind}
								type="button"
								onClick={() => toggleKind(kind)}
								className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
									active
										? KIND_STYLES[kind]
										: 'border-zinc-200 bg-white text-secondary hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400'
								}`}
							>
								{kindLabel(kind)}
								{kindCounts[kind] ? ` ${kindCounts[kind]}` : ''}
							</button>
						);
					})}
					{activeFilterCount > 0 && (
						<button
							type="button"
							onClick={() => {
								setNetworkId('');
								setSelectedKinds(new Set());
							}}
							className="ml-1 text-[11px] text-secondary underline-offset-2 hover:underline dark:text-zinc-400"
						>
							{t('Clear filters')}
						</button>
					)}
				</div>
			</header>

			<main className="flex-1 px-6 py-5">
				{error && (
					<div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
						{error}
					</div>
				)}
				{loading ? (
					<div className="flex h-48 items-center justify-center">
						<Spinner />
					</div>
				) : result ? (
					<div className="flex flex-col gap-4">
						<div className="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary dark:text-zinc-400">
							<span>
								{t('{total} matches, showing {returned}', {
									total: result.total,
									returned: result.returned,
								})}
								{' · '}
								{mode === 'agent' ? t('Agent-ready') : t('Human search')}
							</span>
							{result.context && (
								<div className="flex items-center gap-2">
									<Button
										theme={ButtonTheme.Secondary}
										size={Size.SMALL}
										type="button"
										onClick={() => void copyContext()}
									>
										{copied ? t('Copied') : t('Copy agent context')}
									</Button>
								</div>
							)}
						</div>
						{result.results.length === 0 ? (
							<div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/60 px-8 py-12 text-center dark:border-zinc-700 dark:bg-zinc-900/60">
								<Icon
									name={IconName.Discovery}
									className="mx-auto h-9 w-9 text-zinc-400"
								/>
								<h2 className="mt-3 text-base font-semibold text-heading dark:text-zinc-100">
									{t('No knowledge matched')}
								</h2>
								<p className="mt-1 text-sm text-secondary dark:text-zinc-400">
									{t(
										'Try broader terms, another network, or Human search to include drafts.',
									)}
								</p>
							</div>
						) : (
							<div className="grid gap-3 xl:grid-cols-2">
								{result.results.map((item) => (
									<ResultCard key={`${item.kind}:${item.id}`} item={item} />
								))}
							</div>
						)}
						{result.context && (
							<details className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/60">
								<summary className="cursor-pointer text-xs font-semibold text-body dark:text-zinc-300">
									{t('Agent context preview')}
								</summary>
								<pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-secondary dark:text-zinc-400">
									{result.context}
								</pre>
							</details>
						)}
					</div>
				) : (
					<div className="mx-auto max-w-xl rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/60 px-8 py-12 text-center dark:border-zinc-700 dark:bg-zinc-900/60">
						<Icon
							name={IconName.Discovery}
							className="mx-auto h-10 w-10 text-[#76b900]"
						/>
						<h2 className="mt-4 text-base font-semibold text-heading dark:text-zinc-100">
							{t('Search the knowledge ontology')}
						</h2>
						<p className="mt-2 text-sm leading-6 text-secondary dark:text-zinc-400">
							{t(
								'Find the passage behind a policy, the concept behind a role, or the fact behind a number. Every result keeps its document and page reference.',
							)}
						</p>
					</div>
				)}
			</main>
		</div>
	);
};
