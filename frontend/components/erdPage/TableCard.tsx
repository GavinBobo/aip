// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import type { PointerEvent as ReactPointerEvent } from 'react';

import { t } from '@/i18n';
import { Button } from '@/common/Button';
import { ButtonTheme, Size } from '@/enums/button';
import {
	CARD_COLUMN_NOTE_HEIGHT,
	CARD_HEADER_HEIGHT,
	CARD_ROW_HEIGHT,
	CARD_WIDTH,
	cardHeaderHeight,
	columnRowHeight,
} from '@/lib/erd/geometry';
import type { ErdNode } from '@/types/erd';

type TableCardProps = {
	node: ErdNode;
	dimmed: boolean;
	selected: boolean;
	readOnly: boolean;
	onHeaderPointerDown: (event: ReactPointerEvent, nodeId: string) => void;
	onColumnPointerDown: (event: ReactPointerEvent, nodeId: string, column: string) => void;
	onColumnClick: (nodeId: string, column: string) => void;
	armedColumn: string | null;
	onToggleCollapse: (nodeId: string) => void;
	onEdit: (nodeId: string) => void;
	onDelete: (nodeId: string) => void;
};

const CollapseIcon = ({ collapsed }: { collapsed: boolean }) => (
	<svg
		className={`h-3.5 w-3.5 transition-transform ${collapsed ? '' : 'rotate-90'}`}
		viewBox="0 0 16 16"
		fill="none"
		stroke="currentColor"
		aria-hidden
	>
		<path d="M6 3.5 10.5 8 6 12.5" strokeWidth="1.6" strokeLinecap="round" />
	</svg>
);

