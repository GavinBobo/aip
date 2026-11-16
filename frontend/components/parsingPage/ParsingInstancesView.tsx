// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

import { parsingApi, type ParsingInstance } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { formatDuration, formatInstanceTime, instanceHref } from '@/lib/parsingInstances';

/** How many recent runs the list asks for. Older ones stay on disk. */
const LIST_LIMIT = 100;

export const ParsingInstancesView = () => {
	const [instances, setInstances] = useState<ParsingInstance[] | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [deleting, setDeleting] = useState<string | null>(null);
	/** Bumped by the Refresh button; the effect below is what fetches. */
	const [reloadToken, setReloadToken] = useState(0);

	useEffect(() => {
		let cancelled = false;
		parsingApi.instances(LIST_LIMIT).then((response) => {
			if (cancelled) return;
			if (response.error || response.data == null) {
				setError(response.message ?? t('Failed to load parsing instances.'));
				setInstances([]);
				return;
			}
			setInstances(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, [reloadToken]);

	const refresh = () => {
		setError(null);
		setInstances(null);
		setReloadToken((token) => token + 1);
	};

	const remove = async (instance: ParsingInstance) => {
		if (
			!window.confirm(
				t('Delete {name} and its parsed result? This cannot be undone.', {
					name: instance.file_name ?? instance.id,
				}),
			)
		) {
			return;
		}
		setDeleting(instance.id);
		const response = await parsingApi.removeInstance(instance.id);
		setDeleting(null);
		if (response.error) {
			setError(response.message ?? t('Failed to delete the parsing instance.'));
			return;
		}
		setInstances((current) =>
			current == null ? current : current.filter((item) => item.id !== instance.id),
		);
	};

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<div>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Parsing Instances')}
					</h1>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'Every parse is kept with its source file and answer, newest first. Open one to read the Markdown, the JSON, or the file it came from.',
						)}
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.SMALL}
						onClick={refresh}
						disabled={instances == null}
					>
						<Icon name={IconName.Refresh} className="mr-1 h-3 w-3" />
						{t('Refresh')}
					</Button>
					<Link
						href="/parsing/batch"
						className="inline-flex h-8 items-center rounded-lg bg-[#76b900] px-3 text-xs font-medium text-black transition-colors hover:bg-[#86c900]"
					>
						{t('Create Batch Parsing Task')}
					</Link>
				</div>
			</header>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}

			<div className="p-6">
				{instances == null ? (
					<div className="flex items-center gap-2 text-xs text-secondary dark:text-zinc-400">
						<Spinner />
						<span>{t('Loading parsing instances…')}</span>
					</div>
				) : instances.length === 0 ? (
					<div className="rounded-lg border border-dashed border-zinc-300 px-6 py-12 text-center dark:border-zinc-700">
						<p className="text-xs text-secondary dark:text-zinc-400">
							{t('No parsing instances yet.')}
						</p>
						<Link
							href="/parsing/batch"
							className="mt-3 inline-block text-xs text-[#5c9200] underline dark:text-[#a3e635]"
						>
							{t('Create the first batch task')}
						</Link>
					</div>
				) : (
					<div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="w-full border-collapse text-xs">
							<thead>
								<tr className="border-b border-zinc-200 bg-zinc-50 text-left text-[11px] text-secondary dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
									<th className="px-3 py-2 font-medium">{t('File')}</th>
									<th className="px-3 py-2 font-medium">{t('Parsed at')}</th>
									<th className="px-3 py-2 font-medium">{t('Pages')}</th>
									<th className="px-3 py-2 font-medium">{t('Duration')}</th>
									<th className="px-3 py-2 font-medium">{t('Markdown')}</th>
									<th className="px-3 py-2" />
								</tr>
							</thead>
							<tbody>
								{instances.map((instance) => (
									<tr
										key={instance.id}
										className="border-b border-zinc-100 last:border-b-0 hover:bg-zinc-50/70 dark:border-zinc-800 dark:hover:bg-zinc-900/60"
									>
										<td className="max-w-[320px] px-3 py-2">
											<Link
												href={instanceHref(instance.id)}
												className="block truncate font-medium text-heading hover:underline dark:text-zinc-100"
											>
												{instance.file_name ?? instance.id}
											</Link>
											<span className="block truncate text-[10px] text-secondary dark:text-zinc-500">
												{instance.id}
											</span>
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
											{formatInstanceTime(instance.created)}
										</td>
										<td className="px-3 py-2 text-body dark:text-zinc-300">
											{instance.page_num ?? '—'}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-body dark:text-zinc-300">
											{formatDuration(instance.processing_time_ms)}
										</td>
										<td className="px-3 py-2">
											{instance.has_markdown ? (
												<Icon
													name={IconName.Check}
													className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400"
												/>
											) : (
												<span className="text-secondary dark:text-zinc-500">
													—
												</span>
											)}
										</td>
										<td className="whitespace-nowrap px-3 py-2 text-right">
											<Link
												href={instanceHref(instance.id)}
												className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
											>
												{t('Open')}
											</Link>
											<button
												type="button"
												aria-label={t('Delete')}
												className="ml-3 inline-flex align-middle text-secondary hover:text-red-600 disabled:opacity-50 dark:text-zinc-500"
												disabled={deleting === instance.id}
												onClick={() => void remove(instance)}
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
			</div>
		</div>
	);
};
