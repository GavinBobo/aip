// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { knowledgeApi, type KnowledgeNetwork } from '@/api/knowledge';
import { zonesApi } from '@/api/zones';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { Zone } from '@/types/zones';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

const statusStyles = (status: string): string => {
	if (status === 'published') return 'bg-emerald-100 text-emerald-700';
	if (status === 'archived') return 'bg-zinc-200 text-zinc-600';
	return 'bg-amber-100 text-amber-700';
};

const CreateNetworkModal = ({
	zones,
	onClose,
	onCreated,
}: {
	zones: Zone[];
	onClose: () => void;
	onCreated: (network: KnowledgeNetwork) => void;
}) => {
	const [name, setName] = useState('');
	const [domain, setDomain] = useState('');
	const [description, setDescription] = useState('');
	const [zoneId, setZoneId] = useState('');
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const submit = async () => {
		if (!name.trim() || saving) return;
		setSaving(true);
		setError(null);
		const response = await knowledgeApi.createNetwork({
			name: name.trim(),
			domain: domain.trim() || undefined,
			description: description.trim() || undefined,
			zone_id: zoneId || undefined,
		});
		setSaving(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to create the knowledge network.'));
			return;
		}
		onCreated(response.data);
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('New knowledge network')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('New knowledge network')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{t(
								'A knowledge network groups concepts, relations and facts extracted from parsed documents.',
							)}
						</p>
					</div>
					<Button
						theme={ButtonTheme.IconNeutral}
						size={Size.SMALL}
						iconOnly
						onClick={onClose}
						aria-label={t('Close')}
					>
						<Icon name={IconName.Close} className="h-4 w-4" />
					</Button>
				</div>
				<div className="mt-5 space-y-4">
					<label className="block">
						<span className="mb-1 block text-xs font-medium text-body">
							{t('Name')}
						</span>
						<input
							autoFocus
							className={inputClassName}
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder={t('e.g. Procurement knowledge')}
						/>
					</label>
					<label className="block">
						<span className="mb-1 block text-xs font-medium text-body">
							{t('Zone')}
						</span>
						<select
							className={inputClassName}
							value={zoneId}
							onChange={(event) => setZoneId(event.target.value)}
						>
							<option value="">{t('Visible to all signed-in users')}</option>
							{zones.map((zone) => (
								<option key={zone.id} value={zone.id}>
									{zone.name}
								</option>
							))}
						</select>
					</label>
					<label className="block">
						<span className="mb-1 block text-xs font-medium text-body">
							{t('Domain')}
						</span>
						<input
							className={inputClassName}
							value={domain}
							onChange={(event) => setDomain(event.target.value)}
							placeholder={t('e.g. Supply chain')}
						/>
					</label>
					<label className="block">
						<span className="mb-1 block text-xs font-medium text-body">
							{t('Description')}
						</span>
						<textarea
							className="min-h-24 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							value={description}
							onChange={(event) => setDescription(event.target.value)}
							placeholder={t(
								'What this knowledge covers, and which documents it comes from.',
							)}
						/>
					</label>
					{error && <p className="text-sm text-red-600">{error}</p>}
				</div>
				<div className="mt-6 flex justify-end gap-2">
					<Button theme={ButtonTheme.Secondary} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button loading={saving} disabled={!name.trim()} onClick={submit}>
						{t('Create')}
					</Button>
				</div>
			</div>
		</div>
	);
};

