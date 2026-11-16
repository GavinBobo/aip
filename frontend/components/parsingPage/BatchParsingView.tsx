// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';

import { parsingApi, type ParsingCapabilities, type ParsingJob } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { downloadText } from '@/lib/erd/download';
import { instanceHref } from '@/lib/parsingInstances';

import { MarkdownContent } from './MarkdownContent';

type Phase = 'idle' | 'submitting' | 'running' | 'success' | 'failed';

/** Poll interval for running jobs. The pipeline is seconds-to-minutes. */
const POLL_MS = 1200;

/** Element types OXR can emit, with the label each option carries in the form. */
const ELEMENT_LABELS: Record<string, Record<string, string>> = {
	image: { url: 'URL', base64: 'Base64', none: '不输出' },
	formula: { latex: 'LaTeX', mathml: 'MathML', ascii: 'ASCII' },
	table: { html: 'HTML', markdown: 'Markdown' },
	cs: { smiles: 'SMILES', image: '图片' },
};

const MODEL_OPTION_LABELS: Record<string, string> = {
	temperature: 'temperature',
	top_p: 'top_p',
	repetition_penalty: 'repetition_penalty',
};

/** One queued file: the upload, the job watching it, and its answer. */
type BatchItem = {
	/** Client-side identity; the server's task id arrives after submission. */
	key: string;
	file: File;
	phase: Phase;
	job: ParsingJob | null;
	error: string | null;
};

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const fileKey = (file: File): string => `${file.name}:${file.size}:${file.lastModified}`;

const isAlive = (item: BatchItem): boolean =>
	item.job != null && (item.job.status === 'queuing' || item.job.status === 'processing');

const phaseOf = (job: ParsingJob): Phase => {
	if (job.status === 'success') return 'success';
	if (job.status === 'failed') return 'failed';
	return 'running';
};

/** The stored instance a finished job produced, if the backend kept one. */
const instanceIdOf = (job: ParsingJob | null): string | null => {
	const id = job?.metadata?.instance_id;
	return typeof id === 'string' && id !== '' ? id : null;
};

const STATUS_STYLE: Record<Phase, string> = {
	idle: 'bg-zinc-100 text-secondary dark:bg-zinc-800 dark:text-zinc-400',
	submitting: 'bg-[#76b900]/15 text-[#4b7a00] dark:text-[#a3e635]',
	running: 'bg-[#76b900]/15 text-[#4b7a00] dark:text-[#a3e635]',
	success: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300',
	failed: 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300',
};

