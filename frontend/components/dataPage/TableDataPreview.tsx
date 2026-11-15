// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useQuery } from '@tanstack/react-query';
import { Spinner } from '@nvidia/foundations-react-core';
import { explorationApi } from '@/api/exploration';
import { Button } from '@/common/Button';
import { t } from '@/i18n';
import { Icon, IconName } from '@/common/icons';
import { Modal } from '@/common/modal';
import { ButtonTheme, Size } from '@/enums/button';
import type { TablePreview } from '@/types/exploration';

const PREVIEW_ROWS = 20;

const formatCell = (value: string | number | boolean | null): string => {
	if (value === null) return '';
	return String(value);
};

export type TableDataPreviewProps = {
	/** The table to sample; `null` keeps the dialog closed. */
	tableId: string | null;
	/** Shown under the dialog title so the operator knows which table they are looking at. */
	tableName?: string;
	onClose: () => void;
};

/**
 * The first rows of a table, read from its live source.
 *
 * Opened from the table's catalog page so an operator can see what the data
 * actually looks like before writing a question about it — the column list
 * alone says nothing about values, grain, or formatting. It is a dialog rather
 * than a permanent panel because the sample is something you consult, not
 * something you read alongside the metadata on every visit.
 */
export const TableDataPreview = ({ tableId, tableName, onClose }: TableDataPreviewProps) => {
	const open = tableId != null;
	const {
		data: preview,
		error,
		isFetching,
		refetch,
	} = useQuery({
		queryKey: ['table-preview', tableId, PREVIEW_ROWS],
		// Only read the source once someone asks to see the rows.
		enabled: open,
		queryFn: async (): Promise<TablePreview> => {
			if (tableId == null) throw new Error('No table is selected.');
			const res = await explorationApi.getTablePreview(tableId, PREVIEW_ROWS);
			if (res.error || !res.data) {
				throw new Error(res.message ?? t('Could not read this table.'));
			}
			return res.data;
		},
		// A source error is usually a permission or connectivity problem that a
		// retry will not fix; the Refresh button is the deliberate retry.
		retry: false,
		staleTime: 30_000,
	});
	const loading = isFetching && preview === undefined;
	const message = error == null ? null : error instanceof Error ? error.message : String(error);

	return (
		<Modal
			open={open}
			onClose={onClose}
			className="w-full max-w-6xl"
			ariaLabel={tableName ? t('Data preview of {0}', { 0: tableName }) : t('Data preview')}
			testId="table-data-preview"
		>
			<header className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<div className="flex min-w-0 items-center gap-2">
					<Icon
						name={IconName.Table}
						className="h-5 w-5 shrink-0 text-body dark:text-zinc-300"
					/>
					<div className="min-w-0">
						<h2 className="truncate text-base font-semibold text-heading dark:text-zinc-100">
							{t('Data preview')}{' '}
						</h2>
						<p className="truncate text-xs text-secondary dark:text-zinc-400">
							{tableName ?? t('Table')}
							{preview != null && (
								<>
									{' · '}
									{preview.row_count.toLocaleString()} {t('rows')}{' '}
									{preview.truncated
										? t(' (first {0} shown)', { 0: PREVIEW_ROWS })
										: ''}
								</>
							)}
						</p>
					</div>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<Button
						theme={ButtonTheme.Outline}
						size={Size.SMALL}
						type="button"
						onClick={() => {
							void refetch();
						}}
						disabled={loading}
					>
						<Icon name={IconName.Refresh} className="mr-1 h-3.5 w-3.5" />
						{t('Refresh')}{' '}
					</Button>
					<Button
						theme={ButtonTheme.IconNeutral}
						size={Size.SMALL}
						iconOnly
						type="button"
						onClick={onClose}
						aria-label={t('Close data preview')}
					>
						<Icon name={IconName.Close} className="h-4 w-4" />
					</Button>
				</div>
			</header>

			{loading ? (
				<div className="flex items-center justify-center gap-2 px-5 py-16 text-sm text-secondary dark:text-zinc-400">
					<Spinner aria-label={t('Reading the table')} className="h-4 w-4" />
					{t('Reading the table…')}{' '}
				</div>
			) : message != null ? (
				<p className="px-5 py-8 text-sm text-red-600 dark:text-red-400">{message}</p>
			) : preview != null && preview.rows.length === 0 ? (
				<p className="px-5 py-8 text-sm text-secondary dark:text-zinc-400">
					{t('The table has no rows.')}{' '}
				</p>
			) : preview != null ? (
				<div className="max-h-[65dvh] overflow-auto">
					<table className="min-w-full border-collapse text-xs">
						<thead className="sticky top-0 z-10 bg-zinc-50 dark:bg-zinc-900">
							<tr>
								<th className="border-b border-r border-zinc-200 px-3 py-2 text-right font-medium text-secondary dark:border-zinc-700 dark:text-zinc-500">
									#
								</th>
								{preview.columns.map((column) => (
									<th
										key={column}
										className="whitespace-nowrap border-b border-r border-zinc-200 px-3 py-2 text-left font-semibold text-heading last:border-r-0 dark:border-zinc-700 dark:text-zinc-200"
									>
										{column}
									</th>
								))}
							</tr>
						</thead>
						<tbody>
							{preview.rows.map((row, rowIndex) => (
								<tr
									key={rowIndex}
									className="odd:bg-white even:bg-zinc-50/60 dark:odd:bg-zinc-950 dark:even:bg-zinc-900/40"
								>
									<td className="border-r border-zinc-100 px-3 py-1.5 text-right text-secondary dark:border-zinc-800 dark:text-zinc-500">
										{rowIndex + 1}
									</td>
									{row.map((value, columnIndex) => (
										<td
											key={columnIndex}
											className="max-w-[320px] truncate whitespace-nowrap border-r border-zinc-100 px-3 py-1.5 last:border-r-0 dark:border-zinc-800"
											title={formatCell(value)}
										>
											{formatCell(value)}
										</td>
									))}
								</tr>
							))}
						</tbody>
					</table>
				</div>
			) : null}
		</Modal>
	);
};
