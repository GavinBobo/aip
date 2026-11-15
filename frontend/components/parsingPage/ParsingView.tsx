// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';

import { parsingApi, type ParsingCapabilities, type ParsingJob } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { downloadText } from '@/lib/erd/download';

type Phase = 'idle' | 'submitting' | 'running' | 'success' | 'failed';

/** Poll interval for a running job. The pipeline is seconds-to-minutes. */
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

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/** Tailwind overrides so the preview reads like a document, not like source. */
const MARKDOWN_COMPONENTS = {
	h1: (props: object) => <h1 className="mt-4 mb-2 text-lg font-semibold" {...props} />,
	h2: (props: object) => <h2 className="mt-4 mb-2 text-base font-semibold" {...props} />,
	h3: (props: object) => <h3 className="mt-3 mb-1.5 text-sm font-semibold" {...props} />,
	p: (props: object) => <p className="my-2 leading-relaxed" {...props} />,
	ul: (props: object) => <ul className="my-2 list-disc pl-5" {...props} />,
	ol: (props: object) => <ol className="my-2 list-decimal pl-5" {...props} />,
	li: (props: object) => <li className="my-0.5" {...props} />,
	table: (props: object) => (
		<div className="my-3 overflow-x-auto">
			<table className="min-w-full border-collapse text-xs" {...props} />
		</div>
	),
	th: (props: object) => (
		<th
			className="border border-zinc-300 bg-zinc-50 px-2 py-1 text-left font-medium dark:border-zinc-600 dark:bg-zinc-800"
			{...props}
		/>
	),
	td: (props: object) => (
		<td
			className="border border-zinc-200 px-2 py-1 align-top dark:border-zinc-700"
			{...props}
		/>
	),
	pre: (props: object) => (
		<pre
			className="my-3 overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black"
			{...props}
		/>
	),
	code: (props: object) => (
		<code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px] dark:bg-zinc-800" {...props} />
	),
	a: (props: object) => (
		<a
			className="text-[#5c9200] underline dark:text-[#a3e635]"
			target="_blank"
			rel="noreferrer"
			{...props}
		/>
	),
	img: (props: object) => (
		// eslint-disable-next-line @next/next/no-img-element -- parsed documents carry data: and remote images
		<img className="my-2 max-w-full" alt="" {...props} />
	),
	blockquote: (props: object) => (
		<blockquote
			className="my-2 border-l-2 border-zinc-300 pl-3 text-secondary dark:border-zinc-600 dark:text-zinc-400"
			{...props}
		/>
	),
	hr: (props: object) => <hr className="my-4 border-zinc-200 dark:border-zinc-700" {...props} />,
};

