// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button, SelectButton } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { ButtonTheme, SelectButtonTheme, Size } from '@/enums/button';
import { PopoverAlign } from '@/enums/popover';
import { Popover } from '@/common/Popover';
import { t } from '@/i18n';
import type { Zone } from '@/types/zones';

const ZONE_SELECTION_NAME = 'exploration-zone';

export type ZoneFilterProps = {
	zones: Zone[];
	selected: string | null;
	loading: boolean;
	failed: boolean;
	onChange: (selected: string | null) => void;
};

/** Which one Zone the Exploration graph may draw. */
export const ZoneFilter = ({ zones, selected, loading, failed, onChange }: ZoneFilterProps) => {
	const selectedZone = zones.find((zone) => zone.id === selected);
	const summary = selected === null ? t('All Zones') : (selectedZone?.name ?? t('Filtered'));
	const emptyMessage = failed
		? t('Could not load zones')
		: loading
			? t('Loading zones…')
			: zones.length === 0
				? t('No enabled Zones are configured')
				: null;

	return (
		<Popover
			className="w-40"
			align={PopoverAlign.Right}
			panelClassName="w-72 p-1"
			trigger={({ open, toggle: togglePanel }) => (
				<div className="rounded-lg shadow-md">
					<SelectButton
						theme={SelectButtonTheme.SelectField}
						onClick={togglePanel}
						aria-expanded={open}
						aria-label={t('Filter by Zone')}
					>
						<span className="flex min-w-0 items-center gap-2">
							<Icon
								name={IconName.Filter}
								className="h-4 w-4 shrink-0 text-secondary dark:text-zinc-400"
							/>
							<span className="truncate">{summary}</span>
							{selected !== null && (
								<span
									className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-500"
									aria-hidden
								/>
							)}
						</span>
						<Icon
							name={IconName.ChevronRight}
							className="h-4 w-4 shrink-0 rotate-90 text-secondary dark:text-zinc-400"
						/>
					</SelectButton>
				</div>
			)}
		>
			{({ close }) => (
				<div className="flex flex-col">
					<div className="flex items-center justify-between gap-2 px-2 py-1">
						<span className="text-xs font-medium text-secondary dark:text-zinc-400">
							{t('Filter By')}
						</span>
						<Button
							theme={ButtonTheme.Minimal}
							size={Size.SMALL}
							type="button"
							onClick={() => {
								onChange(null);
								close();
							}}
							disabled={emptyMessage !== null || selected === null}
						>
							{t('Select All')}
						</Button>
					</div>
					{emptyMessage !== null ? (
						<p className="px-2 py-3 text-center text-xs text-secondary dark:text-zinc-400">
							{emptyMessage}
						</p>
					) : (
						<>
							<label className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70">
								<span className="inline-flex w-4 shrink-0" />
								<input
									type="radio"
									name={ZONE_SELECTION_NAME}
									checked={selected === null}
									onChange={() => {
										onChange(null);
										close();
									}}
									className="h-4 w-4 cursor-pointer border-zinc-300 text-[#76b900] focus:ring-[#76b900]/40 dark:border-zinc-600"
								/>
								<Icon
									name={IconName.Filter}
									className="h-4 w-4 shrink-0 text-zinc-500 dark:text-zinc-400"
								/>
								{t('All Zones')}
							</label>
							{zones.map((zone) => (
								<label
									key={zone.id}
									className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70"
								>
									<span className="inline-flex w-4 shrink-0" />
									<input
										type="radio"
										name={ZONE_SELECTION_NAME}
										checked={selected === zone.id}
										onChange={() => {
											onChange(zone.id);
											close();
										}}
										className="h-4 w-4 cursor-pointer border-zinc-300 text-[#76b900] focus:ring-[#76b900]/40 dark:border-zinc-600"
									/>
									<span
										className="h-3 w-3 shrink-0 rounded-full border border-black/10 dark:border-white/20"
										style={{ backgroundColor: zone.color ?? '#a1a1aa' }}
										aria-hidden
									/>
									<span className="min-w-0 truncate">{zone.name || zone.id}</span>
								</label>
							))}
						</>
					)}
				</div>
			)}
		</Popover>
	);
};
