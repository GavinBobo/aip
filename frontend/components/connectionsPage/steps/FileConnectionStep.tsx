// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { t } from '@/i18n';
import { useState, type ChangeEvent } from 'react';
import { Spinner } from '@nvidia/foundations-react-core';
import { Icon, IconName } from '@/common/icons';
import type { FilePreview, ServerPathListing } from '@/types/connection';
import { connectionNameErrorMessage } from '@/components/connectionsPage/connection-name';

/** Extensions the backend accepts; `.pq` is parquet's short form. */
const ACCEPT = '.csv,.tsv,.txt,.xlsx,.xls,.xlsm,.parquet,.pq';

export type FileSourceMode = 'upload' | 'server';

export type FileConnectionStepProps = {
	/** Connection name, also the catalog key. */
	databaseName: string;
	onDatabaseNameChange: (name: string) => void;
	/** Editing an existing connection: its name is the catalog key and is fixed. */
	nameReadOnly?: boolean;
	/** Name of the file already attached to an existing connection. */
	existingFileName?: string | null;
	/** Upload from this browser, or read a file from the server's shared folders. */
	sourceMode: FileSourceMode;
	onSourceModeChange: (mode: FileSourceMode) => void;
	serverPath: string;
	onServerPathChange: (path: string) => void;
	/** Read the path into the preview below. */
	onLoadServerPath: (path?: string) => void;
	/** List shared folders and supported files below a directory. */
	onBrowseServerPaths: (path: string | null) => Promise<ServerPathListing | { error: string }>;
	selectedFileName: string | null;
	preview: FilePreview | null;
	busy: boolean;
	error: string | null;
	sheet: string | null;
	/** ``''`` = auto-detect, a preset character, or ``'custom'``. */
	delimiter: string;
	/** The character behind ``'custom'``. */
	customDelimiter: string;
	headerRow: number;
	columnNames: string[];
	/** One flag per preview column; unchecked columns are dropped on create. */
	selectedColumns: boolean[];
	onSelectFile: (file: File) => void;
	onSheetChange: (sheet: string) => void;
	onDelimiterChange: (value: string) => void;
	onCustomDelimiterChange: (value: string) => void;
	onHeaderRowChange: (row: number) => void;
	onColumnNameChange: (index: number, name: string) => void;
	onColumnToggle: (index: number) => void;
	onSelectAllColumns: (select: boolean) => void;
};

const inputClassName =
	'rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-heading outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100';

const DELIMITER_LABELS: Record<string, string> = {
	',': 'comma',
	'\t': 'tab',
	';': 'semicolon',
	'|': 'pipe',
	' ': 'space',
};

const describeDelimiter = (value: string | null): string =>
	value == null ? 'none' : (DELIMITER_LABELS[value] ?? JSON.stringify(value));

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return t('{0} KB', { 0: (bytes / 1024).toFixed(1) });
	return t('{0} MB', { 0: (bytes / (1024 * 1024)).toFixed(1) });
};