export const ParsingView = () => {
	const [capabilities, setCapabilities] = useState<ParsingCapabilities | null>(null);
	const [file, setFile] = useState<File | null>(null);
	const [phase, setPhase] = useState<Phase>('idle');
	const [job, setJob] = useState<ParsingJob | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<'markdown' | 'json' | 'metadata' | 'original'>('markdown');
	// Object URL of the chosen file, for the source-preview tab. Revoked when the
	// file changes and on unmount; a leaked blob URL keeps the whole document in
	// memory for the life of the tab.
	const [previewUrl, setPreviewUrl] = useState<string | null>(null);
	const previewUrlRef = useRef<string | null>(null);
	const [dragging, setDragging] = useState(false);
	const inputRef = useRef<HTMLInputElement>(null);

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

	// Poll only while the job is alive. The interval is cleared on unmount and as
	// soon as the job reaches a terminal state, so a finished parse stops asking.
	useEffect(() => {
		const taskId = job?.task_id;
		if (taskId == null) return;
		if (job?.status !== 'queuing' && job?.status !== 'processing') return;

		const timer = window.setInterval(() => {
			parsingApi.job(taskId).then((response) => {
				if (response.error || !response.data) {
					setPhase('failed');
					setError(response.message ?? t('Failed to read the job status.'));
					return;
				}
				setJob(response.data);
				setPhase(
					response.data.status === 'success'
						? 'success'
						: response.data.status === 'failed'
							? 'failed'
							: 'running',
				);
				if (response.data.status === 'failed') setError(response.data.error);
			});
		}, POLL_MS);
		return () => window.clearInterval(timer);
	}, [job?.task_id, job?.status]);

	const pickFile = useCallback((next: File | null) => {
		setFile(next);
		if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
		const url = next == null ? null : URL.createObjectURL(next);
		previewUrlRef.current = url;
		setPreviewUrl(url);
		setJob(null);
		setError(null);
		setPhase('idle');
	}, []);

	useEffect(
		() => () => {
			if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
		},
		[],
	);

	const start = async () => {
		if (file == null || phase === 'submitting' || phase === 'running') return;
		setPhase('submitting');
		setError(null);
		setJob(null);

		const form = new FormData();
		form.append('file', file);
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
		if (response.error || !response.data) {
			setPhase('failed');
			setError(response.message ?? t('Failed to submit the document.'));
			return;
		}
		setJob(response.data);
		setPhase('running');
	};

	const outputs = job?.result?.outputs ?? {};
	const markdown = typeof outputs.markdown === 'string' ? outputs.markdown : '';
	const json = outputs.json;
	const metadata = job?.metadata ?? {};
	const busy = phase === 'submitting' || phase === 'running';
	const fileIsPdf =
		file != null && (/\.pdf$/i.test(file.name) || file.type === 'application/pdf');

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
					{t('Document Parsing')}
				</h1>
				<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
					{t(
						'Turn a PDF or a document image into Markdown and JSON, with layout coordinates. The recognition and layout endpoints are configured in Model Settings.',
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
							const dropped = event.dataTransfer.files?.[0];
							if (dropped) pickFile(dropped);
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
							{t('Drop a PDF or image here, or')}{' '}
							<button
								type="button"
								className="text-[#5c9200] underline dark:text-[#a3e635]"
								onClick={() => inputRef.current?.click()}
							>
								{t('choose a file')}
							</button>
						</p>
						<input
							ref={inputRef}
							type="file"
							accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
							className="hidden"
							onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
						/>
						{file != null && (
							<p className="text-[11px] text-secondary dark:text-zinc-400">
								{file.name} · {formatBytes(file.size)}
							</p>
						)}
					</div>

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
							disabled={file == null || busy || outputFormats.length === 0}
							onClick={() => void start()}
						>
							{busy ? t('Parsing…') : t('Parse document')}
						</Button>
						{job != null && (
							<span className="text-[11px] text-secondary dark:text-zinc-400">
								{t('Status')}: {t(job.status)}
							</span>
						)}
					</div>

					{error != null && (
						<div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
							{error}
							{/* OXR deliberately keeps decoder and transport details out of
							    public messages, so point at the page that can fix it. */}
							<span className="mt-1 block">
								<Link className="underline" href="/settings/model-settings">
									{t('Check Model Settings')}
								</Link>
							</span>
						</div>
					)}
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
						{phase === 'success' && (
							<>
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									disabled={markdown === ''}
									onClick={() =>
										downloadText(
											`${(job?.file_name ?? 'document').replace(/\.[^.]+$/, '')}.md`,
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
											`${(job?.file_name ?? 'document').replace(/\.[^.]+$/, '')}.json`,
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
						{phase === 'idle' && tab !== 'original' && (
							<p className="text-secondary dark:text-zinc-500">
								{t('Choose a document and press Parse. The result appears here.')}
							</p>
						)}
						{busy && (
							<div className="flex items-center gap-2 text-secondary dark:text-zinc-400">
								<Spinner />
								<span>
									{job?.status === 'queuing'
										? t('Queued…')
										: t('Recognising pages…')}
								</span>
							</div>
						)}
						{phase === 'success' && tab === 'markdown' && (
							<ReactMarkdown
								remarkPlugins={[remarkGfm]}
								rehypePlugins={[rehypeRaw, rehypeSanitize]}
								components={MARKDOWN_COMPONENTS}
							>
								{markdown}
							</ReactMarkdown>
						)}
						{phase === 'success' && tab === 'json' && (
							<pre className="overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black">
								{JSON.stringify(json ?? {}, null, 2)}
							</pre>
						)}
						{phase === 'success' && tab === 'metadata' && (
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
							(previewUrl == null ? (
								<p className="text-secondary dark:text-zinc-500">
									{t('Choose a document first.')}
								</p>
							) : fileIsPdf ? (
								// Chrome and Edge render PDFs natively; the browser's own
								// viewer is what "what does the file look like" means.
								<iframe
									src={previewUrl}
									title={file?.name ?? t('Original file')}
									className="h-[70vh] w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							) : (
								// eslint-disable-next-line @next/next/no-img-element -- a local blob URL, not a remote asset
								<img
									src={previewUrl}
									alt={file?.name ?? ''}
									className="max-w-full rounded-lg border border-zinc-200 dark:border-zinc-700"
								/>
							))}
					</div>
				</section>
			</div>
		</div>
	);
};
