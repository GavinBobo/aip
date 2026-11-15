// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/common/Button';
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
	selectedCount,
	onDuplicate,
	onDeleteSelected,
	hiddenCount,
	onOpenHidden,
	onOpenTransfer,
	onZoomIn,
	onZoomOut,
	onFit,
}: ErdToolbarProps) => (
	<div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950">
		<select
			value={zoneId ?? ''}
			onChange={(event) => onZoneChange(event.target.value)}
			aria-label={t('Zone')}
			className="h-9 max-w-[240px] rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
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
			className="w-64"
		/>

		<div className="ml-auto flex flex-wrap items-center justify-end gap-2">
			<Button
				theme={snapToGrid ? ButtonTheme.Soft : ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onToggleSnap}
				title={t('Snap to grid')}
				aria-pressed={snapToGrid}
			>
				{t('Snap to grid')}
			</Button>
			<Button
				theme={showMinimap ? ButtonTheme.Soft : ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onToggleMinimap}
				title={t('Minimap')}
				aria-pressed={showMinimap}
			>
				{t('Minimap')}
			</Button>
			<Button
				theme={ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onPaste}
				disabled={!canPaste}
				title={t('Paste (Ctrl+V)')}
			>
				{t('Paste')}
			</Button>
			<Button
				theme={ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onCopy}
				disabled={selectedCount === 0}
				title={t('Copy (Ctrl+C)')}
			>
				{t('Copy')}
			</Button>
			{selectedCount > 0 && (
				<div className="flex h-9 items-center gap-1 rounded-lg border border-[#76b900]/50 bg-[#76b900]/5 px-2 text-xs text-[#4d7a00] dark:text-[#a3d63a]">
					<span>{t('{0} selected', { 0: String(selectedCount) })}</span>
					{!readOnly && (
						<>
							<Button
								theme={ButtonTheme.Icon}
								size={Size.SMALL}
								iconOnly
								type="button"
								onClick={onDuplicate}
								aria-label={t('Duplicate')}
								title={t('Duplicate (Ctrl+D)')}
							>
								⧉
							</Button>
							<Button
								theme={ButtonTheme.IconDanger}
								size={Size.SMALL}
								iconOnly
								type="button"
								onClick={onDeleteSelected}
								aria-label={t('Delete selected')}
								title={t('Delete selected')}
							>
								✕
							</Button>
						</>
					)}
				</div>
			)}
			{hiddenCount > 0 && (
				<Button
					theme={ButtonTheme.Secondary}
					size={Size.REGULAR}
					type="button"
					onClick={onOpenHidden}
				>
					{t('Hidden ({0})', { 0: String(hiddenCount) })}
				</Button>
			)}
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
			{!readOnly && (
				<>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={onAddTable}
					>
						{t('Add table')}
					</Button>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={onAddNote}
					>
						{t('Add note')}
					</Button>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={onAddArea}
					>
						{t('Add area')}
					</Button>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={onAutoArrange}
					>
						{t('Auto arrange')}
					</Button>
				</>
			)}
			<Button
				theme={ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onOpenTransfer}
			>
				{t('Import / Export')}
			</Button>
			<Button
				theme={ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onOpenVersions}
			>
				{t('Versions')}
			</Button>
			<Button
				theme={ButtonTheme.Secondary}
				size={Size.REGULAR}
				type="button"
				onClick={onOpenTemplates}
				disabled={readOnly}
			>
				{t('Templates')}
			</Button>

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
