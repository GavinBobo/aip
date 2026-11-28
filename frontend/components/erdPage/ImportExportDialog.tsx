// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRef, useState } from 'react';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { SQL_DIALECTS } from '@/lib/erd/dialects';
import type { ErdExportFormat, SqlDialect } from '@/types/erd';

type ImportExportDialogProps = {
	open: boolean;
	readOnly: boolean;
	busy: boolean;
	warnings: string[];
	onClose: () => void;
	onImport: (format: ErdExportFormat, content: string, replace: boolean) => void;
	onExport: (format: ErdExportFormat, dialect: SqlDialect) => void;
	onExportImage: (kind: 'svg' | 'png') => void;
};

export const ImportExportDialog = ({
	open,
	readOnly,
	busy,
	warnings,
	onClose,
	onImport,
	onExport,
	onExportImage,
}: ImportExportDialogProps) => {
	const [format, setFormat] = useState<ErdExportFormat>('dbml');
	const [dialect, setDialect] = useState<SqlDialect>('sqlserver');
	const [content, setContent] = useState('');
	// Merge into the current canvas unless the operator explicitly asks to
	// replace it; an import should not wipe the existing diagram by default.
	const [replace, setReplace] = useState(false);
	const [warningsHidden, setWarningsHidden] = useState(true);
	const fileRef = useRef<HTMLInputElement | null>(null);

	const pickFile = async (file: File | undefined) => {
		if (!file) return;
		const text = await file.text();
		setContent(text);
		const lower = file.name.toLowerCase();
		setFormat(lower.endsWith('.json') ? 'json' : lower.endsWith('.sql') ? 'sql' : 'dbml');
	};

	return (
		<Modal open={open} onClose={onClose} className="w-full max-w-3xl">
			<header className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
					{t('Import / Export')}
				</h2>
				<Button
					theme={ButtonTheme.IconNeutral}
					size={Size.SMALL}
					iconOnly
					type="button"
					onClick={onClose}
					aria-label={t('Close')}
				>
					✕
				</Button>
			</header>

			<div className="grid gap-6 p-5 md:grid-cols-2">
				<section className="flex min-w-0 flex-col gap-3">
					<h3 className="text-sm font-semibold text-heading dark:text-zinc-200">
						{t('Export')}
					</h3>
					<p className="text-xs text-secondary dark:text-zinc-400">
						{t(
							'JSON keeps positions and virtual tables. DBML is the format other modelling tools read.',
						)}
					</p>
					<div className="flex gap-2">
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => onExport('json', dialect)}
						>
							{t('Export JSON')}
						</Button>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => onExport('dbml', dialect)}
						>
							{t('Export DBML')}
						</Button>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => onExport('sql', dialect)}
						>
							{t('Export SQL')}
						</Button>
					</div>
					<label className="flex items-center gap-2 text-xs text-body dark:text-zinc-300">
						{t('SQL dialect')}
						<select
							value={dialect}
							onChange={(event) => setDialect(event.target.value as SqlDialect)}
							className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						>
							{SQL_DIALECTS.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
					</label>
					<div className="flex gap-2">
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => onExportImage('png')}
						>
							{t('Export PNG')}
						</Button>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => onExportImage('svg')}
						>
							{t('Export SVG')}
						</Button>
					</div>
					{warnings.length > 0 && (
						<div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
							<div className="mb-1 flex items-center justify-between">
								<span className="font-medium">
									{t('{0} item(s) were skipped', { 0: warnings.length })}
								</span>
								<button
									type="button"
									className="text-amber-700 underline dark:text-amber-300"
									onClick={() => setWarningsHidden(!warningsHidden)}
								>
									{warningsHidden ? t('Show') : t('Hide')}
								</button>
							</div>
							{!warningsHidden && (
								<ul className="list-disc space-y-0.5 pl-4">
									{warnings.map((warning) => (
										<li key={warning}>{warning}</li>
									))}
								</ul>
							)}
						</div>
					)}
				</section>

				<section className="flex min-w-0 flex-col gap-3 border-zinc-200 md:border-l md:pl-6 dark:border-zinc-700">
					<h3 className="text-sm font-semibold text-heading dark:text-zinc-200">
						{t('Import')}
					</h3>
					<div className="flex items-center gap-3 text-xs text-body dark:text-zinc-300">
						<label className="flex items-center gap-1.5">
							<input
								type="radio"
								checked={format === 'dbml'}
								onChange={() => setFormat('dbml')}
							/>
							DBML
						</label>
						<label className="flex items-center gap-1.5">
							<input
								type="radio"
								checked={format === 'sql'}
								onChange={() => setFormat('sql')}
							/>
							SQL
						</label>
						<label className="flex items-center gap-1.5">
							<input
								type="radio"
								checked={format === 'json'}
								onChange={() => setFormat('json')}
							/>
							JSON
						</label>
						<button
							type="button"
							className="ml-auto text-[#5e9400] underline dark:text-[#a3d63a]"
							onClick={() => fileRef.current?.click()}
						>
							{t('Choose file')}
						</button>
						<input
							ref={fileRef}
							type="file"
							accept=".dbml,.json,.sql,text/plain,application/json,application/sql"
							className="hidden"
							onChange={(event) => void pickFile(event.target.files?.[0])}
						/>
					</div>
					<textarea
						value={content}
						onChange={(event) => setContent(event.target.value)}
						placeholder={
							format === 'dbml'
								? 'Table public.orders { id bigint [pk] }'
								: format === 'sql'
									? 'CREATE TABLE orders (id bigint PRIMARY KEY);'
									: '{"nodes": [], "relationships": []}'
						}
						spellCheck={false}
						className="h-48 w-full resize-none rounded-lg border border-zinc-300 bg-white p-2 font-mono text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
					/>
					<label className="flex items-center gap-2 text-xs text-body dark:text-zinc-300">
						<input
							type="checkbox"
							checked={replace}
							onChange={(event) => setReplace(event.target.checked)}
						/>
						{t('Replace the current canvas')}
					</label>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.REGULAR}
						type="button"
						disabled={busy || readOnly || content.trim() === ''}
						onClick={() => onImport(format, content, replace)}
					>
						{t('Import')}
					</Button>
				</section>
			</div>
		</Modal>
	);
};
