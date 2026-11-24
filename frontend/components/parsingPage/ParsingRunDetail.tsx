// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { parsingApi, type ParsingRunDetail } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { formatDuration, formatInstanceTime } from '@/lib/parsingInstances';

import { MarkdownContent } from './MarkdownContent';

type PageBlock = {
	idx: number;
	type: string;
	bbox: number[];
	content: string;
	format: string;
	edited?: boolean;
};

type PageData = {
	page_num: number;
	page_size: { w: number; h: number };
	blocks: PageBlock[];
};

type Tab = 'layout' | 'markdown' | 'json' | 'metadata' | 'compare';

const BLOCK_COLORS: Record<string, string> = {
	Title: 'border-emerald-500 bg-emerald-500/10',
	Text: 'border-sky-500 bg-sky-500/10',
	Table: 'border-violet-500 bg-violet-500/10',
	Formula: 'border-amber-500 bg-amber-500/10',
	Picture: 'border-pink-500 bg-pink-500/10',
	Caption: 'border-teal-500 bg-teal-500/10',
	Footnote: 'border-zinc-400 bg-zinc-400/10',
};

const statusClass = (status: string): string => {
	if (status === 'succeeded') return 'bg-emerald-100 text-emerald-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'cancelled') return 'bg-zinc-200 text-zinc-600';
	if (status === 'running') return 'bg-[#76b900]/15 text-[#4b7a00]';
	return 'bg-zinc-100 text-secondary';
};

const pct = (value: number, total: number): string =>
	total > 0 ? `${(value / total) * 100}%` : '0%';

