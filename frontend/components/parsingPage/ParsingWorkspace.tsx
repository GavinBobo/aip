// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';

import {
	parsingApi,
	type ParsingCapabilities,
	type ParsingHealth,
	type ParsingProfile,
	type ParsingTask,
} from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

const ELEMENT_LABELS: Record<string, Record<string, string>> = {
	image: { url: 'URL', base64: 'Base64', none: '不输出' },
	formula: { latex: 'LaTeX' },
	table: { html: 'HTML', markdown: 'Markdown' },
	cs: { smiles: 'SMILES', image: '图片' },
};

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const fileKey = (file: File): string => `${file.name}:${file.size}:${file.lastModified}`;

const statusClass = (status: string): string => {
	if (status === 'succeeded') return 'bg-emerald-100 text-emerald-700';
	if (status === 'failed') return 'bg-red-100 text-red-700';
	if (status === 'cancelled') return 'bg-zinc-200 text-zinc-600';
	if (status === 'running') return 'bg-[#76b900]/15 text-[#4b7a00]';
	return 'bg-zinc-100 text-secondary';
};

const progressText = (done: number, total: number): string =>
	total > 0 ? `${done}/${total}` : '—';

export const ParsingWorkspace = () => {
	const [capabilities, setCapabilities] = useState<ParsingCapabilities | null>(null);
	const [profiles, setProfiles] = useState<ParsingProfile[]>([]);
	const [health, setHealth] = useState<ParsingHealth | null>(null);
	const [checking, setChecking] = useState(false);
	const [files, setFiles] = useState<File[]>([]);
	const [profile, setProfile] = useState('standard');
	const [outputFormats, setOutputFormats] = useState<string[]>(['markdown', 'json']);
	const [keepHeaderFooter, setKeepHeaderFooter] = useState(false);
	const [elementFormats, setElementFormats] = useState<Record<string, string>>({});
	const [pageStart, setPageStart] = useState('');
	const [pageEnd, setPageEnd] = useState('');
	const [submitting, setSubmitting] = useState(false);
	const [task, setTask] = useState<ParsingTask | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [dragging, setDragging] = useState(false);
	const inputRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		let cancelled = false;
		Promise.all([parsingApi.capabilities(), parsingApi.profiles()]).then(
			([capsResponse, profilesResponse]) => {
				if (cancelled) return;
				if (!capsResponse.error && capsResponse.data) {
					setCapabilities(capsResponse.data);
					setElementFormats(capsResponse.data.element_format_defaults ?? {});
				}
				if (!profilesResponse.error && profilesResponse.data) {
					setProfiles(profilesResponse.data);
				}
			},
		);
		return () => {
			cancelled = true;
		};
	}, []);

	const checkHealth = useCallback(async () => {
		setChecking(true);
		const response = await parsingApi.health();
		setChecking(false);
		if (response.error || !response.data) {
			setHealth(null);
			setError(response.message ?? t('Connection failed.'));
			return;
		}
		setHealth(response.data);
	}, []);

	useEffect(() => {
		let cancelled = false;
		parsingApi.health().then((response) => {
			if (cancelled) return;
			if (response.error || !response.data) {
				setHealth(null);
				return;
			}
			setHealth(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		const taskId = task?.id;
		const taskStatus = task?.status;
		if (taskId == null || taskStatus == null) return;
		if (!['queued', 'running'].includes(taskStatus)) return;
		const timer = window.setInterval(() => {
			parsingApi.task(taskId).then((response) => {
				if (response.error || !response.data) return;
				setTask(response.data);
			});
		}, 1500);
		return () => window.clearInterval(timer);
	}, [task?.id, task?.status]);

	const addFiles = useCallback((picked: FileList | null) => {
		if (picked == null) return;
		const incoming = Array.from(picked);
		if (incoming.length === 0) return;
		setFiles((current) => {
			const known = new Set(current.map(fileKey));
			return [...current, ...incoming.filter((file) => !known.has(fileKey(file)))];
		});
	}, []);

	const start = async () => {
		if (files.length === 0 || submitting) return;
		setSubmitting(true);
		setError(null);
		setTask(null);
		const form = new FormData();
		for (const file of files) form.append('files', file);
		form.append('profile', profile);
		form.append(
			'options',
			JSON.stringify({
				output_formats: outputFormats,
				keep_header_footer: keepHeaderFooter,
				element_formats: elementFormats,
			}),
		);
		if (pageStart.trim() !== '') form.append('page_start', pageStart.trim());
		if (pageEnd.trim() !== '') form.append('page_end', pageEnd.trim());
		const response = await parsingApi.createTask(form);
		setSubmitting(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to submit the document.'));
			return;
		}
		setTask(response.data);
		setFiles([]);
	};

	const busy = submitting || (task != null && ['queued', 'running'].includes(task.status));
	const serviceOk = health?.ok === true;
	const latestRuns = task?.runs ?? [];

	return (
		<div className="flex h-full min-h-0 flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
				<div>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Parsing Workspace')}
					</h1>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'Upload one or more PDFs or images. Each file becomes a durable task with page-level progress, cancel, retry, and a reviewable result.',
						)}
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Link
						href="/parsing/tasks"
						className="text-xs text-[#5c9200] underline dark:text-[#a3e635]"
					>
						{t('Task centre')}
					</Link>
					<Link
						href="/parsing/library"
						className="text-xs text-[#5c9200] underline dark:text-[#a3e635]"
					>
						{t('Result library')}
					</Link>
				</div>
			</header>

			<div className="mx-6 mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-200 px-4 py-3 text-xs dark:border-zinc-700">
				<div className="flex items-center gap-2">
					<span
						className={`h-2 w-2 rounded-full ${
							serviceOk ? 'bg-emerald-500' : 'bg-amber-500'
						}`}
					/>
					<span className="text-body dark:text-zinc-300">
						{health == null
							? t('Checking services…')
							: serviceOk
								? t('Parsing services are healthy.')
								: t('Parsing services need attention.')}
					</span>
					{health != null && (
						<span className="text-secondary dark:text-zinc-500">
							{t('Backend')}: {health.backend.ok ? '✓' : '×'} · {t('Layout')}:{' '}
							{health.layout.ok ? '✓' : '×'}
						</span>
					)}
				</div>
				<div className="flex items-center gap-3">
					<button
						type="button"
						className="text-[#5c9200] underline disabled:opacity-50 dark:text-[#a3e635]"
						disabled={checking}
						onClick={() => void checkHealth()}
					>
						{checking ? t('Checking…') : t('Check services')}
					</button>
					{!serviceOk && (
						<Link className="underline" href="/settings/model-settings">
							{t('Open Model Settings')}
						</Link>
					)}
				</div>
			</div>

			<div className="grid flex-1 gap-5 p-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
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
								event.target.value = '';
							}}
						/>
					</div>

					{files.length > 0 && (
						<div className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
							<div className="flex items-center justify-between">
								<h2 className="text-xs font-semibold text-heading dark:text-zinc-100">
									{t('Queue')} · {files.length}
								</h2>
								<button
									type="button"
									className="text-[11px] text-secondary underline disabled:opacity-50 dark:text-zinc-400"
									disabled={busy}
									onClick={() => setFiles([])}
								>
									{t('Clear the queue')}
								</button>
							</div>
							<ul className="max-h-52 space-y-1 overflow-y-auto">
								{files.map((file) => (
									<li
										key={fileKey(file)}
										className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs"
									>
										<span className="min-w-0 flex-1 truncate">{file.name}</span>
										<span className="shrink-0 text-[10px] text-secondary dark:text-zinc-500">
											{formatBytes(file.size)}
										</span>
										<button
											type="button"
											aria-label={t('Remove from the queue')}
											className="text-secondary hover:text-red-600 disabled:opacity-50 dark:text-zinc-500"
											disabled={busy}
											onClick={() =>
												setFiles((current) =>
													current.filter(
														(item) => fileKey(item) !== fileKey(file),
													),
												)
											}
										>
											<Icon name={IconName.Close} className="h-3 w-3" />
										</button>
									</li>
								))}
							</ul>
						</div>
					)}

					<div className="space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
						<h2 className="text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Parsing profile')}
						</h2>
						<select
							value={profile}
							disabled={busy}
							onChange={(event) => setProfile(event.target.value)}
							className="h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
						>
							{profiles.map((item) => (
								<option key={item.name} value={item.name}>
									{item.name} · {item.description}
								</option>
							))}
						</select>
						<div className="grid grid-cols-2 gap-2">
							<label className="flex flex-col gap-1 text-[11px] text-secondary">
								{t('Start page')}
								<input
									type="number"
									min={1}
									value={pageStart}
									onChange={(event) => setPageStart(event.target.value)}
									placeholder={t('optional')}
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900"
								/>
							</label>
							<label className="flex flex-col gap-1 text-[11px] text-secondary">
								{t('End page')}
								<input
									type="number"
									min={1}
									value={pageEnd}
									onChange={(event) => setPageEnd(event.target.value)}
									placeholder={t('optional')}
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900"
								/>
							</label>
						</div>

						<h2 className="pt-1 text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Output')}
						</h2>
						<div className="flex flex-wrap gap-4 text-xs">
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
										<span className="text-[11px] text-secondary">
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
											className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
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
					</div>

					<div className="flex items-center gap-3">
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							loading={submitting}
							disabled={
								files.length === 0 ||
								busy ||
								outputFormats.length === 0 ||
								(health != null && !health.ok)
							}
							onClick={() => void start()}
						>
							{submitting ? t('Submitting…') : t('Start parsing')}
						</Button>
						{task != null && (
							<span className="text-[11px] text-secondary">
								{t('Status')}: {t(task.status)}
							</span>
						)}
					</div>

					{error != null && (
						<div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
							{error}
						</div>
					)}
				</section>

				<section className="flex min-h-[420px] min-w-0 flex-col rounded-lg border border-zinc-200 dark:border-zinc-700">
					<div className="flex items-center justify-between gap-2 border-b border-zinc-200 px-4 py-2 dark:border-zinc-700">
						<h2 className="text-xs font-semibold text-heading dark:text-zinc-100">
							{task?.name ?? t('Current task')}
						</h2>
						{task != null && (
							<div className="flex items-center gap-2">
								<span
									className={`rounded px-2 py-0.5 text-[10px] ${statusClass(task.status)}`}
								>
									{t(task.status)}
								</span>
								{['queued', 'running'].includes(task.status) && (
									<Button
										theme={ButtonTheme.Secondary}
										size={Size.SMALL}
										onClick={() =>
											void parsingApi.cancelTask(task.id).then((response) => {
												if (!response.error && response.data)
													setTask(response.data);
											})
										}
									>
										{t('Cancel')}
									</Button>
								)}
								<Link
									href={`/parsing/tasks/${encodeURIComponent(task.id)}`}
									className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
								>
									{t('Open task')}
								</Link>
							</div>
						)}
					</div>
					<div className="min-h-0 flex-1 overflow-y-auto p-4 text-xs">
						{task == null ? (
							<div className="space-y-3 text-secondary dark:text-zinc-500">
								<p>
									{t(
										'Choose files and start parsing. Progress and results will appear here.',
									)}
								</p>
								{latestRuns.length === 0 && (
									<div className="rounded-lg border border-dashed border-zinc-300 p-6 text-center dark:border-zinc-700">
										<Icon
											name={IconName.Spreadsheet}
											className="mx-auto mb-2 h-5 w-5 opacity-50"
										/>
										<p>{t('No parsing task yet.')}</p>
									</div>
								)}
							</div>
						) : (
							<div className="space-y-3">
								<div className="flex flex-wrap items-center gap-3 text-[11px] text-secondary">
									<span>
										{t('Files')}:{' '}
										{task.completed_documents + task.failed_documents}/
										{task.total_documents}
									</span>
									<span>
										{t('Profile')}: {task.profile}
									</span>
									{busy && <Spinner />}
								</div>
								<div className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-700">
									{task.documents.map((document) => {
										const run = task.runs
											.filter((item) => item.document_id === document.id)
											.sort((a, b) =>
												(a.created ?? '').localeCompare(b.created ?? ''),
											)
											.at(-1);
										return (
											<div
												key={document.id}
												className="flex flex-wrap items-center gap-2 px-3 py-2.5"
											>
												<div className="min-w-0 flex-1">
													<p className="truncate text-xs font-medium text-heading dark:text-zinc-100">
														{document.file_name}
													</p>
													<p className="mt-0.5 truncate text-[10px] text-secondary dark:text-zinc-500">
														{document.error_message ??
															(document.progress_total > 0
																? `${document.stage ?? t('processing')} · ${progressText(
																		document.progress_done,
																		document.progress_total,
																	)}`
																: t('queuing'))}
													</p>
												</div>
												<span
													className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass(
														document.status,
													)}`}
												>
													{t(document.status)}
												</span>
												{document.status === 'failed' && (
													<button
														type="button"
														className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
														onClick={() =>
															void parsingApi
																.retryDocument(document.id)
																.then((response) => {
																	if (
																		!response.error &&
																		response.data
																	) {
																		setTask(response.data);
																	}
																})
														}
													>
														{t('Retry')}
													</button>
												)}
												{run?.status === 'succeeded' && (
													<Link
														href={`/parsing/library/${encodeURIComponent(run.id)}`}
														className="text-[11px] text-[#5c9200] underline dark:text-[#a3e635]"
													>
														{t('Open result')}
													</Link>
												)}
											</div>
										);
									})}
								</div>
								{task.failed_documents > 0 && (
									<p className="text-[11px] text-amber-700 dark:text-amber-300">
										{t(
											'Some files failed. Retry them individually from this list.',
										)}
									</p>
								)}
							</div>
						)}
					</div>
				</section>
			</div>
		</div>
	);
};