export const BatchParsingView = () => {
	const [capabilities, setCapabilities] = useState<ParsingCapabilities | null>(null);
	const [items, setItems] = useState<BatchItem[]>([]);
	const [selectedKey, setSelectedKey] = useState<string | null>(null);
	const [tab, setTab] = useState<'markdown' | 'json' | 'metadata' | 'original'>('markdown');
	const [dragging, setDragging] = useState(false);
	const inputRef = useRef<HTMLInputElement>(null);

	// The 原始文件 tab shows the selected upload. The URL is created in the
	// handlers that change the selection rather than in an effect: an effect
	// would cost a render that exists only to hold a URL, and the cleanup is the
	// same one call. The ref mirrors the state so a handler can ask "was
	// something selected?" without reading a stale closure.
	const selectedKeyRef = useRef<string | null>(null);
	const previewUrlRef = useRef<string | null>(null);
	const [previewUrl, setPreviewUrl] = useState<string | null>(null);

	const showFile = useCallback((key: string | null, file: File | null) => {
		if (previewUrlRef.current != null) URL.revokeObjectURL(previewUrlRef.current);
		const url = file == null ? null : URL.createObjectURL(file);
		previewUrlRef.current = url;
		selectedKeyRef.current = key;
		setPreviewUrl(url);
		setSelectedKey(key);
	}, []);

	useEffect(
		() => () => {
			if (previewUrlRef.current != null) URL.revokeObjectURL(previewUrlRef.current);
		},
		[],
	);

	const [outputFormats, setOutputFormats] = useState<string[]>(['markdown', 'json']);
	const [keepHeaderFooter, setKeepHeaderFooter] = useState(false);
	const [elementFormats, setElementFormats] = useState<Record<string, string>>({});
	const [modelOptions, setModelOptions] = useState<Record<string, string>>({});

	useEffect(() => {
		let cancelled = false;
		parsingApi.capabilities().then((response) => {
			if (cancelled || response.error || !response.data) return;
			setCapabilities(response.data);
			setElementFormats(response.data.element_format_defaults ?? {});
		});
		return () => {
			cancelled = true;
		};
	}, []);

	// The poller reads the queue through a ref so the interval is created once
	// per "something is running" transition rather than once per status tick.
	const itemsRef = useRef(items);
	useEffect(() => {
		itemsRef.current = items;
	}, [items]);

	const anyAlive = items.some(isAlive);
	useEffect(() => {
		if (!anyAlive) return;

		const timer = window.setInterval(() => {
			for (const item of itemsRef.current.filter(isAlive)) {
				const taskId = item.job?.task_id;
				if (taskId == null) continue;
				parsingApi.job(taskId).then((response) => {
					setItems((current) =>
						current.map((entry) => {
							if (entry.key !== item.key) return entry;
							if (response.error || !response.data) {
								return {
									...entry,
									phase: 'failed',
									error: response.message ?? t('Failed to read the job status.'),
								};
							}
							return {
								...entry,
								job: response.data,
								phase: phaseOf(response.data),
								error:
									response.data.status === 'failed' ? response.data.error : null,
							};
						}),
					);
				});
			}
		}, POLL_MS);
		return () => window.clearInterval(timer);
	}, [anyAlive]);

	const addFiles = useCallback(
		(picked: FileList | null) => {
			if (picked == null) return;
			const incoming = Array.from(picked);
			if (incoming.length === 0) return;

			setItems((current) => {
				const known = new Set(current.map((item) => item.key));
				const added = incoming
					.filter((file) => !known.has(fileKey(file)))
					.map((file) => ({
						key: fileKey(file),
						file,
						phase: 'idle' as Phase,
						job: null,
						error: null,
					}));
				if (added.length === 0) return current;
				return [...current, ...added];
			});
			// New files are what the user just did, so the preview follows them.
			if (selectedKeyRef.current == null) showFile(fileKey(incoming[0]), incoming[0]);
		},
		[showFile],
	);

	const removeItem = (key: string) => {
		setItems((current) => current.filter((item) => item.key !== key));
		if (selectedKeyRef.current === key) showFile(null, null);
	};

	const selected = items.find((item) => item.key === selectedKey) ?? null;

	const start = async () => {
		const pending = items.filter((item) => item.phase === 'idle' || item.phase === 'failed');
		if (pending.length === 0) return;

		// Submitted one at a time: each POST only queues the job, so this is fast,
		// and a failure on file 3 must not lose what files 1 and 2 already queued.
		for (const item of pending) {
			setItems((current) =>
				current.map((entry) =>
					entry.key === item.key
						? { ...entry, phase: 'submitting', error: null, job: null }
						: entry,
				),
			);
			const form = new FormData();
			form.append('file', item.file);
			for (const format of outputFormats) form.append('output_formats', format);
			form.append('feature_config', JSON.stringify({ keep_header_footer: keepHeaderFooter }));
			form.append('element_formats', JSON.stringify(elementFormats));
			const numeric = Object.fromEntries(
				Object.entries(modelOptions)
					.filter(([, value]) => value.trim() !== '')
					.map(([key, value]) => [key, Number(value)]),
			);
			if (Object.keys(numeric).length > 0) form.append('extra', JSON.stringify(numeric));

			const response = await parsingApi.submit(form);
			setItems((current) =>
				current.map((entry) => {
					if (entry.key !== item.key) return entry;
					if (response.error || !response.data) {
						return {
							...entry,
							phase: 'failed',
							error: response.message ?? t('Failed to submit the document.'),
						};
					}
					return { ...entry, job: response.data, phase: 'running' };
				}),
			);
		}
	};

	const busy = items.some((item) => item.phase === 'submitting' || item.phase === 'running');
	const outputs = selected?.job?.result?.outputs ?? {};
	const markdown = typeof outputs.markdown === 'string' ? outputs.markdown : '';
	const json = outputs.json;
	const metadata = selected?.job?.metadata ?? {};
	const instanceId = instanceIdOf(selected?.job ?? null);
	const selectedIsPdf =
		selected != null &&
		(/\.pdf$/i.test(selected.file.name) || selected.file.type === 'application/pdf');

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
					{t('Create Batch Parsing Task')}
				</h1>
				<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
					{t(
						'Queue several PDFs or document images at once. Each file becomes one parsing instance, kept in the list on the left. The recognition and layout endpoints are configured in Model Settings.',
					)}
				</p>
			</header>

			{capabilities != null && !capabilities.ready && (
				<div className="mx-6 mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
					{t('The parser is not configured yet.')}{' '}
					<Link className="underline" href="/settings/model-settings">
						{t('Open Model Settings')}
					</Link>
				</div>
			)}

			<div className="grid flex-1 gap-5 p-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
				<section className="space-y-4">
					<div
						onDragOver={(event) => {
							event.preventDefault();
							setDragging(true);
						}}
						onDragLeave={() => setDragging(false)}
						onDrop={(event) => {
							event.preventDefault();
							setDragging(false);
							addFiles(event.dataTransfer.files);
						}}
						className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
							dragging
								? 'border-[#76b900] bg-[#76b900]/5'
								: 'border-zinc-300 dark:border-zinc-700'
						}`}
					>
						<span className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-100 text-secondary dark:bg-zinc-800 dark:text-zinc-300">
							<Icon name={IconName.Spreadsheet} className="h-4 w-4" />
						</span>
						<p className="text-xs text-body dark:text-zinc-300">
							{t('Drop PDFs or images here, or')}{' '}
							<button
								type="button"
								className="text-[#5c9200] underline dark:text-[#a3e635]"
								onClick={() => inputRef.current?.click()}
							>
								{t('choose files')}
							</button>
						</p>
						<input
							ref={inputRef}
							type="file"
							multiple
							accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
							className="hidden"
							onChange={(event) => {
								addFiles(event.target.files);
								// Cleared so choosing the same file twice fires `change` again.
								event.target.value = '';
							}}
						/>
					</div>

					{items.length > 0 && (
						<div className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
							<div className="flex items-center justify-between">
								<h2 className="text-xs font-semibold text-heading dark:text-zinc-100">
									{t('Queue')} · {items.length}
								</h2>
								<button
									type="button"
									className="text-[11px] text-secondary underline hover:text-heading disabled:opacity-50 dark:text-zinc-400"
									onClick={() => {
										setItems([]);
										showFile(null, null);
									}}
									disabled={busy}
								>
									{t('Clear the queue')}
								</button>
							</div>
							<ul className="max-h-64 space-y-1 overflow-y-auto">
								{items.map((item) => (
									<li key={item.key}>
										<div
											className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${
												item.key === selectedKey
													? 'bg-[#76b900]/10 ring-1 ring-[#76b900]/30'
													: 'hover:bg-zinc-50 dark:hover:bg-zinc-800/60'
											}`}
										>
											<button
												type="button"
												className="min-w-0 flex-1 text-left"
												onClick={() => showFile(item.key, item.file)}
											>
												<span className="block truncate text-xs text-body dark:text-zinc-300">
													{item.file.name}
												</span>
												<span className="block truncate text-[10px] text-secondary dark:text-zinc-500">
													{formatBytes(item.file.size)}
													{item.error != null ? ` · ${item.error}` : ''}
												</span>
											</button>
											<span
												className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[item.phase]}`}
											>
												{t(
													item.phase === 'idle'
														? 'ready'
														: item.phase === 'submitting'
															? 'submitting'
															: item.phase === 'running'
																? item.job?.status === 'queuing'
																	? 'queuing'
																	: 'processing'
																: item.phase,
												)}
											</span>
											{!busy && (
												<button
													type="button"
													aria-label={t('Remove from the queue')}
													className="text-secondary hover:text-red-600 dark:text-zinc-500"
													onClick={() => removeItem(item.key)}
												>
													<Icon
														name={IconName.Close}
														className="h-3 w-3"
													/>
												</button>
											)}
										</div>
									</li>
								))}
							</ul>
						</div>
					)}

					<div className="space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
						<h2 className="text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Output')}
						</h2>
						<div className="flex flex-wrap gap-4 text-xs text-body dark:text-zinc-300">
							{(capabilities?.output_formats ?? ['markdown', 'json']).map(
								(format) => (
									<label key={format} className="flex items-center gap-1.5">
										<input
											type="checkbox"
											checked={outputFormats.includes(format)}
											onChange={(event) =>
												setOutputFormats((current) =>
													event.target.checked
														? [...current, format]
														: current.filter((item) => item !== format),
												)
											}
										/>
										{format}
									</label>
								),
							)}
							<label className="flex items-center gap-1.5">
								<input
									type="checkbox"
									checked={keepHeaderFooter}
									onChange={(event) => setKeepHeaderFooter(event.target.checked)}
								/>
								{t('Keep header and footer')}
							</label>
						</div>

						<h2 className="pt-1 text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Element formats')}
						</h2>
						<div className="grid grid-cols-2 gap-2">
							{Object.entries(capabilities?.element_formats ?? {}).map(
								([element, values]) => (
									<label key={element} className="flex flex-col gap-1">
										<span className="text-[11px] text-secondary dark:text-zinc-400">
											{element}
										</span>
										<select
											value={elementFormats[element] ?? values[0]}
											onChange={(event) =>
												setElementFormats((current) => ({
													...current,
													[element]: event.target.value,
												}))
											}
											className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300"
										>
											{values.map((value) => (
												<option key={value} value={value}>
													{ELEMENT_LABELS[element]?.[value] ?? value}
												</option>
											))}
										</select>
									</label>
								),
							)}
						</div>

						<h2 className="pt-1 text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Model parameters (optional)')}
						</h2>
						<div className="grid grid-cols-3 gap-2">
							{(capabilities?.model_options ?? Object.keys(MODEL_OPTION_LABELS)).map(
								(option) => (
									<label key={option} className="flex flex-col gap-1">
										<span className="text-[11px] text-secondary dark:text-zinc-400">
											{MODEL_OPTION_LABELS[option] ?? option}
										</span>
										<input
											type="number"
											step={0.05}
											value={modelOptions[option] ?? ''}
											onChange={(event) =>
												setModelOptions((current) => ({
													...current,
													[option]: event.target.value,
												}))
											}
											placeholder={t('default')}
											className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300"
										/>
									</label>
								),
							)}
						</div>
					</div>

					<div className="flex items-center gap-3">
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							loading={busy}
							disabled={items.length === 0 || busy || outputFormats.length === 0}
							onClick={() => void start()}
						>
							{busy ? t('Parsing…') : t('Parse documents')}
						</Button>
					</div>
				</section>

				<section className="flex min-h-[420px] min-w-0 flex-col rounded-lg border border-zinc-200 dark:border-zinc-700">
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
						{tab === 'original' && previewUrl != null && (
							<a
								href={previewUrl}
								target="_blank"
								rel="noreferrer"
								className="mr-2 text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
							>
								{t('Open in a new tab')}
							</a>
						)}
						{instanceId != null && (
							<Link
								href={instanceHref(instanceId)}
								className="mr-2 text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
							>
								{t('Open the instance')}
							</Link>
						)}
						{selected?.phase === 'success' && (
							<>
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									disabled={markdown === ''}
									onClick={() =>
										downloadText(
											`${(selected.job?.file_name ?? 'document').replace(/\.[^.]+$/, '')}.md`,
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
											`${(selected.job?.file_name ?? 'document').replace(/\.[^.]+$/, '')}.json`,
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
						{selected == null && (
							<p className="text-secondary dark:text-zinc-500">
								{t('Add documents and press Parse. The result appears here.')}
							</p>
						)}
						{selected != null &&
							(selected.phase === 'running' || selected.phase === 'submitting') && (
								<div className="flex items-center gap-2 text-secondary dark:text-zinc-400">
									<Spinner />
									<span>
										{selected.job?.status === 'queuing'
											? t('Queued…')
											: t('Recognising pages…')}
									</span>
								</div>
							)}
						{selected?.phase === 'failed' && (
							<div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
								{selected.error ?? t('This document could not be parsed.')}
								<span className="mt-1 block">
									<Link className="underline" href="/settings/model-settings">
										{t('Check Model Settings')}
									</Link>
								</span>
							</div>
						)}
						{selected?.phase === 'success' && tab === 'markdown' && (
							<MarkdownContent markdown={markdown} />
						)}
						{selected?.phase === 'success' && tab === 'json' && (
							<pre className="overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black">
								{JSON.stringify(json ?? {}, null, 2)}
							</pre>
						)}
						{selected?.phase === 'success' && tab === 'metadata' && (
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
						{tab === 'original' &&
							(selected == null || previewUrl == null ? (
								<p className="text-secondary dark:text-zinc-500">
									{t('Choose a document first.')}
								</p>
							) : selectedIsPdf ? (
								// Chrome and Edge render PDFs natively; the browser's own
								// viewer is what "what does the file look like" means.
								<iframe
									src={previewUrl}
									title={selected.file.name}
									className="h-[70vh] w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							) : (
								// eslint-disable-next-line @next/next/no-img-element -- a local blob URL, not a remote asset
								<img
									src={previewUrl}
									alt={selected.file.name}
									className="max-w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							))}
					</div>
				</section>
			</div>
		</div>
	);
};