export const ParsingRunDetailView = ({ runId }: { runId: string }) => {
	const router = useRouter();
	const [run, setRun] = useState<ParsingRunDetail | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<Tab>('layout');
	const [pageIndex, setPageIndex] = useState(0);
	const [selected, setSelected] = useState<{ page: number; idx: number } | null>(null);
	const [draft, setDraft] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [notice, setNotice] = useState<string | null>(null);
	const [previous, setPrevious] = useState<ParsingRunDetail | null>(null);

	useEffect(() => {
		let cancelled = false;
		parsingApi.run(runId).then((response) => {
			if (cancelled) return;
			if (response.error || !response.data) {
				setError(response.message ?? t('This parsing instance could not be loaded.'));
				return;
			}
			setRun(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, [runId]);

	const pages = useMemo(() => {
		const json = run?.outputs.json as { pages?: PageData[] } | undefined;
		return json?.pages ?? [];
	}, [run]);
	const currentPage = pages[pageIndex] ?? pages[0];
	const pageRange = Array.isArray(run?.options.page_range)
		? (run.options.page_range as number[])
		: null;
	const sourcePageIndex = (pageNum: number): number =>
		pageRange != null && pageRange.length === 2
			? Math.max(0, pageRange[0] - 1 + pageNum)
			: pageNum;
	const currentBlock =
		selected != null && currentPage?.page_num === selected.page
			? (currentPage.blocks.find((block) => block.idx === selected.idx) ?? null)
			: null;

	const selectBlock = (page: number, block: PageBlock) => {
		setSelected({ page, idx: block.idx });
		setDraft(block.content);
	};

	const saveBlock = async () => {
		if (run == null || currentBlock == null || currentPage == null) return;
		setSaving(true);
		setNotice(null);
		const response = await parsingApi.updateBlocks(run.id, [
			{
				page: currentPage.page_num,
				idx: currentBlock.idx,
				content: draft ?? currentBlock.content,
				format: currentBlock.format,
			},
		]);
		setSaving(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to save the block.'));
			return;
		}
		setRun(response.data);
		setDraft(null);
		setNotice(t('Block saved.'));
	};

	const toggleReviewed = async () => {
		if (run == null) return;
		const response = await parsingApi.review(run.id, !run.reviewed);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to update the review state.'));
			return;
		}
		setRun(response.data);
	};

	const reparse = async () => {
		if (run == null) return;
		const response = await parsingApi.reparse(run.id);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to start the reparse.'));
			return;
		}
		router.push(`/parsing/tasks/${encodeURIComponent(response.data.id)}`);
	};

	const compare = async () => {
		if (run == null) return;
		const response = await parsingApi.previousRun(run.id);
		if (response.error) {
			setError(response.message ?? t('Failed to load the previous result.'));
			return;
		}
		if (response.data == null) {
			setError(t('No previous version to compare.'));
			return;
		}
		setPrevious(response.data);
		setTab('compare');
	};

	const remove = async () => {
		if (run == null) return;
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
		router.push('/parsing/library');
	};

	const markdown = typeof run?.outputs.markdown === 'string' ? run.outputs.markdown : '';

	return (
		<div className="flex h-full min-h-0 flex-col bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<Link
					href="/parsing/library"
					className="text-[11px] text-secondary underline hover:text-heading dark:text-zinc-400"
				>
					← {t('Result Library')}
				</Link>
				<div className="mt-1 flex flex-wrap items-center justify-between gap-3">
					<div className="min-w-0">
						<h1 className="truncate text-base font-semibold text-heading dark:text-zinc-100">
							{run?.file_name ?? t('Loading the parsing instance…')}
						</h1>
						<p className="mt-1 text-[11px] text-secondary dark:text-zinc-400">
							{run != null && (
								<>
									{formatInstanceTime(run.created)} · {run.profile} ·{' '}
									{run.page_count ?? '—'} {t('Pages')} ·{' '}
									{formatDuration(run.processing_time_ms)}
								</>
							)}
						</p>
					</div>
					{run != null && (
						<div className="flex flex-wrap items-center gap-2">
							<span
								className={`rounded px-2 py-0.5 text-[10px] ${statusClass(
									run.status,
								)}`}
							>
								{t(run.status)}
							</span>
							<span
								className={`rounded px-2 py-0.5 text-[10px] ${
									run.reviewed
										? 'bg-emerald-100 text-emerald-700'
										: 'bg-amber-100 text-amber-700'
								}`}
							>
								{run.reviewed ? t('Reviewed') : t('Needs review')}
							</span>
							<Button
								theme={run.reviewed ? ButtonTheme.Secondary : ButtonTheme.Primary}
								size={Size.SMALL}
								onClick={() => void toggleReviewed()}
							>
								{run.reviewed ? t('Reopen review') : t('Mark reviewed')}
							</Button>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								onClick={() => void reparse()}
							>
								{t('Reparse')}
							</Button>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								onClick={() => void compare()}
							>
								{t('Compare previous')}
							</Button>
							<a
								href={parsingApi.exportRunUrl(run.id)}
								className="inline-flex h-8 items-center rounded-md border border-zinc-300 px-2 text-[11px] no-underline dark:border-zinc-600"
							>
								{t('Export zip')}
							</a>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								disabled={run.status === 'running'}
								onClick={() => void remove()}
							>
								{t('Delete')}
							</Button>
						</div>
					)}
				</div>
			</header>

			{error != null && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</div>
			)}
			{notice != null && (
				<div className="mx-6 mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300">
					{notice}
				</div>
			)}
			{run?.status === 'failed' && (
				<div className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					<span className="font-medium">{run.error_code ?? 'PARSE_FAILED'}</span>
					{': '}
					{run.error_message ?? t('This document could not be parsed.')}
				</div>
			)}

			<div className="flex min-h-0 flex-1 flex-col p-6 pt-4">
				{run == null ? (
					<div className="flex items-center gap-2 text-xs text-secondary">
						<Spinner />
						<span>{t('Loading the parsing instance…')}</span>
					</div>
				) : (
					<section className="flex min-h-0 flex-1 flex-col rounded-lg border border-zinc-200 dark:border-zinc-700">
						<div className="flex flex-wrap items-center gap-1 border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
							{(
								[
									['layout', t('Layout')],
									['markdown', 'Markdown'],
									['json', 'JSON'],
									['metadata', t('Metadata')],
									...(previous != null
										? ([['compare', t('Compare')]] as const)
										: []),
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
							{run.review_note && (
								<span className="max-w-[360px] truncate text-[10px] text-secondary">
									{run.review_note}
								</span>
							)}
						</div>

						{tab === 'layout' && (
							<div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-zinc-200 lg:grid-cols-[minmax(0,1fr)_340px] lg:divide-x lg:divide-y-0 dark:divide-zinc-700">
								<div className="flex min-h-0 flex-col">
									<div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 text-[11px] dark:border-zinc-700">
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											disabled={pageIndex === 0}
											onClick={() => {
												setPageIndex((current) => Math.max(0, current - 1));
												setSelected(null);
											}}
										>
											{t('Previous')}
										</Button>
										<select
											value={pageIndex}
											onChange={(event) => {
												setPageIndex(Number(event.target.value));
												setSelected(null);
											}}
											className="h-7 rounded-md border border-zinc-300 bg-white px-2 text-[11px] dark:border-zinc-600 dark:bg-zinc-900"
										>
											{pages.map((page, index) => (
												<option key={page.page_num} value={index}>
													{t('Page {0}', {
														0: sourcePageIndex(page.page_num) + 1,
													})}
												</option>
											))}
										</select>
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											disabled={pageIndex >= pages.length - 1}
											onClick={() => {
												setPageIndex((current) =>
													Math.min(pages.length - 1, current + 1),
												);
												setSelected(null);
											}}
										>
											{t('Next')}
										</Button>
										<span className="flex-1" />
										<a
											href={parsingApi.runPageUrl(
												run.id,
												sourcePageIndex(currentPage?.page_num ?? 0),
											)}
											target="_blank"
											rel="noreferrer"
											className="text-[#5c9200] underline dark:text-[#a3e635]"
										>
											{t('Open page image')}
										</a>
									</div>
									<div className="min-h-0 flex-1 overflow-auto p-3">
										{currentPage == null ? (
											<p className="text-xs text-secondary">
												{t('No page data in this result.')}
											</p>
										) : (
											<div className="relative mx-auto w-fit max-w-full">
												{/* eslint-disable-next-line @next/next/no-img-element -- rendered by this app's own page route */}
												<img
													src={parsingApi.runPageUrl(
														run.id,
														sourcePageIndex(currentPage.page_num),
													)}
													alt={t('Page {0}', {
														0:
															sourcePageIndex(currentPage.page_num) +
															1,
													})}
													className="max-w-full rounded border border-zinc-200 dark:border-zinc-700"
												/>
												{currentPage.blocks.map((block) => (
													<button
														key={block.idx}
														type="button"
														aria-label={`${block.type} ${block.idx}`}
														onClick={() =>
															selectBlock(currentPage.page_num, block)
														}
														className={`absolute cursor-pointer border-2 transition-colors ${
															BLOCK_COLORS[block.type] ??
															'border-zinc-400 bg-zinc-400/10'
														} ${
															selected?.page ===
																currentPage.page_num &&
															selected.idx === block.idx
																? 'ring-2 ring-[#76b900] ring-offset-1'
																: ''
														}`}
														style={{
															left: pct(
																block.bbox[0],
																currentPage.page_size.w,
															),
															top: pct(
																block.bbox[1],
																currentPage.page_size.h,
															),
															width: pct(
																block.bbox[2] - block.bbox[0],
																currentPage.page_size.w,
															),
															height: pct(
																block.bbox[3] - block.bbox[1],
																currentPage.page_size.h,
															),
														}}
													/>
												))}
											</div>
										)}
									</div>
								</div>

								<div className="flex min-h-0 flex-col">
									<div className="border-b border-zinc-200 px-3 py-2 text-[11px] font-medium text-secondary dark:border-zinc-700">
										{t('Blocks')} · {currentPage?.blocks.length ?? 0}
									</div>
									<div className="max-h-[32vh] overflow-y-auto border-b border-zinc-200 p-2 dark:border-zinc-700">
										{(currentPage?.blocks ?? []).map((block) => (
											<button
												key={block.idx}
												type="button"
												onClick={() =>
													selectBlock(currentPage.page_num, block)
												}
												className={`mb-1 block w-full rounded-md px-2 py-1.5 text-left text-[11px] ${
													selected?.page === currentPage.page_num &&
													selected.idx === block.idx
														? 'bg-[#76b900]/15 text-heading'
														: 'hover:bg-zinc-50 dark:hover:bg-zinc-800'
												}`}
											>
												<span className="block font-medium">
													{block.type} #{block.idx}
													{block.edited && (
														<span className="ml-1 text-[9px] text-[#5c9200]">
															{t('edited')}
														</span>
													)}
												</span>
												<span className="mt-0.5 line-clamp-2 block text-secondary dark:text-zinc-400">
													{block.content.slice(0, 160) || t('empty')}
												</span>
											</button>
										))}
									</div>
									<div className="min-h-0 flex-1 p-3">
										{currentBlock == null ? (
											<p className="text-[11px] text-secondary">
												{t('Select a block to inspect or edit it.')}
											</p>
										) : (
											<div className="space-y-2">
												<p className="text-[11px] font-medium">
													{currentBlock.type} #{currentBlock.idx}
												</p>
												<textarea
													value={draft ?? currentBlock.content}
													onChange={(event) =>
														setDraft(event.target.value)
													}
													rows={8}
													className="w-full rounded-md border border-zinc-300 bg-white p-2 font-mono text-[11px] leading-relaxed dark:border-zinc-600 dark:bg-zinc-900"
												/>
												<Button
													theme={ButtonTheme.Primary}
													size={Size.SMALL}
													loading={saving}
													disabled={
														saving ||
														(draft ?? currentBlock.content) ===
															currentBlock.content
													}
													onClick={() => void saveBlock()}
												>
													{t('Save block')}
												</Button>
											</div>
										)}
									</div>
								</div>
							</div>
						)}

						{tab === 'markdown' && (
							<div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-xs text-body dark:text-zinc-300">
								<MarkdownContent markdown={markdown} />
							</div>
						)}
						{tab === 'json' && (
							<div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
								<pre className="overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black">
									{JSON.stringify(run.outputs.json ?? {}, null, 2)}
								</pre>
							</div>
						)}
						{tab === 'metadata' && (
							<div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 text-xs">
								<div>
									<h3 className="mb-2 text-xs font-semibold">{t('Quality')}</h3>
									<dl className="grid grid-cols-2 gap-1">
										{Object.entries(run.quality).map(([key, value]) => (
											<div key={key} className="flex gap-2">
												<dt className="min-w-[140px] text-secondary">
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
								</div>
								<div>
									<h3 className="mb-2 text-xs font-semibold">{t('Snapshot')}</h3>
									<pre className="overflow-x-auto rounded-lg bg-zinc-100 p-3 text-[10px] dark:bg-zinc-900">
										{JSON.stringify(
											{
												model: run.model_snapshot,
												layout: run.layout_snapshot,
												options: run.options,
												pipeline_version: run.pipeline_version,
											},
											null,
											2,
										)}
									</pre>
								</div>
								<div>
									<h3 className="mb-2 text-xs font-semibold">
										{t('Result metadata')}
									</h3>
									<pre className="overflow-x-auto rounded-lg bg-zinc-100 p-3 text-[10px] dark:bg-zinc-900">
										{JSON.stringify(run.metadata, null, 2)}
									</pre>
								</div>
							</div>
						)}
						{tab === 'compare' && previous != null && (
							<div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto divide-y divide-zinc-200 lg:grid-cols-2 lg:divide-x lg:divide-y-0 dark:divide-zinc-700">
								<div className="min-w-0 px-5 py-4">
									<h3 className="mb-2 text-xs font-semibold">
										{t('Previous version')} ·{' '}
										{formatInstanceTime(previous.created)}
									</h3>
									<MarkdownContent
										markdown={
											typeof previous.outputs.markdown === 'string'
												? previous.outputs.markdown
												: ''
										}
									/>
								</div>
								<div className="min-w-0 px-5 py-4">
									<h3 className="mb-2 text-xs font-semibold">
										{t('Current version')} · {formatInstanceTime(run.created)}
									</h3>
									<MarkdownContent markdown={markdown} />
								</div>
							</div>
						)}
					</section>
				)}
			</div>
		</div>
	);
};
