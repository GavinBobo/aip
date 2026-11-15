// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { PairModeAnalysis } from '@/types/exploration';
import type { Zone } from '@/types/zones';

export type PairModePanelProps = {
	zones: Zone[];
	zoneId: string;
	onZoneChange: (zoneId: string) => void;
	onAnalyze: () => void;
	onClose: () => void;
	onFocusTable: (tableId: string) => void;
	analysis: PairModeAnalysis | null;
	loading: boolean;
	error: string | null;
};

export const PairModePanel = ({
	zones,
	zoneId,
	onZoneChange,
	onAnalyze,
	onClose,
	onFocusTable,
	analysis,
	loading,
	error,
}: PairModePanelProps) => {
	const nodeNames = new Map<string, string>();
	for (const node of analysis?.graph.nodes ?? []) {
		nodeNames.set(node.id, node.name ?? node.id);
	}
	const confirmedLinks =
		analysis?.graph.links.filter((link) => !link.relationship_types.includes('CANDIDATE')) ??
		[];

	return (
		<aside
			className="pointer-events-auto absolute top-4 right-4 bottom-4 z-30 flex w-[400px] max-w-[calc(100%-2rem)] flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-950"
			aria-label={t('Pair Mode')}
		>
			<header className="flex items-start justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
				<div className="flex min-w-0 items-start gap-2">
					<span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#76b900]/10 text-[#5f9400] dark:text-[#9bd22a]">
						<Icon name={IconName.Connection} className="h-4 w-4" />
					</span>
					<div className="min-w-0">
						<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
							{t('Pair Mode')}
						</h2>
						<p className="mt-0.5 text-xs leading-relaxed text-secondary dark:text-zinc-400">
							{t(
								'Choose a Zone. The agent analyzes only that Zone and proposes table relationships for you to inspect.',
							)}
						</p>
					</div>
				</div>
				<button
					type="button"
					onClick={onClose}
					aria-label={t('Close')}
					className="rounded p-1 text-secondary hover:bg-zinc-100 hover:text-heading dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
				>
					<Icon name={IconName.Close} className="h-4 w-4" />
				</button>
			</header>

			<div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
				<label className="flex flex-col gap-1.5">
					<span className="text-xs font-medium text-heading dark:text-zinc-200">
						{t('Zone')}
					</span>
					<select
						value={zoneId}
						onChange={(event) => onZoneChange(event.target.value)}
						disabled={loading}
						className="h-9 rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300"
					>
						<option value="">{t('Select a Zone')}</option>
						{zones.map((zone) => (
							<option key={zone.id} value={zone.id}>
								{zone.name || zone.id}
							</option>
						))}
					</select>
				</label>

				<Button
					theme={ButtonTheme.Primary}
					size={Size.REGULAR}
					type="button"
					onClick={onAnalyze}
					disabled={zoneId === '' || loading}
					iconPosition="left"
				>
					<Icon name={IconName.Lightning} className="h-4 w-4" />
					{loading ? t('Analyzing…') : t('Analyze Zone')}
				</Button>

				{error != null && (
					<p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
						{error}
					</p>
				)}

				{analysis != null && (
					<div className="flex flex-col gap-3">
						<div className="rounded-lg border border-zinc-200 bg-zinc-50/70 p-3 dark:border-zinc-700 dark:bg-zinc-900/60">
							<p className="text-xs font-medium text-heading dark:text-zinc-200">
								{analysis.zone.name ?? analysis.zone.id}
							</p>
							<div className="mt-2 grid grid-cols-3 gap-2 text-center">
								{[
									[t('Tables'), analysis.summary.table_count],
									[t('Relationships'), analysis.summary.relationship_count],
									[t('Isolated'), analysis.summary.isolated_table_count],
								].map(([label, value]) => (
									<div
										key={label}
										className="rounded-md border border-zinc-200 bg-white px-2 py-2 dark:border-zinc-700 dark:bg-zinc-950"
									>
										<div className="text-base font-semibold tabular-nums text-heading dark:text-zinc-100">
											{value}
										</div>
										<div className="text-[10px] uppercase tracking-wide text-secondary dark:text-zinc-500">
											{label}
										</div>
									</div>
								))}
							</div>
							<div className="mt-2 flex flex-wrap gap-1.5">
								{Object.entries(analysis.summary.relationship_counts).map(
									([kind, count]) => (
										<span
											key={kind}
											className="rounded-full border border-[#76b900]/30 bg-[#76b900]/10 px-2 py-0.5 text-[10px] font-medium text-[#4f7c00] dark:text-[#9bd22a]"
										>
											{kind} · {count}
										</span>
									),
								)}
							</div>
							<p className="mt-2 text-[11px] text-secondary dark:text-zinc-400">
								{t('Confirmed')}: {analysis.summary.confirmed_relationship_count} ·{' '}
								{t('Suggested')}: {analysis.summary.suggested_relationship_count}
							</p>
						</div>

						{analysis.suggestions.length > 0 && (
							<div className="flex flex-col gap-1.5">
								<h3 className="text-xs font-semibold uppercase tracking-wide text-secondary dark:text-zinc-400">
									{t('Suggested Relationships')}
								</h3>
								<ul className="flex flex-col gap-1.5">
									{analysis.suggestions.map((suggestion) => (
										<li
											key={`${suggestion.source}:${suggestion.target}`}
											className="rounded-lg border border-[#76b900]/25 bg-[#76b900]/5 px-3 py-2"
										>
											<div className="flex items-center gap-1 text-xs font-medium text-heading dark:text-zinc-200">
												<button
													type="button"
													onClick={() => onFocusTable(suggestion.source)}
													className="min-w-0 truncate text-left hover:text-[#5f9400] dark:hover:text-[#9bd22a]"
												>
													{nodeNames.get(suggestion.source) ??
														suggestion.source}
												</button>
												<Icon
													name={IconName.Connection}
													className="h-3 w-3 shrink-0 text-secondary dark:text-zinc-500"
												/>
												<button
													type="button"
													onClick={() => onFocusTable(suggestion.target)}
													className="min-w-0 truncate text-left hover:text-[#5f9400] dark:hover:text-[#9bd22a]"
												>
													{nodeNames.get(suggestion.target) ??
														suggestion.target}
												</button>
											</div>
											<div className="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-secondary dark:text-zinc-400">
												<span className="font-mono">
													{suggestion.source_column}
												</span>
												<Icon
													name={IconName.Connection}
													className="h-2.5 w-2.5"
												/>
												<span className="font-mono">
													{suggestion.target_column}
												</span>
												<span className="rounded bg-white/70 px-1.5 py-0.5 dark:bg-zinc-900/70">
													{suggestion.match === 'exact'
														? t('Same column name')
														: t('Related column names')}
												</span>
												<span className="rounded bg-white/70 px-1.5 py-0.5 tabular-nums dark:bg-zinc-900/70">
													{Math.round(suggestion.confidence * 100)}%
												</span>
											</div>
										</li>
									))}
								</ul>
							</div>
						)}

						<div className="flex flex-col gap-1.5">
							<h3 className="text-xs font-semibold uppercase tracking-wide text-secondary dark:text-zinc-400">
								{t('Confirmed Relationships')}
							</h3>
							{confirmedLinks.length === 0 ? (
								<p className="text-xs text-secondary dark:text-zinc-400">
									{analysis.suggestions.length > 0
										? t(
												'No confirmed relationships yet. Review the agent suggestions above.',
											)
										: t(
												'No relationships were found among the tables in this Zone.',
											)}
								</p>
							) : (
								<ul className="flex flex-col gap-1.5">
									{confirmedLinks.map((link) => (
										<li
											key={`${link.source}:${link.target}`}
											className="rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-700"
										>
											<div className="flex items-center gap-1 text-xs font-medium text-heading dark:text-zinc-200">
												<button
													type="button"
													onClick={() => onFocusTable(link.source)}
													className="min-w-0 truncate text-left hover:text-[#5f9400] dark:hover:text-[#9bd22a]"
												>
													{nodeNames.get(link.source) ?? link.source}
												</button>
												<Icon
													name={IconName.Connection}
													className="h-3 w-3 shrink-0 text-secondary dark:text-zinc-500"
												/>
												<button
													type="button"
													onClick={() => onFocusTable(link.target)}
													className="min-w-0 truncate text-left hover:text-[#5f9400] dark:hover:text-[#9bd22a]"
												>
													{nodeNames.get(link.target) ?? link.target}
												</button>
											</div>
											<div className="mt-1 flex flex-wrap gap-1">
												{link.relationship_types.map((kind) => (
													<span
														key={kind}
														className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-secondary dark:bg-zinc-800 dark:text-zinc-400"
													>
														{kind}
													</span>
												))}
											</div>
										</li>
									))}
								</ul>
							)}
						</div>

						{analysis.isolated_tables.length > 0 && (
							<div className="flex flex-col gap-1.5">
								<h3 className="text-xs font-semibold uppercase tracking-wide text-secondary dark:text-zinc-400">
									{t('Isolated Tables')}
								</h3>
								<ul className="flex flex-wrap gap-1.5">
									{analysis.isolated_tables.map((table) => (
										<li key={table.id}>
											<button
												type="button"
												onClick={() => onFocusTable(table.id)}
												className="rounded-full border border-zinc-200 px-2 py-1 text-[11px] text-heading hover:border-[#76b900]/40 hover:bg-[#76b900]/5 dark:border-zinc-700 dark:text-zinc-300"
											>
												{table.name ?? table.id}
											</button>
										</li>
									))}
								</ul>
							</div>
						)}
					</div>
				)}
			</div>
		</aside>
	);
};
