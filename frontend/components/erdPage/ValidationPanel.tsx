// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/common/Button';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdIssue } from '@/lib/erd/validation';

type ValidationPanelProps = {
	issues: ErdIssue[];
	readOnly: boolean;
	onClose: () => void;
	onFocus: (issue: ErdIssue) => void;
	onDeleteRelationship: (relationshipId: string) => void;
};

export const ValidationPanel = ({
	issues,
	readOnly,
	onClose,
	onFocus,
	onDeleteRelationship,
}: ValidationPanelProps) => (
	<div className="absolute right-4 top-4 z-20 flex max-h-[70%] w-80 flex-col rounded-xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
		<div className="flex items-center justify-between border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
			<span className="text-xs font-semibold text-heading dark:text-zinc-200">
				{t('Canvas checks')} ({issues.length})
			</span>
			<Button
				theme={ButtonTheme.IconNeutral}
				size={Size.SMALL}
				iconOnly
				onClick={onClose}
				aria-label={t('Close')}
			>
				✕
			</Button>
		</div>
		<div className="min-h-0 flex-1 overflow-y-auto p-2">
			{issues.length === 0 ? (
				<p className="p-3 text-xs text-secondary dark:text-zinc-400">
					{t('No problems found')}
				</p>
			) : (
				<ul className="space-y-2">
					{issues.map((issue) => (
						<li
							key={issue.id}
							className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-700"
						>
							<div className="flex items-start gap-2">
								<span
									className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
										issue.severity === 'error' ? 'bg-red-500' : 'bg-amber-500'
									}`}
									aria-hidden
								/>
								<p className="text-[11px] leading-relaxed text-body dark:text-zinc-300">
									{t(issue.message, issue.params)}
								</p>
							</div>
							{issue.relationshipId && (
								<div className="mt-1 flex gap-1 pl-4">
									<Button
										theme={ButtonTheme.Minimal}
										size={Size.SMALL}
										onClick={() => onFocus(issue)}
									>
										{t('Show')}
									</Button>
									{!readOnly && (
										<Button
											theme={ButtonTheme.IconDanger}
											size={Size.SMALL}
											onClick={() =>
												onDeleteRelationship(issue.relationshipId as string)
											}
										>
											{t('Delete relationship')}
										</Button>
									)}
								</div>
							)}
						</li>
					))}
				</ul>
			)}
		</div>
	</div>
);
