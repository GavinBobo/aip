// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';

import {
	parsingApi,
	type ParsingCapabilities,
	type ParsingProfile,
	type ParsingSourceListing,
	type ParsingSourceScan,
	type ParsingTask,
} from '@/api/parsing';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Modal } from '@/common/modal';
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

const textField =
	'h-8 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

type Props = {
	open: boolean;
	onClose: () => void;
	onCreated: (task: ParsingTask) => void;
};

export const ParsingFolderTaskModal = ({ open, onClose, onCreated }: Props) => {
	const [capabilities, setCapabilities] = useState<ParsingCapabilities | null>(null);
	const [profiles, setProfiles] = useState<ParsingProfile[]>([]);
	const [listing, setListing] = useState<ParsingSourceListing | null>(null);
	const [pathDraft, setPathDraft] = useState('');
	const [browsing, setBrowsing] = useState(false);
	const [browseError, setBrowseError] = useState<string | null>(null);
	const [selectedPath, setSelectedPath] = useState<string | null>(null);
	const [scan, setScan] = useState<ParsingSourceScan | null>(null);
	const [scanning, setScanning] = useState(false);
	const [name, setName] = useState('');
	const [profile, setProfile] = useState('standard');
	const [outputFormats, setOutputFormats] = useState<string[]>(['markdown', 'json']);
	const [keepHeaderFooter, setKeepHeaderFooter] = useState(false);
	const [elementFormats, setElementFormats] = useState<Record<string, string>>({});
	const [pageStart, setPageStart] = useState('');
	const [pageEnd, setPageEnd] = useState('');
	const [submitting, setSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [healthOk, setHealthOk] = useState<boolean | null>(null);

	useEffect(() => {
		if (!open) return;
		let cancelled = false;
		Promise.all([
			parsingApi.capabilities(),
			parsingApi.profiles(),
			parsingApi.browseSources(null),
			parsingApi.health(),
		]).then(([caps, presets, rootListing, health]) => {
			if (cancelled) return;
			setHealthOk(health.error || !health.data ? false : health.data.ok);
			if (!caps.error && caps.data) {
				setCapabilities(caps.data);
				setElementFormats(caps.data.element_format_defaults ?? {});
			}
			if (!presets.error && presets.data) setProfiles(presets.data);
			if (!rootListing.error && rootListing.data) {
				setListing(rootListing.data);
				setPathDraft(rootListing.data.path ?? '');
				setSelectedPath(rootListing.data.path);
			} else if (rootListing.error) {
				setBrowseError(rootListing.message ?? t('Could not list the shared folders.'));
			}
		});
		return () => {
			cancelled = true;
		};
	}, [open]);

	const browse = async (path: string | null) => {
		setBrowsing(true);
		setBrowseError(null);
		const response = await parsingApi.browseSources(path);
		setBrowsing(false);
		if (response.error || !response.data) {
			setBrowseError(response.message ?? t('Could not list the shared folders.'));
			return;
		}
		setListing(response.data);
		setPathDraft(response.data.path ?? path ?? '');
		setSelectedPath(response.data.path);
		setScan(null);
	};

	const chooseFolder = async () => {
		if (selectedPath == null) return;
		setScanning(true);
		setError(null);
		const response = await parsingApi.scanSources(selectedPath);
		setScanning(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Could not scan this folder.'));
			setScan(null);
			return;
		}
		setScan(response.data);
		if (name.trim() === '') {
			const folder = selectedPath
				.replace(/[\\/]+$/, '')
				.split(/[\\/]/)
				.pop();
			setName(folder ? `${folder} · ${response.data.count} 个 PDF` : '');
		}
	};

	const start = async () => {
		if (selectedPath == null || scan == null || scan.count === 0 || submitting) return;
		setSubmitting(true);
		setError(null);
		const response = await parsingApi.createTaskFromFolder({
			path: selectedPath,
			name: name.trim() || undefined,
			profile,
			options: {
				output_formats: outputFormats,
				keep_header_footer: keepHeaderFooter,
				element_formats: elementFormats,
			},
			page_start: pageStart.trim() === '' ? undefined : Number(pageStart),
			page_end: pageEnd.trim() === '' ? undefined : Number(pageEnd),
		});
		setSubmitting(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to create the folder parsing task.'));
			return;
		}
		onCreated(response.data);
		onClose();
	};

	const totalBytes = (scan?.files ?? []).reduce((sum, item) => sum + item.size, 0);
	const directories = (listing?.entries ?? []).filter((entry) => entry.kind === 'directory');

	return (
		<Modal
			open={open}
			onClose={onClose}
			align="top"
			ariaLabel={t('Create a parsing task from a shared folder')}
			className="flex max-h-[90vh] w-[min(940px,calc(100vw-2rem))] flex-col overflow-hidden"
		>
			<header className="flex items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<div>
					<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
						{t('Create a parsing task from a shared folder')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{t(
							'Choose a Windows/server shared folder. Every PDF in it and its subfolders becomes one parsing document in the task.',
						)}
					</p>
				</div>
				<button
					type="button"
					aria-label={t('Close')}
					onClick={onClose}
					className="text-secondary hover:text-heading dark:text-zinc-400"
				>
					<Icon name={IconName.Close} className="h-4 w-4" />
				</button>
			</header>

			<div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto md:grid-cols-[minmax(0,1fr)_360px]">
				<section className="min-h-[360px] border-b border-zinc-200 p-5 md:border-b-0 md:border-r dark:border-zinc-700">
					<div className="mb-2 flex items-center justify-between gap-2">
						<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
							{t('Shared folder')}
						</h3>
						<div className="flex gap-2">
							<button
								type="button"
								disabled={browsing || listing?.parent == null}
								onClick={() => void browse(listing?.parent ?? null)}
								className="text-[11px] text-secondary underline disabled:opacity-40 dark:text-zinc-400"
							>
								{t('Up')}
							</button>
							<button
								type="button"
								disabled={browsing}
								onClick={() => void browse(null)}
								className="text-[11px] text-secondary underline disabled:opacity-40 dark:text-zinc-400"
							>
								{t('Shared roots')}
							</button>
						</div>
					</div>
					<div className="mb-2 flex gap-1">
						<input
							value={pathDraft}
							onChange={(event) => setPathDraft(event.target.value)}
							onKeyDown={(event) => {
								if (event.key === 'Enter') void browse(pathDraft);
							}}
							placeholder={t('Shared folder path')}
							className={`${textField} font-mono`}
						/>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.SMALL}
							disabled={browsing || pathDraft.trim() === ''}
							onClick={() => void browse(pathDraft)}
						>
							{t('Open')}
						</Button>
					</div>

					{browsing ? (
						<div className="flex items-center gap-2 py-8 text-xs text-secondary">
							<Spinner />
							{t('Listing shared folders…')}
						</div>
					) : browseError != null ? (
						<p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
							{browseError}
						</p>
					) : listing != null && listing.roots.length === 0 ? (
						<p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
							{t(
								'No shared folders are configured. Set FILE_SOURCE_ROOTS on the backend.',
							)}
						</p>
					) : (
						<>
							<ul className="max-h-56 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
								{directories.length === 0 ? (
									<li className="px-3 py-6 text-center text-xs text-secondary">
										{t('No subfolders here. You can use this folder directly.')}
									</li>
								) : (
									directories.map((entry) => (
										<li key={entry.path}>
											<button
												type="button"
												onClick={() => void browse(entry.path)}
												className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-heading hover:bg-[#76b900]/10 dark:text-zinc-200"
											>
												<Icon
													name={IconName.ChevronRight}
													className="h-3.5 w-3.5 shrink-0 text-secondary"
												/>
												<span className="min-w-0 flex-1 truncate">
													{entry.name}
												</span>
												{entry.is_root && (
													<span className="rounded-full border border-zinc-300 px-1.5 text-[10px] uppercase text-secondary">
														{t('Shared')}
													</span>
												)}
											</button>
										</li>
									))
								)}
							</ul>
							<div className="mt-3 flex items-center justify-between gap-3">
								<span className="text-[11px] text-secondary dark:text-zinc-400">
									{t('Current folder is selected.')}
								</span>
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									loading={scanning}
									disabled={selectedPath == null || scanning}
									onClick={() => void chooseFolder()}
								>
									{t('Scan this folder')}
								</Button>
							</div>
						</>
					)}

					{scan != null && (
						<div className="mt-4 rounded-lg border border-zinc-200 dark:border-zinc-700">
							<div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
								<span className="text-xs font-medium text-heading dark:text-zinc-100">
									{t('{count} PDFs found', { count: scan.count })}
								</span>
								<span className="text-[10px] text-secondary">
									{formatBytes(totalBytes)} · {t('limit')}: {scan.limit}
								</span>
							</div>
							<ul className="max-h-40 overflow-y-auto px-3 py-2 text-[11px]">
								{scan.files.slice(0, 20).map((file) => (
									<li key={file.path} className="flex items-center gap-2 py-0.5">
										<span className="min-w-0 flex-1 truncate">
											{file.relative}
										</span>
										<span className="shrink-0 text-secondary">
											{formatBytes(file.size)}
										</span>
									</li>
								))}
								{scan.files.length > 20 && (
									<li className="pt-1 text-secondary">
										{t('…and {count} more', {
											count: scan.files.length - 20,
										})}
									</li>
								)}
							</ul>
						</div>
					)}
				</section>

				<section className="space-y-3 p-5">
					<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
						{t('Parsing options')}
					</h3>
					<label className="flex flex-col gap-1 text-[11px] text-secondary">
						{t('Task name')}
						<input
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder={t('optional')}
							className={textField}
						/>
					</label>
					<label className="flex flex-col gap-1 text-[11px] text-secondary">
						{t('Parsing profile')}
						<select
							value={profile}
							onChange={(event) => setProfile(event.target.value)}
							className={textField}
						>
							{profiles.map((item) => (
								<option key={item.name} value={item.name}>
									{item.name} · {item.description}
								</option>
							))}
						</select>
					</label>
					<div>
						<p className="mb-1 text-[11px] text-secondary">{t('Output')}</p>
						<div className="flex flex-wrap gap-3 text-xs">
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
					</div>
					<div>
						<p className="mb-1 text-[11px] text-secondary">{t('Element formats')}</p>
						<div className="grid grid-cols-2 gap-2">
							{Object.entries(capabilities?.element_formats ?? {}).map(
								([element, values]) => (
									<label key={element} className="flex flex-col gap-1">
										<span className="text-[10px] text-secondary">
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
											className={textField}
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
					<div className="grid grid-cols-2 gap-2">
						<label className="flex flex-col gap-1 text-[11px] text-secondary">
							{t('Start page')}
							<input
								type="number"
								min={1}
								value={pageStart}
								onChange={(event) => setPageStart(event.target.value)}
								placeholder={t('optional')}
								className={textField}
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
								className={textField}
							/>
						</label>
					</div>
					{error != null && (
						<p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700">
							{error}
						</p>
					)}
				</section>
			</div>

			<footer className="flex items-center justify-between gap-3 border-t border-zinc-200 px-5 py-3 dark:border-zinc-700">
				<span className="text-[11px] text-secondary dark:text-zinc-400">
					{scan == null
						? t('Select a folder and scan it first.')
						: healthOk === false
							? t('Parsing services need attention.')
							: t('{count} PDFs will be parsed into the result library.', {
									count: scan.count,
								})}
				</span>
				<div className="flex gap-2">
					<Button theme={ButtonTheme.Secondary} size={Size.SMALL} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.SMALL}
						loading={submitting}
						disabled={
							scan == null ||
							scan.count === 0 ||
							selectedPath == null ||
							outputFormats.length === 0 ||
							healthOk === false
						}
						onClick={() => void start()}
					>
						{t('Start parsing this folder')}
					</Button>
				</div>
			</footer>
		</Modal>
	);
};
