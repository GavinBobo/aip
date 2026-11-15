// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import { TABLE_TEMPLATES, type TableTemplate } from '@/lib/erd/templates';

type TemplatesDialogProps = {
	open: boolean;
	busy: boolean;
	readOnly: boolean;
	onClose: () => void;
	onInsert: (template: TableTemplate) => void;
};

export const TemplatesDialog = ({
	open,
	busy,
	readOnly,
	onClose,
	onInsert,
}: TemplatesDialogProps) => (
	<Modal open={open} onClose={onClose} className="w-full max-w-2xl">
		<header className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
			<div>
				<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
					{t('Table templates')}
				</h2>
				<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
					{t('Templates are drawn as canvas-only tables; the catalog is not changed.')}
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
		<ul className="divide-y divide-zinc-200 dark:divide-zinc-700">
			{TABLE_TEMPLATES.map((template) => (
				<li key={template.id} className="flex items-start gap-3 px-5 py-4">
					<div className="min-w-0 flex-1">
						<p className="text-sm font-medium text-body dark:text-zinc-200">
							{t(template.name)}
						</p>
						<p className="mt-0.5 text-xs text-secondary dark:text-zinc-400">
							{t(template.description)}
						</p>
						<p className="mt-1 text-[11px] text-secondary dark:text-zinc-500">
							{t('{0} tables / {1} relationships', {
								0: String(template.tables.length),
								1: String(template.relationships.length),
							})}
						</p>
					</div>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.SMALL}
						loading={busy}
						disabled={readOnly}
						onClick={() => onInsert(template)}
					>
						{t('Insert')}
					</Button>
				</li>
			))}
		</ul>
	</Modal>
);
