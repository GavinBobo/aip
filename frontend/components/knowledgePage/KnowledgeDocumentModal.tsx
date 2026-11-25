// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useState } from 'react';

import { knowledgeApi, type KnowledgeDocument } from '@/api/knowledge';
import { parsingApi, type ParsingRunSummary } from '@/api/parsing';
import { Button } from '@/common/Button';
import { formatDateTime } from '@/common/date';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

export const KnowledgeDocumentModal = ({
	networkId,
	onClose,
	onAdded,
}: {
	networkId: string;
	onClose: () => void;
	onAdded: (document: KnowledgeDocument) => void;
}) => {
	const [query, setQuery] = useState('');
	const [runs, setRuns] = useState<ParsingRunSummary[]>([]);
	const [loading, setLoading] = useState(true);
	const [adding, setAdding] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	const load = useCallback((q: string) => {
		setLoading(true);
		parsingApi
			.runs({ status: 'succeeded', limit: 50, q: q.trim() || undefined })
			.then((response) => {
				setLoading(false);
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to load parsing results.'));
					return;
				}
				setError(null);
				setRuns(response.data);
			});
	}, []);

	useEffect(() => {
		let cancelled = false;
		parsingApi.runs({ status: 'succeeded', limit: 50 }).then((response) => {
			if (cancelled) return;
			setLoading(false);
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to load parsing results.'));
				return;
			}
			setError(null);
			setRuns(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	const add = async (runId: string) => {
		if (adding) return;
		setAdding(runId);
		setError(null);
		const response = await knowledgeApi.addDocument(networkId, runId);
		setAdding(null);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to add the document.'));
			return;
		}
		onAdded(response.data);
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('Add a parsed document')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="flex max-h-[82vh] w-full max-w-2xl flex-col rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('Add a parsed document')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{t(
								'Only successful OXR parsing results can be added. The extractor reads the stored Markdown and page blocks.',
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

				<div className="flex gap-2 px-6 py-4">
					<input
						className={inputClassName}
						value={query}
						onChange={(event) => setQuery(event.target.value)}
						onKeyDown={(event) => {
							if (event.key === 'Enter') load(query);
						}}
						placeholder={t('Search parsed file names')}
					/>
					<Button theme={ButtonTheme.Secondary} onClick={() => load(query)}>
						{t('Search')}
					</Button>
				</div>

				<div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
					{loading ? (
						<div className="flex h-40 items-center justify-center">
							<Spinner />
						</div>
					) : error ? (
						<div className="mx-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
							{error}
						</div>
					) : runs.length === 0 ? (
						<p className="px-3 py-10 text-center text-sm text-secondary">
							{t('No successful parsing results match this search.')}
						</p>
					) : (
						<div className="space-y-1">
							{runs.map((run) => (
								<button
									key={run.id}
									type="button"
									disabled={adding != null}
									onClick={() => add(run.id)}
									className="flex w-full items-center justify-between gap-4 rounded-lg px-3 py-3 text-left transition-colors hover:bg-zinc-100 disabled:opacity-60 dark:hover:bg-zinc-800"
								>
									<div className="min-w-0">
										<div className="truncate text-sm font-medium text-heading dark:text-zinc-100">
											{run.file_name || run.source_name || run.id}
										</div>
										<div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-secondary">
											<span>
												{run.page_count != null
													? t('{count} pages', { count: run.page_count })
													: t('Page count unknown')}
											</span>
											{run.finished && (
												<span>{formatDateTime(run.finished)}</span>
											)}
											{run.reviewed && <span>{t('Reviewed')}</span>}
										</div>
									</div>
									{adding === run.id ? (
										<Spinner />
									) : (
										<Icon
											name={IconName.Plus}
											className="h-4 w-4 shrink-0 text-[#76b900]"
										/>
									)}
								</button>
							))}
						</div>
					)}
				</div>
			</div>
		</div>
	);
};
