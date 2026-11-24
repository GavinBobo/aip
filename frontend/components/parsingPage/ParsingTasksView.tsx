// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

import { parsingApi, type ParsingTask } from '@/api/parsing';
import { Button } from '@/common/Button';
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

export const ParsingTasksView = () => {
	const [tasks, setTasks] = useState<ParsingTask[] | null>(null);
	const [total, setTotal] = useState(0);
	const [page, setPage] = useState(0);
	const [query, setQuery] = useState('');
	const [status, setStatus] = useState('');
	const [error, setError] = useState<string | null>(null);
	const [reloadToken, setReloadToken] = useState(0);

	useEffect(() => {
		let cancelled = false;
		parsingApi
			.tasks({
				limit: PAGE_SIZE,
				offset: page * PAGE_SIZE,
				q: query.trim() || undefined,
				status: status || undefined,
			})
			.then((response) => {
				if (cancelled) return;
				if (response.error || response.data == null) {
					setError(response.message ?? t('Failed to load parsing tasks.'));
					setTasks([]);
					return;
				}
				setTasks(response.data);
				setTotal(response.total);
			});
		return () => {
			cancelled = true;
		};
	}, [page, query, status, reloadToken]);

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<div>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Parsing Tasks')}
					</h1>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'Every batch is durable. Open one to see file-level progress, retry failures, and jump to its results.',
						)}
					</p>
				</div>
				<Link
					href="/parsing"
					className="inline-flex h-8 items-center rounded-lg bg-[#76b900] px-3 text-xs font-medium text-black transition-colors hover:bg-[#86c900]"
				>
					{t('New parsing task')}
				</Link>
			</header>

			<div className="flex flex-wrap items-center gap-2 px-6 pt-4">
				<input
					value={query}
					onChange={(event) => {
						setPage(0);
						setQuery(event.target.value);
					}}
					placeholder={t('Search tasks')}
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
				<Button
					theme={ButtonTheme.Secondary}
					size={Size.SMALL}
					onClick={() => setReloadToken((token) => token + 1)}
				>
					{t('Refresh')}
				</Button>
			</div>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}

			<div className="p-6">
				{tasks == null ? (
					<div className="flex items-center gap-2 text-xs text-secondary">
						<Spinner />
						<span>{t('Loading parsing tasks…')}</span>
					</div>
				) : tasks.length === 0 ? (
					<div className="rounded-lg border border-dashed border-zinc-300 px-6 py-12 text-center text-xs text-secondary dark:border-zinc-700">
						{t('No parsing tasks yet.')}{' '}
						<Link
							href="/parsing"
							className="text-[#5c9200] underline dark:text-[#a3e635]"
						>
							{t('Create the first task')}
						</Link>
					</div>
				) : (
					<div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="w-full border-collapse text-xs">
							<thead>
								<tr className="border-b border-zinc-200 bg-zinc-50 text-left text-[11px] text-secondary dark:border-zinc-700 dark:bg-zinc-900">
									<th className="px-3 py-2 font-medium">{t('Task')}</th>
									<th className="px-3 py-2 font-medium">{t('Status')}</th>
									<th className="px-3 py-2 font-medium">{t('Files')}</th>
									<th className="px-3 py-2 font-medium">{t('Parsed at')}</th>
									<th className="px-3 py-2 font-medium">{t('Duration')}</th>
									<th className="px-3 py-2" />
								</tr>
							</thead>
							<tbody>
								{tasks.map((task) => (
									<tr
										key={task.id}
										className="border-b border-zinc-100 last:border-b-0 hover:bg-zinc-50/70 dark:border-zinc-800 dark:hover:bg-zinc-900/60"
									>
										<td className="max-w-[360px] px-3 py-2">
											<Link
												href={`/parsing/tasks/${encodeURIComponent(task.id)}`}
												className="block truncate font-medium text-heading hover:underline dark:text-zinc-100"
											>
												{task.name}
											</Link>
											<span className="block truncate text-[10px] text-secondary dark:text-zinc-500">
												{task.profile} · {task.created_by ?? '—'}
											</span>
										</td>
										<td className="px-3 py-2">
											<span
												className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass(task.status)}`}
											>
												{t(task.status)}
											</span>
										</td>
										<td className="px-3 py-2 text-body dark:text-zinc-300">
											{task.completed_documents + task.failed_documents}/
											{task.total_documents}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
											{formatInstanceTime(task.created)}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
											{formatDuration(
												task.finished && task.started
													? new Date(task.finished).getTime() -
															new Date(task.started).getTime()
													: null,
											)}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-right">
											<Link
												href={`/parsing/tasks/${encodeURIComponent(task.id)}`}
												className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
											>
												{t('Open')}
											</Link>
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
							{t('Page {0}', { 0: page + 1 })} · {total} {t('tasks')}
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
