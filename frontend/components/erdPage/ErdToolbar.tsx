// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import type { MouseEvent as ReactMouseEvent } from 'react';

import { Button } from '@/common/Button';
import { PopoverMenu, type PopoverMenuItem } from '@/common/PopoverMenu';
import { SearchInput } from '@/common/SearchInput';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { Zone } from '@/types/zones';

type ErdToolbarProps = {
	zones: Zone[];
	zoneId: string | null;
	onZoneChange: (zoneId: string) => void;
	search: string;
	onSearchChange: (value: string) => void;
	readOnly: boolean;
	zoom: number;
	onAddTable: () => void;
	onAddNote: () => void;
	onAddArea: () => void;
	onAutoArrange: () => void;
	onUndo: () => void;
	onRedo: () => void;
	canUndo: boolean;
	canRedo: boolean;
	issueCount: number;
	errorCount: number;
	snapToGrid: boolean;
	onToggleSnap: () => void;
	showMinimap: boolean;
	onToggleMinimap: () => void;
	canPaste: boolean;
	onPaste: () => void;
	onCopy: () => void;
	onOpenVersions: () => void;
	onOpenTemplates: () => void;
	onOpenIssues: () => void;
	onOpenOntology: () => void;
	selectedCount: number;
	onDuplicate: () => void;
	onDeleteSelected: () => void;
	hiddenCount: number;
	onOpenHidden: () => void;
	onOpenTransfer: () => void;
	onZoomIn: () => void;
	onZoomOut: () => void;
	onFit: () => void;
};

const MenuChevron = ({ open }: { open: boolean }) => (
	<svg
		className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
		viewBox="0 0 16 16"
		fill="none"
		stroke="currentColor"
		aria-hidden
	>
		<path d="m4 6 4 4 4-4" strokeWidth="1.5" strokeLinecap="round" />
	</svg>
);

const MenuTrigger = ({
	label,
	open,
	toggle,
}: {
	label: string;
	open: boolean;
	toggle: (event: ReactMouseEvent) => void;
}) => (
	<Button
		theme={ButtonTheme.Secondary}
		size={Size.REGULAR}
		type="button"
		onClick={toggle}
		aria-haspopup="menu"
		aria-expanded={open}
		iconPosition="right"
	>
		{label}
		<MenuChevron open={open} />
	</Button>
);

