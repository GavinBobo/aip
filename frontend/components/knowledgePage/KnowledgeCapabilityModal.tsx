// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { knowledgeApi, type KnowledgeCapability } from '@/api/knowledge';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

export const KnowledgeCapabilityModal = ({
	networkId,
	onClose,
	onCreated,
}: {
	networkId: string;
	onClose: () => void;
	onCreated: (capability: KnowledgeCapability) => void;
}) => {
	const [name, setName] = useState('');
	const [kind, setKind] = useState<KnowledgeCapability['kind']>('skill');
	const [description, setDescription] = useState('');
	const [config, setConfig] = useState('{}');
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const submit = async () => {
		if (!name.trim() || saving) return;
		let parsedConfig: Record<string, unknown> = {};
		try {
			parsedConfig = config.trim() ? JSON.parse(config) : {};
		} catch {
			setError(t('Configuration must be valid JSON.'));
			return;
		}
		setSaving(true);
		setError(null);
		const response = await knowledgeApi.createCapability(networkId, {
			name: name.trim(),
			kind,
			description: description.trim() || undefined,
			config: parsedConfig,
		});
		setSaving(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to create the capability.'));
			return;
		}
		onCreated(response.data);
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('New capability')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="w-full max-w-xl rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('New capability')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{t(
								'Declare a Skill, Function, MCP tool or knowledge base this network depends on.',
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
						placeholder={t('Capability name')}
						autoFocus
					/>
					<select
						className={inputClassName}
						value={kind}
						onChange={(event) =>
							setKind(event.target.value as KnowledgeCapability['kind'])
						}
					>
						<option value="skill">{t('Skill')}</option>
						<option value="function">{t('Function')}</option>
						<option value="mcp_tool">{t('MCP tool')}</option>
						<option value="knowledge_base">{t('Knowledge base')}</option>
					</select>
					<input
						className={inputClassName}
						value={description}
						onChange={(event) => setDescription(event.target.value)}
						placeholder={t('Description (optional)')}
					/>
					<textarea
						className="min-h-24 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-body outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						value={config}
						onChange={(event) => setConfig(event.target.value)}
						placeholder='{"box_id": "...", "tool_id": "..."}'
					/>
				</div>
				{error && <p className="px-6 pb-2 text-sm text-red-600">{error}</p>}
				<div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
					<Button theme={ButtonTheme.Secondary} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button loading={saving} disabled={!name.trim()} onClick={submit}>
						{t('Create')}
					</Button>
				</div>
			</div>
		</div>
	);
};
