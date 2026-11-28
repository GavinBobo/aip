// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { erdApi } from '@/api/erd';
import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { COLUMN_STYLE_OPTIONS, columnStyleClass } from '@/lib/erd/columnAppearance';
import { SQL_DIALECTS } from '@/lib/erd/dialects';
import type { ErdCardinality, ErdColumnStyle, ErdIndex, SqlDialect } from '@/types/erd';

type AddMode = 'sql' | 'custom';

export type DraftColumn = {
	name: string;
	data_type: string;
	is_primary_key: boolean;
	is_unique: boolean;
	is_nullable: boolean;
	note: string | null;
	color: string | null;
	style: ErdColumnStyle | null;
};

export type DraftTable = {
	name: string;
	category: string | null;
	note: string | null;
	columns: DraftColumn[];
	indexes: ErdIndex[];
};

export type DraftRelationship = {
	source: string;
	target: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
	label: string | null;
};

type DraftRow = Omit<DraftColumn, 'note'> & {
	key: string;
	note: string;
};

type DraftIndexRow = {
	key: string;
	name: string;
	columns: string;
	unique: boolean;
};

let rowSeed = 0;

const emptyRow = (): DraftRow => {
	rowSeed += 1;
	return {
		key: `column-${rowSeed}`,
		name: '',
		data_type: 'text',
		is_primary_key: false,
		is_unique: false,
		is_nullable: true,
		note: '',
		color: null,
		style: null,
	};
};

const SAMPLE_SQL: Record<SqlDialect, string> = {
	sqlserver:
		'CREATE TABLE [dbo].[audit_log] (\n  [id] bigint PRIMARY KEY,\n  [created_at] datetime2\n);',
	postgres:
		'CREATE TABLE public.audit_log (\n  id bigint PRIMARY KEY,\n  created_at timestamp\n);',
	mysql: 'CREATE TABLE `audit_log` (\n  `id` bigint PRIMARY KEY,\n  `created_at` datetime\n);',
	mariadb: 'CREATE TABLE `audit_log` (\n  `id` bigint PRIMARY KEY,\n  `created_at` datetime\n);',
	oracle: 'CREATE TABLE "AUDIT_LOG" (\n  "ID" NUMBER PRIMARY KEY,\n  "CREATED_AT" TIMESTAMP\n);',
	sqlite: 'CREATE TABLE audit_log (\n  id INTEGER PRIMARY KEY,\n  created_at TEXT\n);',
};

type AddTableDialogProps = {
	open: boolean;
	zoneId: string | null;
	onClose: () => void;
	onCreate: (tables: DraftTable[], relationships: DraftRelationship[]) => void | Promise<void>;
};