export const ErdToolbar = ({
	zones,
	zoneId,
	onZoneChange,
	search,
	onSearchChange,
	readOnly,
	zoom,
	onAddTable,
	onAddNote,
	onAddArea,
	onAutoArrange,
	onUndo,
	onRedo,
	canUndo,
	canRedo,
	issueCount,
	errorCount,
	snapToGrid,
	onToggleSnap,
	showMinimap,
	onToggleMinimap,
	canPaste,
	onPaste,
	onCopy,
	onOpenVersions,
	onOpenTemplates,
	onOpenIssues,
	onOpenOntology,
	selectedCount,
	onDuplicate,
	onDeleteSelected,
	hiddenCount,
	onOpenHidden,
	onOpenTransfer,
	onZoomIn,
	onZoomOut,
	onFit,
}: ErdToolbarProps) => {
	const addItems: PopoverMenuItem[] = [
		{ label: t('Add table'), onClick: onAddTable, disabled: readOnly },
		{ label: t('Add note'), onClick: onAddNote, disabled: readOnly },
		{ label: t('Add area'), onClick: onAddArea, disabled: readOnly },
		{ label: t('Templates'), onClick: onOpenTemplates, disabled: readOnly },
	];
	const editItems: PopoverMenuItem[] = [
		{
			label: t('Copy (Ctrl+C)'),
			onClick: onCopy,
			disabled: selectedCount === 0,
		},
		{
			label: t('Paste (Ctrl+V)'),
			onClick: onPaste,
			disabled: readOnly || !canPaste,
		},
		{
			label: t('Duplicate (Ctrl+D)'),
			onClick: onDuplicate,
			disabled: readOnly || selectedCount === 0,
		},
		{
			label: t('Delete selected'),
			onClick: onDeleteSelected,
			disabled: readOnly || selectedCount === 0,
			danger: true,
		},
	];
	const viewItems: PopoverMenuItem[] = [
		{ label: t('Snap to grid'), onClick: onToggleSnap, selected: snapToGrid },
		{ label: t('Minimap'), onClick: onToggleMinimap, selected: showMinimap },
		{ label: t('Auto arrange'), onClick: onAutoArrange, disabled: readOnly },
	];
	const fileItems: PopoverMenuItem[] = [
		{ label: t('Import / Export'), onClick: onOpenTransfer },
		{ label: t('Versions'), onClick: onOpenVersions },
		...(hiddenCount > 0
			? [
					{
						label: t('Hidden ({0})', { 0: String(hiddenCount) }),
						onClick: onOpenHidden,
					},
				]
			: []),
	];

	return (
		<div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-950">
			<select
				value={zoneId ?? ''}
				onChange={(event) => onZoneChange(event.target.value)}
				aria-label={t('Zone')}
				className="h-9 w-40 shrink-0 rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
			>
				{zones.map((zone) => (
					<option key={zone.id} value={zone.id}>
						{zone.name}
					</option>
				))}
			</select>

			<SearchInput
				value={search}
				onChange={onSearchChange}
				placeholder={t('Search tables and columns')}
				className="max-w-md min-w-[220px] flex-1"
			/>

			<div className="ml-auto flex flex-wrap items-center justify-end gap-2">
				{!readOnly && (
					<PopoverMenu
						items={addItems}
						trigger={({ open, toggle }) => (
							<MenuTrigger label={t('Add')} open={open} toggle={toggle} />
						)}
					/>
				)}
				<PopoverMenu
					items={editItems}
					trigger={({ open, toggle }) => (
						<MenuTrigger label={t('Edit')} open={open} toggle={toggle} />
					)}
				/>
				<PopoverMenu
					items={viewItems}
					trigger={({ open, toggle }) => (
						<MenuTrigger label={t('View')} open={open} toggle={toggle} />
					)}
				/>
				<PopoverMenu
					items={fileItems}
					trigger={({ open, toggle }) => (
						<MenuTrigger label={t('File')} open={open} toggle={toggle} />
					)}
				/>

				{selectedCount > 0 && (
					<div className="flex h-9 items-center rounded-lg border border-[#76b900]/50 bg-[#76b900]/5 px-2 text-xs text-[#4d7a00] dark:text-[#a3d63a]">
						{t('{0} selected', { 0: String(selectedCount) })}
					</div>
				)}

				<span className="mx-0.5 h-6 w-px bg-zinc-200 dark:bg-zinc-700" aria-hidden />

				<Button
					theme={ButtonTheme.Secondary}
					size={Size.REGULAR}
					type="button"
					onClick={onOpenOntology}
					disabled={!zoneId}
					title={t('Build data ontology candidates from this ERD')}
				>
					{t('Data ontology')}
				</Button>

				<Button
					theme={ButtonTheme.Secondary}
					size={Size.REGULAR}
					type="button"
					onClick={onOpenIssues}
					title={t('Canvas checks')}
				>
					{t('Checks')}
					{issueCount > 0 && (
						<span
							className={`rounded-full px-1.5 text-[10px] font-semibold text-white ${
								errorCount > 0 ? 'bg-red-500' : 'bg-amber-500'
							}`}
						>
							{issueCount}
						</span>
					)}
				</Button>

				<div className="flex h-9 items-center rounded-lg border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
					<Button
						theme={ButtonTheme.Icon}
						size={Size.REGULAR}
						iconOnly
						type="button"
						onClick={onUndo}
						disabled={!canUndo}
						aria-label={t('Undo')}
						title={t('Undo (Ctrl+Z)')}
					>
						↶
					</Button>
					<Button
						theme={ButtonTheme.Icon}
						size={Size.REGULAR}
						iconOnly
						type="button"
						onClick={onRedo}
						disabled={!canRedo}
						aria-label={t('Redo')}
						title={t('Redo (Ctrl+Shift+Z)')}
					>
						↷
					</Button>
				</div>

				<div className="flex h-9 items-center rounded-lg border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
					<Button
						theme={ButtonTheme.Icon}
						size={Size.REGULAR}
						iconOnly
						type="button"
						onClick={onZoomOut}
						aria-label={t('Zoom out')}
					>
						−
					</Button>
					<span className="w-11 text-center text-xs text-body dark:text-zinc-300">
						{Math.round(zoom * 100)}%
					</span>
					<Button
						theme={ButtonTheme.Icon}
						size={Size.REGULAR}
						iconOnly
						type="button"
						onClick={onZoomIn}
						aria-label={t('Zoom in')}
					>
						+
					</Button>
				</div>
				<Button
					theme={ButtonTheme.Secondary}
					size={Size.REGULAR}
					type="button"
					onClick={onFit}
					title={t('Fit to view')}
				>
					{t('Fit')}
				</Button>
			</div>
		</div>
	);
};
