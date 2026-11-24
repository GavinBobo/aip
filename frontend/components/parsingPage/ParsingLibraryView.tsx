// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

import { parsingApi, type ParsingRunSummary } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { formatDuration, formatInstanceTime } from '@/lib/parsingInstances';

const PAGE_SIZE = 20;

const statusClass = (status: string): string => {
	if (status === 'succeeded') return 'bg-emerald-100 text-emerald-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'cancelled') return 'bg-zinc-200 text-zinc-600';
	if (status === 'running') return 'bg-[#76b900]/15 text-[#4b7a00]';
	return 'bg-zinc-100 text-secondary';
};

export const ParsingLibraryView = () => {
	const [runs, setRuns] = useState<ParsingRunSummary[] | null>(null);
	const [total, setTotal] = useState(0);
	const [page, setPage] = useState(0);
	const [query, setQuery] = useState('');
	const [status, setStatus] = useState('');
	const [reviewed, setReviewed] = useState('');
	const [error, setError] = useState<string | null>(null);
	const [reloadToken, setReloadToken] = useState(0);

	useEffect(() => {
		let cancelled = false;
		parsingApi
			.runs({
				limit: PAGE_SIZE,
				offset: page * PAGE_SIZE,
				q: query.trim() || undefined,
				status: status || undefined,
				reviewed: reviewed === '' ? undefined : reviewed === 'yes',
			})
			.then((response) => {
				if (cancelled) return;
				if (response.error || response.data == null) {
					setError(response.message ?? t('Failed to load parsing results.'));
					setRuns([]);
					return;
				}
				setRuns(response.data);
				setTotal(response.total);
			});
		return () => {
			cancelled = true;
		};
	}, [page, query, status, reviewed, reloadToken]);

	const remove = async (run: ParsingRunSummary) => {
		if (
			!window.confirm(
				t('Delete {name} and its parsed result? This cannot be undone.', {
					name: run.file_name ?? run.id,
				}),
			)
		) {
			return;
		}
		const response = await parsingApi.removeRun(run.id);
		if (response.error) {
			setError(response.message ?? t('Failed to delete the parsing instance.'));
			return;
		}
		setRuns((current) =>
			current == null ? current : current.filter((item) => item.id !== run.id),
		);
		setTotal((current) => Math.max(0, current - 1));
	};

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<div>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Result Library')}
					</h1>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'Every run keeps its source, output, model snapshot, and review state. Open one to inspect the page boxes or correct a block.',
						)}
					</p>
				</div>
				<Button
					theme={ButtonTheme.Secondary}
					size={Size.SMALL}
					onClick={() => setReloadToken((token) => token + 1)}
				>
					<Icon name={IconName.Refresh} className="mr-1 h-3 w-3" />
					{t('Refresh')}
				</Button>
			</header>

			<div className="flex flex-wrap items-center gap-2 px-6 pt-4">
				<input
					value={query}
					onChange={(event) => {
						setPage(0);
						setQuery(event.target.value);
					}}
					placeholder={t('Search results')}
					className="h-8 w-64 rounded-md border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
				/>
				<select
					value={status}
					onChange={(event) => {
						setPage(0);
						setStatus(event.target.value);
					}}
					className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
				>
					<option value="">{t('All statuses')}</option>
					{['queued', 'running', 'succeeded', 'failed', 'cancelled'].map((item) => (
						<option key={item} value={item}>
							{t(item)}
						</option>
					))}
				</select>
				<select
					value={reviewed}
					onChange={(event) => {
						setPage(0);
						setReviewed(event.target.value);
					}}
					className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
				>
					<option value="">{t('All review states')}</option>
					<option value="no">{t('Needs review')}</option>
					<option value="yes">{t('Reviewed')}</option>
				</select>
			</div>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}

			<div className="p-6">
				{runs == null ? (
					<div className="flex items-center gap-2 text-xs text-secondary">
						<Spinner />
						<span>{t('Loading parsing results…')}</span>
					</div>
				) : runs.length === 0 ? (
					<div className="rounded-lg border border-dashed border-zinc-300 px-6 py-12 text-center text-xs text-secondary dark:border-zinc-700">
						{t('No parsing results yet.')}{' '}
						<Link
							href="/parsing"
							className="text-[#5c9200] underline dark:text-[#a3e635]"
						>
							{t('Start a parsing task')}
						</Link>
					</div>
				) : (
					<div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="w-full border-collapse text-xs">
							<thead>
								<tr className="border-b border-zinc-200 bg-zinc-50 text-left text-[11px] text-secondary dark:border-zinc-700 dark:bg-zinc-900">
									<th className="px-3 py-2 font-medium">{t('File')}</th>
									<th className="px-3 py-2 font-medium">{t('Status')}</th>
									<th className="px-3 py-2 font-medium">{t('Profile')}</th>
									<th className="px-3 py-2 font-medium">{t('Pages')}</th>
									<th className="px-3 py-2 font-medium">{t('Duration')}</th>
									<th className="px-3 py-2 font-medium">{t('Review')}</th>
									<th className="px-3 py-2" />
								</tr>
							</thead>
							<tbody>
								{runs.map((run) => (
									<tr
										key={run.id}
										className="border-b border-zinc-100 last:border-b-0 hover:bg-zinc-50/70 dark:border-zinc-800 dark:hover:bg-zinc-900/60"
									>
										<td className="max-w-[340px] px-3 py-2">
											<Link
												href={`/parsing/library/${encodeURIComponent(run.id)}`}
												className="block truncate font-medium text-heading hover:underline dark:text-zinc-100"
											>
												{run.file_name ?? run.id}
											</Link>
											<span className="block truncate text-[10px] text-secondary dark:text-zinc-500">
												{run.task_name} · {formatInstanceTime(run.created)}
											</span>
										</td>
										<td className="px-3 py-2">
											<span
												className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass(run.status)}`}
											>
												{t(run.status)}
											</span>
										</td>
										<td className="px-3 py-2 text-body dark:text-zinc-300">
											{run.profile}
										</td>
										<td className="px-3 py-2 text-body dark:text-zinc-300">
											{run.page_count ?? '—'}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
											{formatDuration(run.processing_time_ms)}
										</td>
										<td className="px-3 py-2">
											{run.reviewed ? (
												<span className="text-[10px] text-emerald-600 dark:text-emerald-400">
													{t('Reviewed')}
												</span>
											) : (
												<span className="text-[10px] text-amber-600 dark:text-amber-400">
													{t('Needs review')}
												</span>
											)}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-right">
											<Link
												href={`/parsing/library/${encodeURIComponent(run.id)}`}
												className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
											>
												{t('Open')}
											</Link>
											<button
												type="button"
												aria-label={t('Delete')}
												className="ml-3 inline-flex align-middle text-secondary hover:text-red-600 dark:text-zinc-500"
												disabled={run.status === 'running'}
												onClick={() => void remove(run)}
											>
												<Icon
													name={IconName.Trash}
													className="h-3.5 w-3.5"
												/>
											</button>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				)}

				{total > PAGE_SIZE && (
					<div className="mt-4 flex items-center justify-between text-xs text-secondary">
						<span>
							{t('Page {0}', { 0: page + 1 })} · {total} {t('results')}
						</span>
						<div className="flex gap-2">
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								disabled={page === 0}
								onClick={() => setPage((current) => Math.max(0, current - 1))}
							>
								{t('Previous')}
							</Button>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								disabled={(page + 1) * PAGE_SIZE >= total}
								onClick={() => setPage((current) => current + 1)}
							>
								{t('Next')}
							</Button>
						</div>
					</div>
				)}
			</div>
		</div>
	);
};
