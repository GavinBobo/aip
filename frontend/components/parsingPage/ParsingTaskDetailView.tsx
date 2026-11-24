// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { parsingApi, type ParsingTask } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { formatDuration, formatInstanceTime } from '@/lib/parsingInstances';

const statusClass = (status: string): string => {
	if (status === 'succeeded') return 'bg-emerald-100 text-emerald-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'cancelled') return 'bg-zinc-200 text-zinc-600';
	if (status === 'running') return 'bg-[#76b900]/15 text-[#4b7a00]';
	return 'bg-zinc-100 text-secondary';
};

export const ParsingTaskDetailView = ({ taskId }: { taskId: string }) => {
	const router = useRouter();
	const [task, setTask] = useState<ParsingTask | null>(null);
	const [error, setError] = useState<string | null>(null);

	const load = useCallback(
		() =>
			parsingApi.task(taskId).then((response) => {
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to load parsing tasks.'));
					return;
				}
				setTask(response.data);
			}),
		[taskId],
	);

	useEffect(() => {
		void load();
	}, [load]);

	const taskStatus = task?.status;
	useEffect(() => {
		if (taskStatus == null || !['queued', 'running'].includes(taskStatus)) return;
		const timer = window.setInterval(() => {
			void load();
		}, 1500);
		return () => {
			window.clearInterval(timer);
		};
	}, [load, taskStatus]);

	const cancel = async () => {
		if (task == null) return;
		const response = await parsingApi.cancelTask(task.id);
		if (!response.error && response.data) setTask(response.data);
	};

	const retry = async (documentId: string) => {
		const response = await parsingApi.retryDocument(documentId);
		if (!response.error && response.data) setTask(response.data);
	};

	const remove = async () => {
		if (task == null) return;
		if (
			!window.confirm(
				t('Delete {name} and all of its results? This cannot be undone.', {
					name: task.name,
				}),
			)
		) {
			return;
		}
		const response = await parsingApi.deleteTask(task.id);
		if (response.error) {
			setError(response.message ?? t('Failed to delete the parsing task.'));
			return;
		}
		router.push('/parsing/tasks');
	};

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<Link
					href="/parsing/tasks"
					className="text-[11px] text-secondary underline hover:text-heading dark:text-zinc-400"
				>
					← {t('Parsing Tasks')}
				</Link>
				<div className="mt-1 flex flex-wrap items-center justify-between gap-3">
					<div>
						<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
							{task?.name ?? t('Loading parsing task…')}
						</h1>
						<p className="mt-1 text-[11px] text-secondary dark:text-zinc-400">
							{task != null && (
								<>
									{formatInstanceTime(task.created)} · {task.profile} ·{' '}
									{task.completed_documents + task.failed_documents}/
									{task.total_documents} {t('files')}
								</>
							)}
						</p>
					</div>
					<div className="flex items-center gap-2">
						{task != null && ['queued', 'running'].includes(task.status) && (
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								onClick={() => void cancel()}
							>
								{t('Cancel task')}
							</Button>
						)}
						{task != null && (
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								disabled={['queued', 'running'].includes(task.status)}
								onClick={() => void remove()}
							>
								{t('Delete')}
							</Button>
						)}
						<span
							className={`rounded px-2 py-0.5 text-[11px] ${statusClass(
								task?.status ?? 'queued',
							)}`}
						>
							{t(task?.status ?? 'queued')}
						</span>
					</div>
				</div>
			</header>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}

			<div className="p-6">
				{task == null ? (
					<div className="flex items-center gap-2 text-xs text-secondary">
						<Spinner />
						<span>{t('Loading parsing task…')}</span>
					</div>
				) : (
					<div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="w-full border-collapse text-xs">
							<thead>
								<tr className="border-b border-zinc-200 bg-zinc-50 text-left text-[11px] text-secondary dark:border-zinc-700 dark:bg-zinc-900">
									<th className="px-3 py-2 font-medium">{t('File')}</th>
									<th className="px-3 py-2 font-medium">{t('Status')}</th>
									<th className="px-3 py-2 font-medium">{t('Progress')}</th>
									<th className="px-3 py-2 font-medium">{t('Pages')}</th>
									<th className="px-3 py-2 font-medium">{t('Duration')}</th>
									<th className="px-3 py-2" />
								</tr>
							</thead>
							<tbody>
								{task.documents.map((document) => {
									const run = task.runs
										.filter((item) => item.document_id === document.id)
										.sort((a, b) =>
											(a.created ?? '').localeCompare(b.created ?? ''),
										)
										.at(-1);
									return (
										<tr
											key={document.id}
											className="border-b border-zinc-100 last:border-b-0 dark:border-zinc-800"
										>
											<td className="max-w-[320px] px-3 py-2">
												<span className="block truncate font-medium text-heading dark:text-zinc-100">
													{document.file_name}
												</span>
												{document.error_message && (
													<span className="block truncate text-[10px] text-red-600 dark:text-red-400">
														{document.error_code}:{' '}
														{document.error_message}
													</span>
												)}
											</td>
											<td className="px-3 py-2">
												<span
													className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass(
														document.status,
													)}`}
												>
													{t(document.status)}
												</span>
											</td>
											<td className="px-3 py-2 text-body dark:text-zinc-300">
												{document.progress_total > 0 ? (
													<div className="min-w-[110px]">
														<div className="flex justify-between text-[10px]">
															<span>
																{document.stage ?? t('processing')}
															</span>
															<span>
																{document.progress_percent}%
															</span>
														</div>
														<div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
															<div
																className="h-full rounded-full bg-[#76b900] transition-[width]"
																style={{
																	width: `${document.progress_percent}%`,
																}}
															/>
														</div>
													</div>
												) : (
													'—'
												)}
											</td>
											<td className="px-3 py-2 text-body dark:text-zinc-300">
												{document.page_count ?? '—'}
											</td>
											<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
												{formatDuration(document.processing_time_ms)}
											</td>
											<td className="whitespace-nowrap px-3 py-2 text-right">
												{run?.status === 'succeeded' && (
													<Link
														href={`/parsing/library/${encodeURIComponent(run.id)}`}
														className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
													>
														{t('Open result')}
													</Link>
												)}
												{document.status === 'failed' && (
													<button
														type="button"
														className="ml-3 text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
														onClick={() => void retry(document.id)}
													>
														{t('Retry')}
													</button>
												)}
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</div>
		</div>
	);
};