export const FileConnectionStep = ({
	databaseName,
	onDatabaseNameChange,
	nameReadOnly = false,
	existingFileName = null,
	sourceMode,
	onSourceModeChange,
	serverPath,
	onServerPathChange,
	onLoadServerPath,
	onBrowseServerPaths,
	selectedFileName,
	preview,
	busy,
	error,
	sheet,
	delimiter,
	customDelimiter,
	headerRow,
	columnNames,
	selectedColumns,
	onSelectFile,
	onSheetChange,
	onDelimiterChange,
	onCustomDelimiterChange,
	onHeaderRowChange,
	onColumnNameChange,
	onColumnToggle,
	onSelectAllColumns,
}: FileConnectionStepProps) => {
	const [browserOpen, setBrowserOpen] = useState(false);
	const [browseBusy, setBrowseBusy] = useState(false);
	const [browseError, setBrowseError] = useState<string | null>(null);
	const [listing, setListing] = useState<ServerPathListing | null>(null);

	const pickFile = ({ target }: ChangeEvent<HTMLInputElement>) => {
		const picked = target.files?.[0];
		if (picked) onSelectFile(picked);
	};

	const openBrowser = async (path: string | null): Promise<void> => {
		setBrowserOpen(true);
		setBrowseBusy(true);
		setBrowseError(null);
		const res = await onBrowseServerPaths(path);
		setBrowseBusy(false);
		if ('error' in res) {
			setBrowseError(res.error);
			return;
		}
		setListing(res);
	};

	const chooseServerFile = (path: string): void => {
		onServerPathChange(path);
		setBrowserOpen(false);
		onLoadServerPath(path);
	};

	return (
		<div className="flex flex-1 flex-col gap-4 p-2">
			<p className="text-sm text-body dark:text-zinc-400">
				{t(
					'Upload a spreadsheet, delimited file, or Parquet file, or read one from a shared folder the server can access. Nothing is catalogued until you create the connection.',
				)}{' '}
			</p>

			<label className="flex flex-col gap-1.5">
				<span className="text-sm font-medium text-heading dark:text-zinc-200">
					{t('Name')}
					<span className="ml-0.5 text-red-500">*</span>
				</span>
				<input
					type="text"
					value={databaseName}
					onChange={({ target }) => onDatabaseNameChange(target.value)}
					placeholder={t('my_dataset')}
					readOnly={nameReadOnly}
					data-testid="file-connection-name"
					className={
						nameReadOnly
							? `${inputClassName} cursor-not-allowed bg-zinc-50 text-secondary dark:bg-zinc-800/60 dark:text-zinc-400`
							: inputClassName
					}
				/>
				<span className="text-xs text-secondary dark:text-zinc-400">
					{nameReadOnly
						? t('The connection name is fixed once created.')
						: t(
								'Letters, digits, and underscores; must not start with a digit. Shown in the catalog and used to route questions. One file becomes one table.',
							)}
				</span>
				{!nameReadOnly &&
					databaseName.trim() !== '' &&
					connectionNameErrorMessage(databaseName) != null && (
						<span className="text-xs text-red-500">
							{connectionNameErrorMessage(databaseName)}
						</span>
					)}
			</label>

			<div className="flex flex-col gap-2">
				<span className="text-sm font-medium text-heading dark:text-zinc-200">
					{t('Source')}
					<span className="ml-0.5 text-red-500">*</span>
				</span>
				<div
					role="tablist"
					aria-label={t('File source')}
					className="grid grid-cols-2 gap-1 rounded-lg border border-zinc-200 bg-zinc-50 p-1 dark:border-zinc-700 dark:bg-zinc-900/60"
				>
					{(
						[
							['upload', 'Upload file'],
							['server', 'Server shared folder'],
						] as const
					).map(([mode, label]) => (
						<button
							key={mode}
							type="button"
							role="tab"
							aria-selected={sourceMode === mode}
							onClick={() => onSourceModeChange(mode)}
							className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
								sourceMode === mode
									? 'bg-white text-heading shadow-sm ring-1 ring-zinc-200 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-600'
									: 'text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-200'
							}`}
						>
							{t(label)}
						</button>
					))}
				</div>
			</div>

			{sourceMode === 'upload' ? (
				<label className="flex flex-col gap-1.5">
					<span className="text-sm font-medium text-heading dark:text-zinc-200">
						{t('File')}
						<span className="ml-0.5 text-red-500">*</span>
					</span>
					<input
						type="file"
						accept={ACCEPT}
						onChange={pickFile}
						data-testid="file-connection-input"
						className={`${inputClassName} file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1 file:text-sm dark:file:bg-zinc-800 dark:file:text-zinc-200`}
					/>
					<span className="text-xs text-secondary dark:text-zinc-400">
						{t('CSV, TSV, XLSX, XLS, or Parquet.')}{' '}
						{existingFileName != null && selectedFileName == null && (
							<>
								{' '}
								{t('Currently loaded:')} {existingFileName}
								{t('. Choose a file to replace it.')}
							</>
						)}
					</span>
				</label>
			) : (
				<div className="flex flex-col gap-2">
					<label className="flex flex-col gap-1.5">
						<span className="text-sm font-medium text-heading dark:text-zinc-200">
							{t('File path')}
							<span className="ml-0.5 text-red-500">*</span>
						</span>
						<div className="flex flex-wrap items-center gap-2">
							<input
								type="text"
								value={serverPath}
								onChange={({ target }) => onServerPathChange(target.value)}
								placeholder="/mnt/shared/sales.xlsx"
								spellCheck={false}
								data-testid="file-connection-server-path"
								className={`${inputClassName} min-w-0 flex-1 font-mono`}
							/>
							<button
								type="button"
								onClick={() => void openBrowser(null)}
								className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-heading hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
							>
								{t('Browse')}{' '}
							</button>
							<button
								type="button"
								onClick={() => onLoadServerPath()}
								disabled={serverPath.trim() === '' || busy}
								className="rounded-lg bg-[#76b900] px-3 py-2 text-sm font-medium text-white hover:bg-[#659f00] disabled:cursor-not-allowed disabled:opacity-50"
							>
								{t('Load data')}{' '}
							</button>
						</div>
						<span className="text-xs text-secondary dark:text-zinc-400">
							{t(
								"Only paths inside the server's configured shared folders can be read.",
							)}{' '}
							{existingFileName != null && (
								<>
									{' '}
									{t('Currently loaded:')} {existingFileName}.
								</>
							)}
						</span>
					</label>

					{browserOpen && (
						<div className="overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50/60 dark:border-zinc-700 dark:bg-zinc-900/60">
							<div className="flex items-center justify-between gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
								<span
									className="min-w-0 truncate font-mono text-xs text-heading dark:text-zinc-200"
									title={listing?.path ?? t('Shared folders')}
								>
									{listing?.path ?? t('Shared folders')}
								</span>
								<div className="flex shrink-0 gap-1">
									<button
										type="button"
										onClick={() => void openBrowser(listing?.parent ?? null)}
										disabled={browseBusy}
										className="rounded px-2 py-1 text-xs text-secondary hover:bg-zinc-200/70 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-700/70"
									>
										{t('Up')}{' '}
									</button>
									<button
										type="button"
										onClick={() => setBrowserOpen(false)}
										className="rounded px-2 py-1 text-xs text-secondary hover:bg-zinc-200/70 dark:text-zinc-400 dark:hover:bg-zinc-700/70"
									>
										{t('Close')}{' '}
									</button>
								</div>
							</div>
							{browseBusy && (
								<div className="flex items-center gap-2 px-3 py-3 text-xs text-secondary dark:text-zinc-400">
									<Spinner
										aria-label={t('Listing shared folders')}
										className="h-3.5 w-3.5"
									/>
									{t('Listing…')}{' '}
								</div>
							)}
							{browseError != null && (
								<p className="px-3 py-3 text-xs text-red-700 dark:text-red-300">
									{browseError}
								</p>
							)}
							{!browseBusy &&
								browseError == null &&
								listing != null &&
								listing.roots.length === 0 && (
									<p className="px-3 py-3 text-xs text-secondary dark:text-zinc-400">
										{t('No shared folders are configured. Set')}{' '}
										<code className="font-mono">FILE_SOURCE_ROOTS</code>{' '}
										{t('on the backend to one or more directories.')}{' '}
									</p>
								)}
							{!browseBusy &&
								browseError == null &&
								listing != null &&
								listing.roots.length > 0 &&
								listing.entries.length === 0 && (
									<p className="px-3 py-3 text-xs text-secondary dark:text-zinc-400">
										{t('No supported files or subfolders here.')}{' '}
									</p>
								)}
							{!browseBusy && browseError == null && listing != null && (
								<ul className="max-h-56 overflow-y-auto py-1">
									{listing.entries.map((entry) => (
										<li key={entry.path}>
											<button
												type="button"
												onClick={() =>
													entry.kind === 'directory'
														? void openBrowser(entry.path)
														: chooseServerFile(entry.path)
												}
												className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-heading hover:bg-[#76b900]/10 dark:text-zinc-200"
											>
												<Icon
													name={
														entry.kind === 'directory'
															? IconName.ChevronRight
															: IconName.Table
													}
													className="h-3.5 w-3.5 shrink-0 text-secondary dark:text-zinc-400"
												/>
												<span className="min-w-0 flex-1 truncate">
													{entry.name}
												</span>
												{entry.is_root === true && (
													<span className="shrink-0 rounded-full border border-zinc-300 px-1.5 text-[10px] uppercase text-secondary dark:border-zinc-600 dark:text-zinc-400">
														{t('Shared')}{' '}
													</span>
												)}
												{entry.kind === 'file' && entry.size != null && (
													<span className="shrink-0 text-[10px] text-secondary dark:text-zinc-500">
														{formatBytes(entry.size)}
													</span>
												)}
											</button>
										</li>
									))}
								</ul>
							)}
						</div>
					)}
				</div>
			)}

			{busy && (
				<div className="flex items-center gap-2 text-sm text-secondary dark:text-zinc-400">
					<Spinner aria-label={t('Reading the file')} className="h-4 w-4" />
					{t('Reading the file…')}{' '}
				</div>
			)}

			{error != null && (
				<p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</p>
			)}

			{preview != null && (
				<div className="flex flex-col gap-3">
					<div className="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary dark:text-zinc-400">
						<span>
							{preview.filename} · {preview.row_count.toLocaleString()} {t('rows ×')}{' '}
							{preview.column_count} {t('columns')}{' '}
						</span>
						{preview.sheets.length > 1 && (
							<label className="flex items-center gap-2">
								<span>{t('Sheet')}</span>
								<select
									value={sheet ?? preview.sheet ?? ''}
									onChange={({ target }) => onSheetChange(target.value)}
									data-testid="file-connection-sheet"
									className={`${inputClassName} px-2 py-1 text-xs`}
								>
									{preview.sheets.map((name) => (
										<option key={name} value={name}>
											{name}
										</option>
									))}
								</select>
							</label>
						)}
						{preview.format === 'csv' && (
							<label className="flex items-center gap-2">
								<span>{t('Delimiter')}</span>
								<select
									value={delimiter}
									onChange={({ target }) => onDelimiterChange(target.value)}
									data-testid="file-connection-delimiter"
									className={`${inputClassName} px-2 py-1 text-xs`}
								>
									<option value="">
										{t('Auto-detect (')}
										{describeDelimiter(preview.delimiter)})
									</option>
									<option value=",">{t('Comma')}</option>
									<option value={'\t'}>{t('Tab')}</option>
									<option value=";">{t('Semicolon')}</option>
									<option value="|">{t('Pipe')}</option>
									<option value=" ">{t('Space')}</option>
									<option value="custom">{t('Other…')}</option>
								</select>
								{delimiter === 'custom' && (
									<input
										type="text"
										maxLength={1}
										value={customDelimiter}
										onChange={({ target }) =>
											onCustomDelimiterChange(target.value)
										}
										aria-label={t('Custom delimiter')}
										data-testid="file-connection-custom-delimiter"
										className={`${inputClassName} w-14 px-2 py-1 text-center text-xs`}
									/>
								)}
							</label>
						)}
					</div>

					{preview.supports_header_row && (
						<div className="flex items-center gap-3">
							<label className="flex items-center gap-2 text-sm text-heading dark:text-zinc-200">
								<span>{t('Header row')}</span>
								<input
									type="number"
									min={1}
									max={preview.rows.length}
									value={headerRow + 1}
									onChange={({ target }) => {
										const next = Number.parseInt(target.value, 10);
										if (Number.isFinite(next)) {
											onHeaderRowChange(
												Math.min(
													Math.max(next - 1, 0),
													preview.rows.length - 1,
												),
											);
										}
									}}
									data-testid="file-connection-header-row"
									className={`${inputClassName} w-20 px-2 py-1`}
								/>
							</label>
							<span className="text-xs text-secondary dark:text-zinc-400">
								{t('Click a row to use it as the column names.')}{' '}
							</span>
						</div>
					)}

					<div className="flex items-center justify-between gap-2">
						<span className="text-xs text-secondary dark:text-zinc-400">
							{t('Click a column header to include or exclude it.')}
						</span>
						<button
							type="button"
							onClick={() =>
								onSelectAllColumns(
									!(
										selectedColumns.length > 0 &&
										selectedColumns.every(Boolean)
									),
								)
							}
							className="shrink-0 text-xs font-medium text-[#76b900] hover:underline"
						>
							{selectedColumns.length > 0 && selectedColumns.every(Boolean)
								? t('Deselect all')
								: t('Select all')}
						</button>
					</div>

					<div className="max-h-[260px] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="min-w-full border-collapse text-xs">
							<thead>
								<tr className="sticky top-0 z-10 bg-zinc-50 text-[11px] dark:bg-zinc-900">
									<th className="w-10 border-r border-zinc-200 bg-zinc-100 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-800" />
									{columnNames.map((name, index) => {
										const selected = selectedColumns[index] !== false;
										return (
											<th
												key={index}
												className={`max-w-[220px] border-r border-zinc-200 p-0 text-left font-medium transition-colors dark:border-zinc-700 ${
													selected
														? 'bg-zinc-200 text-heading hover:bg-zinc-300 dark:bg-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-600'
														: 'bg-zinc-100 text-zinc-400 hover:bg-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-500 dark:hover:bg-zinc-700'
												}`}
											>
												<button
													type="button"
													onClick={() => onColumnToggle(index)}
													aria-pressed={selected}
													title={t('Include column {0}', {
														0: index + 1,
													})}
													className="flex w-full items-center gap-1 px-2 py-1"
												>
													<span
														className={`truncate ${selected ? '' : 'line-through'}`}
													>
														{name || `${t('Column')} ${index + 1}`}
													</span>
												</button>
											</th>
										);
									})}
								</tr>
							</thead>
							<tbody>
								{preview.rows.map((row, rowIndex) => (
									<tr
										key={rowIndex}
										onClick={
											preview.supports_header_row
												? () => onHeaderRowChange(rowIndex)
												: undefined
										}
										className={
											preview.supports_header_row && rowIndex === headerRow
												? 'cursor-pointer bg-[#76b900]/15 font-medium'
												: preview.supports_header_row
													? 'cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/60'
													: ''
										}
									>
										<td className="w-10 select-none border-r border-zinc-200 px-2 py-1 text-right text-secondary dark:border-zinc-700 dark:text-zinc-500">
											{rowIndex + 1}
										</td>
										{Array.from(
											{ length: preview.column_count },
											(_, columnIndex) => {
												const selected =
													selectedColumns[columnIndex] !== false;
												return (
													<td
														key={columnIndex}
														className={`max-w-[220px] truncate whitespace-nowrap border-r border-zinc-100 px-2 py-1 last:border-r-0 dark:border-zinc-800 ${
															selected
																? 'bg-zinc-100/70 dark:bg-zinc-800/40'
																: 'text-zinc-400 opacity-70 dark:text-zinc-500'
														}`}
													>
														{row[columnIndex] ?? ''}
													</td>
												);
											},
										)}
									</tr>
								))}
							</tbody>
						</table>
					</div>

					<div className="flex flex-col gap-2">
						<span className="text-sm font-medium text-heading dark:text-zinc-200">
							{t('Column names')}{' '}
						</span>
						<span className="text-xs text-secondary dark:text-zinc-400">
							{t('Columns you deselect are left out of the connection.')}
						</span>
						<div className="grid max-h-[220px] grid-cols-2 gap-2 overflow-y-auto pr-1">
							{columnNames.map((name, index) => (
								<label key={index} className="flex flex-col gap-1">
									<span className="text-[11px] text-secondary dark:text-zinc-500">
										{t('Column')} {index + 1}
									</span>
									<input
										type="text"
										value={name}
										onChange={({ target }) =>
											onColumnNameChange(index, target.value)
										}
										disabled={selectedColumns[index] === false}
										data-testid={`file-connection-column-${index}`}
										className={`${inputClassName} px-2 py-1 text-xs ${
											selectedColumns[index] === false
												? 'cursor-not-allowed opacity-50'
												: ''
										}`}
									/>
								</label>
							))}
						</div>
						<span className="text-xs text-secondary dark:text-zinc-400">
							{t(
								'Rename columns to the names people should see in questions and answers. Blank names fall back to Column 1, Column 2, …',
							)}{' '}
						</span>
					</div>
				</div>
			)}
		</div>
	);
};
