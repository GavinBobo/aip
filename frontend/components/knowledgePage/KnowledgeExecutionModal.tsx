// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { knowledgeApi, type KnowledgeAction, type KnowledgeExecution } from '@/api/knowledge';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

export const KnowledgeExecutionModal = ({
	action,
	onClose,
	onCreated,
}: {
	action: KnowledgeAction;
	onClose: () => void;
	onCreated: (execution: KnowledgeExecution) => void;
}) => {
	const initial = Object.fromEntries(
		action.parameters.map((parameter) => [parameter.name ?? '', '']),
	);
	const [parameters, setParameters] = useState(JSON.stringify(initial, null, 2));
	const [execution, setExecution] = useState<KnowledgeExecution | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [running, setRunning] = useState(false);

	const prepare = async () => {
		let parsed: Record<string, unknown>;
		try {
			parsed = JSON.parse(parameters);
		} catch {
			setError(t('Parameters must be valid JSON.'));
			return;
		}
		setRunning(true);
		setError(null);
		const response = await knowledgeApi.executeAction(action.id, parsed, true);
		setRunning(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to prepare the execution.'));
			return;
		}
		setExecution(response.data);
		onCreated(response.data);
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('Prepare action execution')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('Prepare action execution')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{action.name} · {t('Dry-run only; no external tool is called.')}
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
				<div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
					<label className="text-xs font-medium text-body">
						{t('Parameters (JSON)')}
					</label>
					<textarea
						className="mt-1 min-h-32 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-body outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						value={parameters}
						onChange={(event) => setParameters(event.target.value)}
					/>
					{error && <p className="mt-2 text-sm text-red-600">{error}</p>}
					{execution && (
						<div className="mt-3">
							<div className="text-xs font-medium text-body">
								{t('Execution plan')}
							</div>
							<pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-zinc-950 px-3 py-2 text-[10px] text-zinc-100">
								{JSON.stringify(execution.plan, null, 2)}
							</pre>
						</div>
					)}
				</div>
				<div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
					<Button theme={ButtonTheme.Secondary} onClick={onClose}>
						{t('Close')}
					</Button>
					<Button loading={running} onClick={prepare}>
						{t('Prepare plan')}
					</Button>
				</div>
			</div>
		</div>
	);
};
