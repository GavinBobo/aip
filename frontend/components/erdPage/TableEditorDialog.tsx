// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdColumn, ErdNode } from '@/types/erd';

type DraftRow = {
	key: string;
	name: string;
	data_type: string;
	is_primary_key: boolean;
	is_unique: boolean;
	is_nullable: boolean;
	note: string;
};

const toRows = (columns: ErdColumn[]): DraftRow[] =>
	columns.map((column, index) => ({
		key: `existing-${index}-${column.name}`,
		name: column.name,
		data_type: column.data_type ?? '',
		is_primary_key: column.is_primary_key,
		is_unique: column.is_unique === true,
		is_nullable: column.is_nullable !== false,
		note: column.note ?? '',
	}));

type TableEditorDialogProps = {
	node: ErdNode;
	busy: boolean;
	onClose: () => void;
	onSave: (patch: {
		name: string;
		note: string | null;
		indexes: { name: string | null; columns: string[]; unique: boolean }[];
		columns: {
			name: string;
			data_type: string;
			is_primary_key: boolean;
			is_unique: boolean;
			is_nullable: boolean;
			note: string | null;
		}[];
		column_notes: Record<string, string>;
	}) => void;
};

let rowSeed = 0;

export const TableEditorDialog = ({ node, busy, onClose, onSave }: TableEditorDialogProps) => {
	const [name, setName] = useState(node.name);
	const [note, setNote] = useState(node.note ?? '');
	const [rows, setRows] = useState<DraftRow[]>(() => toRows(node.columns));
	const [indexes, setIndexes] = useState(() =>
		node.indexes.map((index, position) => ({
			key: `index-${position}`,
			name: index.name ?? '',
			columns: index.columns.join(', '),
			unique: index.unique,
		})),
	);
	// Catalog tables mirror the source database: their name and columns are
	// read-only here, but the note is the modeller's own annotation.
	const schemaLocked = node.table_id != null;

	const updateRow = (key: string, patch: Partial<DraftRow>) => {
		setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
	};

	const addRow = () => {
		rowSeed += 1;
		setRows((current) => [
			...current,
			{
				key: `new-${rowSeed}`,
				name: '',
				data_type: 'text',
				is_primary_key: false,
				is_unique: false,
				is_nullable: true,
				note: '',
			},
		]);
	};

	const validRows = rows.filter((row) => row.name.trim() !== '');

	return (
		<Modal open onClose={onClose} className="w-full max-w-3xl">
			<header className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<div>
					<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Edit table')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{schemaLocked
							? t(
									'Columns come from the catalog. Their aliases and the table note are yours to edit.',
								)
							: t('This table lives only on the canvas; the catalog is not changed.')}
					</p>
				</div>
				<Button
					theme={ButtonTheme.IconNeutral}
					size={Size.SMALL}
					iconOnly
					onClick={onClose}
					aria-label={t('Close')}
				>
					✕
				</Button>
			</header>

			<div className="space-y-4 p-5">
				<label className="block text-xs font-medium text-body dark:text-zinc-300">
					{t('Table name')}
					<input
						value={name}
						disabled={schemaLocked}
						onChange={(event) => setName(event.target.value)}
						className="mt-1 h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
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
					<div className="grid grid-cols-[1fr_0.9fr_1fr_auto] gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-[11px] font-medium text-secondary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
						<span>{t('Column')}</span>
						<span>{t('Type')}</span>
						<span>{t('Alias')}</span>
						<span className="text-right">{t('Constraints')}</span>
					</div>
					<div className="max-h-72 overflow-y-auto">
						{rows.map((row) => (
							<div
								key={row.key}
								className="grid grid-cols-[1fr_0.9fr_1fr_auto] items-center gap-2 border-b border-zinc-100 px-3 py-2 last:border-b-0 dark:border-zinc-800"
							>
								<input
									value={row.name}
									disabled={schemaLocked}
									onChange={(event) =>
										updateRow(row.key, { name: event.target.value })
									}
									placeholder="column_name"
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
								/>
								<input
									value={row.data_type}
									disabled={schemaLocked}
									onChange={(event) =>
										updateRow(row.key, { data_type: event.target.value })
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
									title={t('Shown in grey under the column name on the canvas')}
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
								/>
								<div className="flex items-center gap-2 text-[11px] text-body dark:text-zinc-300">
									<label className="flex items-center gap-1">
										<input
											type="checkbox"
											disabled={schemaLocked}
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
											disabled={schemaLocked}
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
											disabled={schemaLocked}
											checked={!row.is_nullable}
											onChange={(event) =>
												updateRow(row.key, {
													is_nullable: !event.target.checked,
												})
											}
										/>
										{t('required')}
									</label>
									{!schemaLocked && (
										<Button
											theme={ButtonTheme.IconDanger}
											size={Size.SMALL}
											iconOnly
											onClick={() =>
												setRows((current) =>
													current.filter((item) => item.key !== row.key),
												)
											}
											aria-label={t('Remove column {0}', {
												0: row.name || '?',
											})}
										>
											✕
										</Button>
									)}
								</div>
							</div>
						))}
					</div>
				</div>

				{!schemaLocked && (
					<Button theme={ButtonTheme.Secondary} size={Size.SMALL} onClick={addRow}>
						{t('Add column')}
					</Button>
				)}

				{!schemaLocked && (
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
										setIndexes((current) =>
											current.map((row) =>
												row.key === index.key
													? { ...row, name: event.target.value }
													: row,
											),
										)
									}
									placeholder={t('index name (optional)')}
									className="h-8 rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
								/>
								<input
									value={index.columns}
									onChange={(event) =>
										setIndexes((current) =>
											current.map((row) =>
												row.key === index.key
													? { ...row, columns: event.target.value }
													: row,
											),
										)
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
												setIndexes((current) =>
													current.map((row) =>
														row.key === index.key
															? {
																	...row,
																	unique: event.target.checked,
																}
															: row,
													),
												)
											}
										/>
										{t('unique')}
									</label>
									<Button
										theme={ButtonTheme.IconDanger}
										size={Size.SMALL}
										iconOnly
										onClick={() =>
											setIndexes((current) =>
												current.filter((row) => row.key !== index.key),
											)
										}
										aria-label={t('Remove index {0}', {
											0: index.name || index.columns || '?',
										})}
									>
										✕
									</Button>
								</div>
							</div>
						))}
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.SMALL}
							onClick={() => {
								rowSeed += 1;
								setIndexes((current) => [
									...current,
									{
										key: `index-${rowSeed}`,
										name: '',
										columns: '',
										unique: false,
									},
								]);
							}}
						>
							{t('Add index')}
						</Button>
					</section>
				)}

				<div className="flex justify-end gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-700">
					<Button theme={ButtonTheme.Secondary} size={Size.REGULAR} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.REGULAR}
						loading={busy}
						disabled={name.trim() === ''}
						onClick={() =>
							onSave({
								name: name.trim(),
								note: note.trim() === '' ? null : note.trim(),
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
								columns: validRows.map((row) => ({
									name: row.name.trim(),
									data_type: row.data_type.trim() || 'text',
									is_primary_key: row.is_primary_key,
									is_unique: row.is_unique,
									is_nullable: row.is_nullable,
									note: row.note.trim() === '' ? null : row.note.trim(),
								})),
								// An empty alias is sent as an empty string so clearing a
								// note removes it instead of being ignored.
								column_notes: Object.fromEntries(
									validRows.map((row) => [row.name.trim(), row.note.trim()]),
								),
							})
						}
					>
						{t('Save')}
					</Button>
				</div>
			</div>
		</Modal>
	);
};
