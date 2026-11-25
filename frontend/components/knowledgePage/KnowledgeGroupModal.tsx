// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo, useState } from 'react';

import { knowledgeApi, type KnowledgeConcept, type KnowledgeConceptGroup } from '@/api/knowledge';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

export const KnowledgeGroupModal = ({
	networkId,
	concepts,
	onClose,
	onCreated,
}: {
	networkId: string;
	concepts: KnowledgeConcept[];
	onClose: () => void;
	onCreated: (group: KnowledgeConceptGroup) => void;
}) => {
	const [name, setName] = useState('');
	const [description, setDescription] = useState('');
	const [query, setQuery] = useState('');
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const filtered = useMemo(() => {
		const needle = query.trim().toLowerCase();
		if (!needle) return concepts;
		return concepts.filter(
			(concept) =>
				concept.name.toLowerCase().includes(needle) ||
				concept.aliases.some((alias) => alias.toLowerCase().includes(needle)),
		);
	}, [concepts, query]);

	const toggle = (id: string) => {
		setSelected((current) => {
			const next = new Set(current);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	};

	const submit = async () => {
		if (!name.trim() || saving) return;
		setSaving(true);
		setError(null);
		const response = await knowledgeApi.createConceptGroup(networkId, {
			name: name.trim(),
			description: description.trim() || undefined,
			concept_ids: [...selected],
		});
		setSaving(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to create the concept group.'));
			return;
		}
		onCreated(response.data);
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('New concept group')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="flex max-h-[82vh] w-full max-w-xl flex-col rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('New concept group')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{t(
								'Group related concepts for navigation, context loading and BKN export.',
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
						<Icon name={IconName.Close} className="h-4 w-4" />
					</Button>
				</div>
				<div className="space-y-3 px-6 py-4">
					<input
						className={inputClassName}
						value={name}
						onChange={(event) => setName(event.target.value)}
						placeholder={t('Group name')}
						autoFocus
					/>
					<input
						className={inputClassName}
						value={description}
						onChange={(event) => setDescription(event.target.value)}
						placeholder={t('Description (optional)')}
					/>
					<input
						className={inputClassName}
						value={query}
						onChange={(event) => setQuery(event.target.value)}
						placeholder={t('Search concepts')}
					/>
				</div>
				<div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
					{filtered.length === 0 ? (
						<p className="px-3 py-8 text-center text-sm text-secondary">
							{t('No concepts match this search.')}
						</p>
					) : (
						filtered.map((concept) => (
							<label
								key={concept.id}
								className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 hover:bg-zinc-100 dark:hover:bg-zinc-800"
							>
								<input
									type="checkbox"
									checked={selected.has(concept.id)}
									onChange={() => toggle(concept.id)}
									className="h-4 w-4 accent-[#76b900]"
								/>
								<span className="min-w-0">
									<span className="block truncate text-sm font-medium text-heading dark:text-zinc-100">
										{concept.name}
									</span>
									<span className="block truncate text-[11px] text-secondary">
										{concept.description || t('No description yet.')}
									</span>
								</span>
							</label>
						))
					)}
				</div>
				{error && <p className="px-6 pb-2 text-sm text-red-600">{error}</p>}
				<div className="flex items-center justify-between gap-3 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
					<span className="text-xs text-secondary">
						{t('{count} concepts selected', { count: selected.size })}
					</span>
					<div className="flex gap-2">
						<Button theme={ButtonTheme.Secondary} onClick={onClose}>
							{t('Cancel')}
						</Button>
						<Button loading={saving} disabled={!name.trim()} onClick={submit}>
							{t('Create')}
						</Button>
					</div>
				</div>
			</div>
		</div>
	);
};
