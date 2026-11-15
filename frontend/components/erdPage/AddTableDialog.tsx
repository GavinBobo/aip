// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

export type DraftTable = {
	name: string;
	columns: { name: string; data_type: string; is_primary_key: boolean }[];
};

type AddTableDialogProps = {
	open: boolean;
	onClose: () => void;
	onCreate: (table: DraftTable) => void;
};

const parseColumns = (text: string) => {
	const columns: DraftTable['columns'] = [];
	for (const line of text.split('\n')) {
		const trimmed = line.trim();
		if (trimmed === '') continue;
		const primary = /\bpk\b/i.test(trimmed);
		const withoutSettings = trimmed.replace(/\[[^\]]*\]/g, '').trim();
		const [name, ...rest] = withoutSettings.split(/\s+/);
		if (!name) continue;
		columns.push({
			name,
			data_type: rest.join(' ') || 'text',
			is_primary_key: primary,
		});
	}
	return columns;
};

export const AddTableDialog = ({ open, onClose, onCreate }: AddTableDialogProps) => {
	const [name, setName] = useState('');
	const [columns, setColumns] = useState('');

	return (
		<Modal open={open} onClose={onClose} className="w-full max-w-xl">
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
			<div className="space-y-3 p-5">
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
					{t('Columns, one per line: name type [pk]')}
					<textarea
						value={columns}
						onChange={(event) => setColumns(event.target.value)}
						spellCheck={false}
						placeholder={'id bigint [pk]\ncreated_at timestamp'}
						className="mt-1 h-32 w-full resize-none rounded-lg border border-zinc-300 bg-white p-2 font-mono text-xs text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
					/>
				</label>
				<div className="flex justify-end gap-2">
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={onClose}
					>
						{t('Cancel')}
					</Button>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.REGULAR}
						type="button"
						disabled={name.trim() === ''}
						onClick={() => {
							onCreate({ name: name.trim(), columns: parseColumns(columns) });
							onClose();
						}}
					>
						{t('Add table')}
					</Button>
				</div>
			</div>
		</Modal>
	);
};