export const TableCard = ({
	node,
	dimmed,
	selected,
	readOnly,
	onHeaderPointerDown,
	onColumnPointerDown,
	onColumnClick,
	armedColumn,
	onToggleCollapse,
	onEdit,
	onDelete,
}: TableCardProps) => (
	<div
		data-erd-node={node.id}
		className={`group absolute rounded-lg border bg-white shadow-sm transition-opacity dark:bg-zinc-900 ${
			selected ? 'ring-2 ring-[#76b900]/60' : ''
		} ${
			dimmed
				? 'border-zinc-200 opacity-30 dark:border-zinc-700'
				: 'border-zinc-300 dark:border-zinc-600'
		}`}
		style={{
			left: node.x,
			top: node.y,
			width: CARD_WIDTH,
			minHeight: cardHeaderHeight(node),
		}}
	>
		<div
			className={`flex flex-col rounded-t-lg border-b border-zinc-200 bg-zinc-50 px-2 dark:border-zinc-700 dark:bg-zinc-800 ${
				readOnly ? '' : 'cursor-grab active:cursor-grabbing'
			}`}
			style={{ height: cardHeaderHeight(node) }}
			onPointerDown={(event) => {
				if (!readOnly) onHeaderPointerDown(event, node.id);
			}}
			title={node.table_id ? t('Drag to move') : t('Virtual table (not in the catalog)')}
		>
			<div className="flex items-center gap-1.5" style={{ height: CARD_HEADER_HEIGHT }}>
				<button
					type="button"
					className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-secondary hover:bg-zinc-200 dark:hover:bg-zinc-700"
					onPointerDown={(event) => event.stopPropagation()}
					onClick={() => onToggleCollapse(node.id)}
					aria-label={node.collapsed ? t('Expand table') : t('Collapse table')}
				>
					<CollapseIcon collapsed={node.collapsed} />
				</button>
				<span
					className="min-w-0 flex-1 truncate text-[13px] font-semibold text-heading dark:text-zinc-100"
					title={node.name}
				>
					{node.name}
				</span>
				{node.table_id == null && (
					<span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
						{t('virtual')}
					</span>
				)}
				{node.indexes.length > 0 && (
					<span
						className="shrink-0 rounded bg-zinc-100 px-1 text-[10px] text-secondary dark:bg-zinc-800 dark:text-zinc-400"
						title={t('{0} index(es)', { 0: String(node.indexes.length) })}
					>
						⚏{node.indexes.length}
					</span>
				)}
				{!readOnly && (
					<span className="opacity-0 transition-opacity group-hover:opacity-100">
					<Button
						theme={ButtonTheme.IconNeutral}
						size={Size.SMALL}
						iconOnly
						type="button"
						onPointerDown={(event) => event.stopPropagation()}
						onClick={() => onEdit(node.id)}
						aria-label={t('Edit {0}', { 0: node.name })}
						title={t('Edit table')}
					>
						<svg
							className="h-3.5 w-3.5"
							viewBox="0 0 16 16"
							fill="none"
							stroke="currentColor"
						>
							<path
								d="M11.3 2.2a1.4 1.4 0 0 1 2 2L5 12.5l-2.7.7.7-2.7 8.3-8.3Z"
								strokeWidth="1.4"
								strokeLinejoin="round"
							/>
						</svg>
					</Button>
					<Button
						theme={ButtonTheme.IconDanger}
						size={Size.SMALL}
						iconOnly
						type="button"
						onPointerDown={(event) => event.stopPropagation()}
						onClick={() => onDelete(node.id)}
						aria-label={t('Remove {0} from the canvas', { 0: node.name })}
						title={t('Remove from canvas')}
					>
						<svg
							className="h-3.5 w-3.5"
							viewBox="0 0 16 16"
							fill="none"
							stroke="currentColor"
						>
							<path d="M4 4l8 8M12 4l-8 8" strokeWidth="1.6" strokeLinecap="round" />
						</svg>
					</Button>
					</span>
				)}
			</div>
			{!node.collapsed && node.note && (
				<p
					className="truncate pl-[26px] pr-1 text-[10px] leading-none text-zinc-400 dark:text-zinc-500"
					title={node.note}
				>
					{node.note}
				</p>
			)}
		</div>
		{!node.collapsed && (
			<div className="py-0.5">
				{node.columns.length === 0 && (
					<p className="px-2 py-1 text-[11px] text-secondary dark:text-zinc-400">
						{t('No columns')}
					</p>
				)}
				{node.columns.map((column) => (
					<div
						key={column.name}
						data-erd-column={column.name}
						data-erd-node={node.id}
						className="group/row relative px-2 text-[11px] text-body hover:bg-[#76b900]/5 dark:text-zinc-300 dark:hover:bg-[#76b900]/10"
						style={{ height: columnRowHeight(column) }}
					>
						<div
							className="flex items-center gap-1.5"
							style={{ height: CARD_ROW_HEIGHT }}
						>
							{column.is_primary_key && (
								<span
									className="shrink-0 text-[10px] text-amber-500"
									title={t('Primary key')}
									aria-label={t('Primary key')}
								>
									◆
								</span>
							)}
							<span className="min-w-0 flex-1 truncate" title={column.name}>
								{column.name}
							</span>
							<span className="max-w-[45%] shrink-0 truncate text-[10px] text-secondary dark:text-zinc-400">
								{column.data_type ?? ''}
							</span>
						</div>
						{column.note && (
							<p
								className={`truncate text-[10px] leading-none text-zinc-400 dark:text-zinc-500 ${
									column.is_primary_key ? 'pl-[16px]' : ''
								}`}
								style={{ height: CARD_COLUMN_NOTE_HEIGHT }}
								title={column.note}
							>
								{column.note}
							</p>
						)}
						{!readOnly && (
							<>
								<span
									className={`absolute -left-[5px] h-2.5 w-2.5 -translate-y-1/2 cursor-crosshair rounded-full border bg-white dark:bg-zinc-900 ${
										armedColumn === column.name
											? 'border-[#76b900] opacity-100 ring-2 ring-[#76b900]/40'
											: 'border-zinc-400 opacity-0 group-hover/row:opacity-100 dark:border-zinc-500'
									}`}
									style={{ top: CARD_ROW_HEIGHT / 2 }}
									onPointerDown={(event) =>
										onColumnPointerDown(event, node.id, column.name)
									}
									onClick={() => onColumnClick(node.id, column.name)}
									role="button"
									aria-label={t('Connect from {0}.{1}', {
										0: node.name,
										1: column.name,
									})}
								/>
								<span
									className={`absolute -right-[5px] h-2.5 w-2.5 -translate-y-1/2 cursor-crosshair rounded-full border bg-white dark:bg-zinc-900 ${
										armedColumn === column.name
											? 'border-[#76b900] opacity-100 ring-2 ring-[#76b900]/40'
											: 'border-zinc-400 opacity-0 group-hover/row:opacity-100 dark:border-zinc-500'
									}`}
									style={{ top: CARD_ROW_HEIGHT / 2 }}
									onPointerDown={(event) =>
										onColumnPointerDown(event, node.id, column.name)
									}
									onClick={() => onColumnClick(node.id, column.name)}
									role="button"
									aria-label={t('Connect from {0}.{1}', {
										0: node.name,
										1: column.name,
									})}
								/>
							</>
						)}
					</div>
				))}
			</div>
		)}
	</div>
);