export const KnowledgeWorkspace = () => {
	const router = useRouter();
	const [networks, setNetworks] = useState<KnowledgeNetwork[]>([]);
	const [zones, setZones] = useState<Zone[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [creating, setCreating] = useState(false);

	useEffect(() => {
		let cancelled = false;
		knowledgeApi.listNetworks().then((response) => {
			if (cancelled) return;
			setLoading(false);
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to load knowledge networks.'));
				return;
			}
			setError(null);
			setNetworks(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		let cancelled = false;
		zonesApi.getAll().then((response) => {
			if (!cancelled && !response.error && response.data) setZones(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		if (!window.location.search.includes('new=1')) return;
		const timer = window.setTimeout(() => setCreating(true), 0);
		return () => window.clearTimeout(timer);
	}, []);

	return (
		<div className="flex h-full w-full flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-6 dark:border-zinc-800">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div className="max-w-3xl">
						<div className="flex items-center gap-2">
							<Icon name={IconName.Knowledge} className="h-5 w-5 text-[#76b900]" />
							<h1 className="text-xl font-semibold tracking-tight text-heading dark:text-zinc-100">
								{t('Knowledge Ontology')}
							</h1>
						</div>
						<p className="mt-2 text-sm leading-6 text-secondary">
							{t(
								'Where the data ontology describes tables and terms, the knowledge ontology describes concepts, relations and grounded facts extracted from parsed documents. Link a concept to a term or table to connect both worlds.',
							)}
						</p>
					</div>
					<div className="flex flex-wrap items-center gap-2">
						<Link
							href="/knowledge/search"
							className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-body no-underline transition-colors hover:border-[#76b900] hover:bg-[#76b900]/10 hover:text-[#5e9400] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-[#76b900]/20 dark:hover:text-[#a3d63a]"
						>
							<Icon name={IconName.Discovery} className="h-4 w-4" />
							{t('Knowledge search')}
						</Link>
						<Button onClick={() => setCreating(true)}>
							<Icon name={IconName.Plus} className="mr-1.5 h-4 w-4" />
							{t('New knowledge network')}
						</Button>
					</div>
				</div>
			</header>

			<main className="flex-1 px-6 py-6">
				{loading ? (
					<div className="flex h-48 items-center justify-center">
						<Spinner />
					</div>
				) : error ? (
					<div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
						{error}
					</div>
				) : networks.length === 0 ? (
					<div className="mx-auto max-w-xl rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/60 px-8 py-12 text-center dark:border-zinc-700 dark:bg-zinc-900/60">
						<Icon
							name={IconName.Knowledge}
							className="mx-auto h-10 w-10 text-[#76b900]"
						/>
						<h2 className="mt-4 text-base font-semibold text-heading dark:text-zinc-100">
							{t('Start with a knowledge network')}
						</h2>
						<p className="mt-2 text-sm leading-6 text-secondary">
							{t(
								'Create a network, add a successful parsing result, and let the extractor turn the document into concepts, relations and cited facts.',
							)}
						</p>
						<div className="mt-5">
							<Button onClick={() => setCreating(true)}>
								{t('Create the first network')}
							</Button>
						</div>
					</div>
				) : (
					<div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
						{networks.map((network) => (
							<Link
								key={network.id}
								href={`/knowledge/${encodeURIComponent(network.id)}`}
								className="group flex flex-col rounded-2xl border border-zinc-200 bg-white p-5 no-underline transition-all hover:-translate-y-0.5 hover:border-[#76b900]/50 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
							>
								<div className="flex items-start justify-between gap-3">
									<div className="min-w-0">
										<h2 className="truncate text-base font-semibold text-heading group-hover:text-[#5e9400] dark:text-zinc-100">
											{network.name}
										</h2>
										<p className="mt-1 text-xs text-secondary">
											{network.domain || t('No domain')}
											{' · '}
											{network.zone_id
												? zones.find((zone) => zone.id === network.zone_id)
														?.name || t('Zoned')
												: t('All signed-in users')}
										</p>
									</div>
									<span
										className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusStyles(network.status)}`}
									>
										{t(network.status)}
									</span>
								</div>
								<p className="mt-3 line-clamp-2 min-h-10 text-sm leading-5 text-secondary">
									{network.description || t('No description yet.')}
								</p>
								<div className="mt-4 grid grid-cols-4 gap-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
									{[
										[t('Concepts'), network.concept_count],
										[t('Relations'), network.relation_count],
										[t('Facts'), network.fact_count],
										[t('Data links'), network.data_link_count],
									].map(([label, value]) => (
										<div key={String(label)}>
											<div className="text-base font-semibold text-heading dark:text-zinc-100">
												{value}
											</div>
											<div className="text-[11px] text-secondary">
												{label}
											</div>
										</div>
									))}
								</div>
							</Link>
						))}
					</div>
				)}
			</main>

			{creating && (
				<CreateNetworkModal
					zones={zones}
					onClose={() => setCreating(false)}
					onCreated={(network) => {
						setCreating(false);
						router.push(`/knowledge/${encodeURIComponent(network.id)}`);
					}}
				/>
			)}
		</div>
	);
};
