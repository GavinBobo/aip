// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdVersion } from '@/types/erd';

type VersionsDialogProps = {
	open: boolean;
	versions: ErdVersion[];
	busy: boolean;
	readOnly: boolean;
	onClose: () => void;
	onCreate: (label: string) => void;
	onRestore: (version: ErdVersion) => void;
	onDelete: (version: ErdVersion) => void;
};

export const VersionsDialog = ({
	open,
	versions,
	busy,
	readOnly,
	onClose,
	onCreate,
	onRestore,
	onDelete,
}: VersionsDialogProps) => {
	const [label, setLabel] = useState('');

	return (
		<Modal open={open} onClose={onClose} className="w-full max-w-2xl">
			<header className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<div>
					<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Version history')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{t(
							'A version stores the tables, relationships, notes and areas as they are now.',
						)}
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

			{!readOnly && (
				<div className="flex items-center gap-2 border-b border-zinc-200 px-5 py-3 dark:border-zinc-700">
					<input
						value={label}
						onChange={(event) => setLabel(event.target.value)}
						placeholder={t('Version label (optional)')}
						className="h-9 min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
					/>
					<Button
						theme={ButtonTheme.Primary}
						size={Size.REGULAR}
						loading={busy}
						onClick={() => {
							onCreate(label.trim());
							setLabel('');
						}}
					>
						{t('Save current version')}
					</Button>
				</div>
			)}

			<div className="max-h-[50dvh] overflow-y-auto p-2">
				{versions.length === 0 ? (
					<p className="p-4 text-xs text-secondary dark:text-zinc-400">
						{t('No saved versions yet')}
					</p>
				) : (
					<ul className="space-y-1">
						{versions.map((version) => (
							<li
								key={version.id}
								className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800"
							>
								<div className="min-w-0 flex-1">
									<p className="truncate text-sm text-body dark:text-zinc-200">
										{version.label || t('Untitled version')}
									</p>
									<p className="text-[11px] text-secondary dark:text-zinc-400">
										{version.created
											? new Date(version.created).toLocaleString()
											: ''}
										{' · '}
										{t('{0} tables / {1} relationships', {
											0: String(version.node_count),
											1: String(version.relationship_count),
										})}
									</p>
								</div>
								{!readOnly && (
									<>
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											onClick={() => onRestore(version)}
										>
											{t('Restore')}
										</Button>
										<Button
											theme={ButtonTheme.IconDanger}
											size={Size.SMALL}
											iconOnly
											onClick={() => onDelete(version)}
											aria-label={t('Delete version')}
										>
											✕
										</Button>
									</>
								)}
							</li>
						))}
					</ul>
				)}
			</div>
		</Modal>
	);
};