export const AddTableDialog = ({ open, zoneId, onClose, onCreate }: AddTableDialogProps) => {
	const [mode, setMode] = useState<AddMode>('sql');
	const [dialect, setDialect] = useState<SqlDialect>('sqlserver');
	const [sql, setSql] = useState('');
	const [name, setName] = useState('');
	const [category, setCategory] = useState('');
	const [note, setNote] = useState('');
	const [rows, setRows] = useState<DraftRow[]>(() => [emptyRow()]);
	const [indexes, setIndexes] = useState<DraftIndexRow[]>([]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const updateRow = (key: string, patch: Partial<DraftRow>) => {
		setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
	};

	const addRow = () => {
		setRows((current) => [...current, emptyRow()]);
	};

	const removeRow = (key: string) => {
		setRows((current) =>
			current.length === 1 ? current : current.filter((row) => row.key !== key),
		);
	};

	const addIndex = () => {
		rowSeed += 1;
		setIndexes((current) => [
			...current,
			{ key: `index-${rowSeed}`, name: '', columns: '', unique: false },
		]);
	};

	const updateIndex = (key: string, patch: Partial<DraftIndexRow>) => {
		setIndexes((current) =>
			current.map((index) => (index.key === key ? { ...index, ...patch } : index)),
		);
	};

	const removeIndex = (key: string) => {
		setIndexes((current) => current.filter((index) => index.key !== key));
	};

	const validRows = rows.filter((row) => row.name.trim() !== '');

	const submitCustom = () => {
		if (name.trim() === '') return;
		onCreate(
			[
				{
					name: name.trim(),
					category: category.trim() === '' ? null : category.trim(),
					note: note.trim() === '' ? null : note.trim(),
					columns: validRows.map((row) => ({
						name: row.name.trim(),
						data_type: row.data_type.trim() || 'text',
						is_primary_key: row.is_primary_key,
						is_unique: row.is_unique,
						is_nullable: row.is_nullable,
						note: row.note.trim() === '' ? null : row.note.trim(),
						color: row.color,
						style: row.style,
					})),
					indexes: indexes
						.map((index) => ({
							name: index.name.trim() || null,
							columns: index.columns
								.split(',')
								.map((column) => column.trim())
								.filter(Boolean),
							unique: index.unique,
						}))
						.filter((index) => index.columns.length > 0),
				},
			],
			[],
		);
		onClose();
	};

	const submitSql = async () => {
		if (!zoneId || sql.trim() === '') return;
		setBusy(true);
		setError(null);
		const response = await erdApi.parseDdl({
			zone_id: zoneId,
			dialect,
			content: sql,
		});
		setBusy(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to parse the SQL'));
			return;
		}
		const result = response.data;
		if (result.tables.length === 0) {
			setError(t('No CREATE TABLE statements found'));
			return;
		}
		onCreate(
			result.tables.map((table) => ({
				name: table.name,
				category: null,
				note: null,
				columns: table.columns.map((column) => ({
					name: column.name,
					data_type: column.data_type ?? 'text',
					is_primary_key: column.is_primary_key,
					is_unique: column.is_unique === true,
					is_nullable: column.is_nullable !== false,
					note: column.note ?? null,
					color: column.color ?? null,
					style: column.style ?? null,
				})),
				indexes: table.indexes ?? [],
			})),
			result.relationships.map((relationship) => ({
				source: relationship.source,
				target: relationship.target,
				source_columns: relationship.source_columns,
				target_columns: relationship.target_columns,
				cardinality: relationship.cardinality,
				label: relationship.label,
			})),
		);
		onClose();
	};

	const canSubmit = mode === 'sql' ? Boolean(zoneId) && sql.trim() !== '' : name.trim() !== '';

	return (
		<Modal
			open={open}
			onClose={onClose}
			className="max-h-[90vh] w-full max-w-5xl overflow-y-auto"
		>
			<header className="border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
					{t('Add a table')}
				</h2>
				<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
					{t(
						'Drawn tables exist only on this canvas; they are not taken from the catalog.',
					)}
				</p>
			</header>

			<div className="space-y-4 p-5">
				<div
					role="tablist"
					className="flex w-fit gap-1 rounded-lg bg-zinc-100 p-1 dark:bg-zinc-800"
				>
					{(
						[
							{ value: 'sql', label: t('SQL mode') },
							{ value: 'custom', label: t('Custom mode') },
						] as const
					).map((option) => (
						<button
							key={option.value}
							type="button"
							role="tab"
							aria-selected={mode === option.value}
							onClick={() => {
								setMode(option.value);
								setError(null);
							}}
							className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
								mode === option.value
									? 'bg-white text-heading shadow-sm dark:bg-zinc-700 dark:text-zinc-100'
									: 'text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-200'
							}`}
						>
							{option.label}
						</button>
					))}
				</div>

				{error && (
					<div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
						{error}
					</div>
				)}

				{mode === 'sql' ? (
					<>
						<label className="block text-xs font-medium text-body dark:text-zinc-300">
							{t('Database type')}
							<select
								value={dialect}
								onChange={(event) => setDialect(event.target.value as SqlDialect)}
								className="mt-1 h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							>
								{SQL_DIALECTS.map((option) => (
									<option key={option.value} value={option.value}>
										{option.label}
									</option>
								))}
							</select>
						</label>
						<label className="block text-xs font-medium text-body dark:text-zinc-300">
							{t('CREATE TABLE SQL')}
							<textarea
								value={sql}
								onChange={(event) => setSql(event.target.value)}
								spellCheck={false}
								placeholder={SAMPLE_SQL[dialect]}
								className="mt-1 h-56 w-full resize-none rounded-lg border border-zinc-300 bg-white p-2 font-mono text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							/>
						</label>
						<p className="text-[11px] text-secondary dark:text-zinc-400">
							{t(
								'Multiple CREATE TABLE statements are added together, including foreign keys between them.',
							)}
						</p>
					</>
				) : (
					<>
						<label className="block text-xs font-medium text-body dark:text-zinc-300">
							{t('Table name')}
							<input
								value={name}
								onChange={(event) => setName(event.target.value)}
								placeholder="public.audit_log"
								className="mt-1 h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							/>
						</label>

						<label className="block text-xs font-medium text-body dark:text-zinc-300">
							{t('Category')}
							<input
								value={category}
								onChange={(event) => setCategory(event.target.value)}
								maxLength={64}
								placeholder={t('e.g. fact, dimension, staging')}
								className="mt-1 h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							/>
						</label>

						<label className="block text-xs font-medium text-body dark:text-zinc-300">
							{t('Note')}
							<textarea
								value={note}
								onChange={(event) => setNote(event.target.value)}
								placeholder={t('What is this table for?')}
								className="mt-1 h-20 w-full resize-none rounded-lg border border-zinc-300 bg-white p-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							/>
						</label>

						<div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
							<div className="grid grid-cols-[1.1fr_0.9fr_1fr_auto_auto] items-center gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-[11px] font-medium text-secondary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
								<span>{t('Column')}</span>
								<span>{t('Type')}</span>
								<span>{t('Alias')}</span>
								<span>{t('Appearance')}</span>
								<span className="text-right">{t('Constraints')}</span>
							</div>
							<div className="max-h-72 overflow-y-auto">
								{rows.map((row) => (
									<div
										key={row.key}
										className="grid grid-cols-[1.1fr_0.9fr_1fr_auto_auto] items-center gap-2 border-b border-zinc-100 px-3 py-2 last:border-b-0 dark:border-zinc-800"
									>
										<input
											value={row.name}
											onChange={(event) =>
												updateRow(row.key, { name: event.target.value })
											}
											placeholder="column_name"
											style={{ color: row.color ?? undefined }}
											className={`h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200 ${columnStyleClass(
												row.style,
											)}`}
										/>
										<input
											value={row.data_type}
											onChange={(event) =>
												updateRow(row.key, {
													data_type: event.target.value,
												})
											}
											placeholder="text"
											className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
										/>
										<input
											value={row.note}
											onChange={(event) =>
												updateRow(row.key, { note: event.target.value })
											}
											placeholder={t('Shown in grey under the name')}
											className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
										/>
										<div className="flex items-center gap-1">
											<input
												type="color"
												value={row.color ?? '#71717a'}
												onChange={(event) =>
													updateRow(row.key, {
														color: event.target.value,
													})
												}
												aria-label={t('Column color')}
												title={t('Column color')}
												className="h-7 w-7 cursor-pointer rounded border border-zinc-300 bg-white p-0.5 dark:border-zinc-600 dark:bg-zinc-900"
											/>
											<button
												type="button"
												onClick={() => updateRow(row.key, { color: null })}
												className="h-7 w-6 rounded text-[11px] text-secondary hover:bg-zinc-100 dark:hover:bg-zinc-800"
												aria-label={t('Clear column color')}
												title={t('Clear column color')}
											>
												×
											</button>
											<select
												value={row.style ?? 'normal'}
												onChange={(event) =>
													updateRow(row.key, {
														style:
															event.target.value === 'normal'
																? null
																: (event.target
																		.value as ErdColumnStyle),
													})
												}
												aria-label={t('Column style')}
												title={t('Column style')}
												className="h-7 min-w-0 rounded-md border border-zinc-300 bg-white px-1 text-[11px] text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
											>
												{COLUMN_STYLE_OPTIONS.map((option) => (
													<option key={option.value} value={option.value}>
														{t(option.label)}
													</option>
												))}
											</select>
										</div>
										<div className="flex items-center justify-end gap-2 text-[11px] text-body dark:text-zinc-300">
											<label className="flex items-center gap-1">
												<input
													type="checkbox"
													checked={row.is_primary_key}
													onChange={(event) =>
														updateRow(row.key, {
															is_primary_key: event.target.checked,
														})
													}
												/>
												PK
											</label>
											<label className="flex items-center gap-1">
												<input
													type="checkbox"
													checked={row.is_unique}
													onChange={(event) =>
														updateRow(row.key, {
															is_unique: event.target.checked,
														})
													}
												/>
												{t('unique')}
											</label>
											<label className="flex items-center gap-1">
												<input
													type="checkbox"
													checked={!row.is_nullable}
													onChange={(event) =>
														updateRow(row.key, {
															is_nullable: !event.target.checked,
														})
													}
												/>
												{t('required')}
											</label>
											<Button
												theme={ButtonTheme.IconDanger}
												size={Size.SMALL}
												iconOnly
												type="button"
												onClick={() => removeRow(row.key)}
												disabled={rows.length === 1}
												aria-label={t('Remove column {0}', {
													0: row.name || '?',
												})}
											>
												×
											</Button>
										</div>
									</div>
								))}
							</div>
						</div>
						<Button theme={ButtonTheme.Secondary} size={Size.SMALL} onClick={addRow}>
							{t('Add column')}
						</Button>

						<section className="space-y-2">
							<h3 className="text-xs font-medium text-body dark:text-zinc-300">
								{t('Indexes')}
							</h3>
							{indexes.length === 0 && (
								<p className="text-[11px] text-secondary dark:text-zinc-400">
									{t('No indexes')}
								</p>
							)}
							{indexes.map((index) => (
								<div
									key={index.key}
									className="grid grid-cols-[1fr_1.4fr_auto] items-center gap-2"
								>
									<input
										value={index.name}
										onChange={(event) =>
											updateIndex(index.key, { name: event.target.value })
										}
										placeholder={t('index name (optional)')}
										className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
									/>
									<input
										value={index.columns}
										onChange={(event) =>
											updateIndex(index.key, { columns: event.target.value })
										}
										placeholder={t('columns, comma separated')}
										className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
									/>
									<div className="flex items-center gap-2 text-[11px] text-body dark:text-zinc-300">
										<label className="flex items-center gap-1">
											<input
												type="checkbox"
												checked={index.unique}
												onChange={(event) =>
													updateIndex(index.key, {
														unique: event.target.checked,
													})
												}
											/>
											{t('unique')}
										</label>
										<Button
											theme={ButtonTheme.IconDanger}
											size={Size.SMALL}
											iconOnly
											onClick={() => removeIndex(index.key)}
											aria-label={t('Remove index {0}', {
												0: index.name || index.columns || '?',
											})}
										>
											×
										</Button>
									</div>
								</div>
							))}
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								onClick={addIndex}
							>
								{t('Add index')}
							</Button>
						</section>
					</>
				)}

				<div className="flex justify-end gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-700">
					<Button theme={ButtonTheme.Secondary} size={Size.REGULAR} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.REGULAR}
						loading={busy}
						disabled={!canSubmit}
						onClick={() => {
							if (mode === 'sql') void submitSql();
							else submitCustom();
						}}
					>
						{mode === 'sql' ? t('Add from SQL') : t('Add table')}
					</Button>
				</div>
			</div>
		</Modal>
	);
};
