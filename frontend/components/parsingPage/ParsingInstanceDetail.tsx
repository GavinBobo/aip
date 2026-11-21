// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { parsingApi, type ParsingInstanceDetail } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { downloadText } from '@/lib/erd/download';
import { formatDuration, formatInstanceTime } from '@/lib/parsingInstances';

import { MarkdownContent } from './MarkdownContent';

type Tab = 'markdown' | 'json' | 'metadata' | 'original';

/** One stored run, read back from the backend — nothing is re-parsed here. */
export const ParsingInstanceDetailView = ({ document, run }: { document: string; run: string }) => {
	const router = useRouter();
	const [detail, setDetail] = useState<ParsingInstanceDetail | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<Tab>('markdown');
	const [removing, setRemoving] = useState(false);

	const id = `${document}/${run}`;

	useEffect(() => {
		let cancelled = false;
		parsingApi.instance(id).then((response) => {
			if (cancelled) return;
			if (response.error || response.data == null) {
				setError(response.message ?? t('This parsing instance could not be loaded.'));
				return;
			}
			setDetail(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, [id]);

	const remove = async () => {
		if (
			!window.confirm(
				t('Delete {name} and its parsed result? This cannot be undone.', {
					name: detail?.file_name ?? id,
				}),
			)
		) {
			return;
		}
		setRemoving(true);
		const response = await parsingApi.removeInstance(id);
		setRemoving(false);
		if (response.error) {
			setError(response.message ?? t('Failed to delete the parsing instance.'));
			return;
		}
		router.push('/parsing/instances');
	};

	const outputs = detail?.outputs ?? {};
	const markdown = typeof outputs.markdown === 'string' ? outputs.markdown : '';
	const json = outputs.json;
	const metadata = detail?.metadata ?? {};
	const sourceUrl = parsingApi.instanceSourceUrl(id);
	const sourceIsPdf = /\.pdf$/i.test(detail?.source_name ?? '');

	return (
		<div className="flex h-full min-h-0 flex-col bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<Link
					href="/parsing/instances"
					className="text-[11px] text-secondary underline hover:text-heading dark:text-zinc-400"
				>
					← {t('Batch Parsing Tasks')}
				</Link>
				<div className="mt-1 flex flex-wrap items-center justify-between gap-3">
					<div className="min-w-0">
						<h1 className="truncate text-base font-semibold text-heading dark:text-zinc-100">
							{detail?.file_name ?? id}
						</h1>
						<p className="mt-1 text-[11px] text-secondary dark:text-zinc-400">
							{formatInstanceTime(detail?.created ?? null)}
							{typeof metadata.page_num === 'number' && (
								<>
									{' · '}
									{/* One page reads badly as "1 pages"; the plural form is its own key. */}
									{metadata.page_num === 1
										? t('{count} page', { count: 1 })
										: t('{count} pages', { count: metadata.page_num })}
								</>
							)}
							{' · '}
							{formatDuration(
								typeof metadata.processing_time_ms === 'number'
									? metadata.processing_time_ms
									: null,
							)}
						</p>
					</div>
					<div className="flex shrink-0 items-center gap-2">
						<span className="text-[11px] text-secondary dark:text-zinc-500">{id}</span>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.SMALL}
							disabled={removing}
							onClick={() => void remove()}
						>
							{t('Delete')}
						</Button>
					</div>
				</div>
			</header>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}

			<div className="flex min-h-0 flex-1 flex-col p-6 pt-4">
				<section className="flex min-h-0 flex-1 flex-col rounded-lg border border-zinc-200 dark:border-zinc-700">
					<div className="flex items-center gap-1 border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
						{(
							[
								['markdown', 'Markdown'],
								['json', 'JSON'],
								['metadata', t('Metadata')],
								['original', t('Original file')],
							] as const
						).map(([key, label]) => (
							<button
								key={key}
								type="button"
								onClick={() => setTab(key)}
								className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
									tab === key
										? 'bg-[#76b900]/15 font-medium text-heading dark:text-zinc-100'
										: 'text-secondary hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
								}`}
							>
								{label}
							</button>
						))}
						<span className="flex-1" />
						{tab === 'original' && detail != null && (
							<a
								href={sourceUrl}
								target="_blank"
								rel="noreferrer"
								className="mr-2 text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
							>
								{t('Open in a new tab')}
							</a>
						)}
						{detail != null && (
							<>
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									disabled={markdown === ''}
									onClick={() =>
										downloadText(
											`${(detail.file_name ?? 'document').replace(/\.[^.]+$/, '')}.md`,
											markdown,
											'text/markdown;charset=utf-8',
										)
									}
								>
									{t('Download .md')}
								</Button>
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									disabled={json == null}
									onClick={() =>
										downloadText(
											`${(detail.file_name ?? 'document').replace(/\.[^.]+$/, '')}.json`,
											JSON.stringify(json ?? {}, null, 2),
											'application/json;charset=utf-8',
										)
									}
								>
									{t('Download .json')}
								</Button>
							</>
						)}
					</div>

					<div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-xs text-body dark:text-zinc-300">
						{detail == null && error == null && (
							<div className="flex items-center gap-2 text-secondary dark:text-zinc-400">
								<Spinner />
								<span>{t('Loading the parsing instance…')}</span>
							</div>
						)}
						{detail != null && tab === 'markdown' && (
							<MarkdownContent markdown={markdown} />
						)}
						{detail != null && tab === 'json' && (
							<pre className="overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black">
								{JSON.stringify(json ?? {}, null, 2)}
							</pre>
						)}
						{detail != null && tab === 'metadata' && (
							<dl className="space-y-1">
								{Object.entries(metadata).map(([key, value]) => (
									<div key={key} className="flex gap-2">
										<dt className="min-w-[140px] text-secondary dark:text-zinc-500">
											{key}
										</dt>
										<dd className="break-all">
											{typeof value === 'object'
												? JSON.stringify(value)
												: String(value)}
										</dd>
									</div>
								))}
							</dl>
						)}
						{detail != null &&
							tab === 'original' &&
							(sourceIsPdf ? (
								<iframe
									src={sourceUrl}
									title={detail.source_name ?? t('Original file')}
									className="h-[75vh] w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							) : (
								// eslint-disable-next-line @next/next/no-img-element -- served by this app's own asset route
								<img
									src={sourceUrl}
									alt={detail.source_name ?? ''}
									className="max-w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							))}
					</div>
				</section>
			</div>
		</div>
	);
};
