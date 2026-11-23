// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { t } from '@/i18n';
import { Button } from '@/common/Button';
import { ButtonTheme, Size } from '@/enums/button';
import {
	CARD_COLUMN_NOTE_HEIGHT,
	CARD_HEADER_HEIGHT,
	CARD_ROW_HEIGHT,
	columnRowHeight,
	nodeWidth,
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
	onReorderColumns: (nodeId: string, fromIndex: number, toIndex: number) => void;
	onResizeStart: (event: ReactPointerEvent, nodeId: string) => void;
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
	onReorderColumns,
	onResizeStart,
	armedColumn,
	onToggleCollapse,
	onEdit,
	onDelete,
}: TableCardProps) => {
	const columnListRef = useRef<HTMLDivElement | null>(null);
	const columnDrag = useRef<{ nodeId: string; fromIndex: number; count: number } | null>(null);
	const [draggingColumn, setDraggingColumn] = useState<{
		nodeId: string;
		fromIndex: number;
	} | null>(null);
	const [dropIndex, setDropIndex] = useState<number | null>(null);

	useEffect(() => {
		const insertionIndexAt = (clientY: number): number => {
			const list = columnListRef.current;
			if (!list) return columnDrag.current?.fromIndex ?? 0;
			const rows = Array.from(list.querySelectorAll<HTMLElement>('[data-erd-column-row]'));
			for (let index = 0; index < rows.length; index += 1) {
				const rect = rows[index].getBoundingClientRect();
				if (clientY < rect.top + rect.height / 2) return index;
			}
			return rows.length;
		};

		const onPointerMove = (event: PointerEvent) => {
			if (!columnDrag.current) return;
			setDropIndex(insertionIndexAt(event.clientY));
		};

		const onPointerUp = (event: PointerEvent) => {
			const current = columnDrag.current;
			if (!current) return;
			const insertion = insertionIndexAt(event.clientY);
			columnDrag.current = null;
			setDraggingColumn(null);
			setDropIndex(null);
			const target = insertion > current.fromIndex ? insertion - 1 : insertion;
			if (target !== current.fromIndex && target >= 0 && target < current.count) {
				onReorderColumns(current.nodeId, current.fromIndex, target);
			}
		};

		const onPointerCancel = () => {
			columnDrag.current = null;
			setDraggingColumn(null);
			setDropIndex(null);
		};

		window.addEventListener('pointermove', onPointerMove);
		window.addEventListener('pointerup', onPointerUp);
		window.addEventListener('pointercancel', onPointerCancel);
		return () => {
			window.removeEventListener('pointermove', onPointerMove);
			window.removeEventListener('pointerup', onPointerUp);
			window.removeEventListener('pointercancel', onPointerCancel);
		};
	}, [onReorderColumns]);

	const beginColumnDrag = (
		event: ReactPointerEvent<HTMLButtonElement>,
		nodeId: string,
		fromIndex: number,
	) => {
		if (readOnly || event.button !== 0) return;
		event.preventDefault();
		event.stopPropagation();
		columnDrag.current = { nodeId, fromIndex, count: node.columns.length };
		setDraggingColumn({ nodeId, fromIndex });
		setDropIndex(fromIndex);
	};

	let markerTop = 0;
	if (dropIndex != null) {
		for (const column of node.columns.slice(0, dropIndex)) {
			markerTop += columnRowHeight(column);
		}
	}

	return (
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
				width: nodeWidth(node),
				minHeight: CARD_HEADER_HEIGHT,
			}}
		>
			<div
				className={`flex items-center gap-1.5 rounded-t-lg border-b border-zinc-200 bg-zinc-50 px-2 dark:border-zinc-700 dark:bg-zinc-800 ${
					readOnly ? '' : 'cursor-grab active:cursor-grabbing'
				}`}
				style={{ height: CARD_HEADER_HEIGHT }}
				onPointerDown={(event) => {
					if (!readOnly) onHeaderPointerDown(event, node.id);
				}}
				title={node.table_id ? t('Drag to move') : t('Virtual table (not in the catalog)')}
			>
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
				{node.note && (
					<span
						className="shrink-0 text-[11px] text-secondary dark:text-zinc-400"
						title={node.note}
						aria-label={t('Table note')}
					>
						▤
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
								<path
									d="M4 4l8 8M12 4l-8 8"
									strokeWidth="1.6"
									strokeLinecap="round"
								/>
							</svg>
						</Button>
					</span>
				)}
			</div>
			{!node.collapsed && (
				<div ref={columnListRef} className="relative py-0.5">
					{draggingColumn && dropIndex != null && (
						<span
							className="pointer-events-none absolute inset-x-1 z-10 h-0.5 rounded-full bg-[#76b900]"
							style={{ top: markerTop + 1 }}
							aria-hidden
						/>
					)}
					{node.columns.length === 0 && (
						<p className="px-2 py-1 text-[11px] text-secondary dark:text-zinc-400">
							{t('No columns')}
						</p>
					)}
					{node.columns.map((column, index) => (
						<div
							key={column.name}
							data-erd-column={column.name}
							data-erd-node={node.id}
							data-erd-column-row="true"
							className={`group/row relative px-2 text-[11px] text-body hover:bg-[#76b900]/5 dark:text-zinc-300 dark:hover:bg-[#76b900]/10 ${
								draggingColumn?.nodeId === node.id &&
								draggingColumn.fromIndex === index
									? 'opacity-50'
									: ''
							}`}
							style={{ height: columnRowHeight(column) }}
						>
							<div
								className="flex items-center gap-1.5"
								style={{ height: CARD_ROW_HEIGHT }}
							>
								{!readOnly && node.columns.length > 1 && (
									<button
										type="button"
										className="-ml-1 flex h-5 w-4 shrink-0 cursor-grab items-center justify-center rounded text-zinc-400 opacity-30 transition-opacity hover:bg-zinc-200 hover:text-zinc-600 focus:opacity-100 active:cursor-grabbing group-hover/row:opacity-100 dark:text-zinc-500 dark:hover:bg-zinc-700 dark:hover:text-zinc-300"
										onPointerDown={(event) =>
											beginColumnDrag(event, node.id, index)
										}
										onClick={(event) => event.stopPropagation()}
										onKeyDown={(event) => {
											if (
												event.key !== 'ArrowUp' &&
												event.key !== 'ArrowDown'
											) {
												return;
											}
											event.preventDefault();
											event.stopPropagation();
											const target =
												index + (event.key === 'ArrowUp' ? -1 : 1);
											if (target >= 0 && target < node.columns.length) {
												onReorderColumns(node.id, index, target);
											}
										}}
										aria-label={t('Reorder column {0}', { 0: column.name })}
										aria-keyshortcuts="ArrowUp ArrowDown"
										title={t('Drag to reorder column')}
									>
										<svg
											className="h-3 w-2"
											viewBox="0 0 8 12"
											fill="currentColor"
											aria-hidden
										>
											<circle cx="2" cy="2" r="1" />
											<circle cx="6" cy="2" r="1" />
											<circle cx="2" cy="6" r="1" />
											<circle cx="6" cy="6" r="1" />
											<circle cx="2" cy="10" r="1" />
											<circle cx="6" cy="10" r="1" />
										</svg>
									</button>
								)}
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
			{!readOnly && (
				<span
					className="absolute -bottom-1.5 -right-1.5 z-10 flex h-4 w-4 cursor-ew-resize items-center justify-center rounded-sm border border-zinc-400 bg-white text-zinc-500 opacity-30 transition-opacity hover:opacity-100 group-hover:opacity-100 dark:border-zinc-500 dark:bg-zinc-900 dark:text-zinc-300"
					onPointerDown={(event) => {
						event.stopPropagation();
						onResizeStart(event, node.id);
					}}
					role="button"
					aria-label={t('Resize table width')}
					title={t('Drag to resize table width')}
				>
					<svg className="h-2.5 w-2.5" viewBox="0 0 10 10" aria-hidden>
						<path
							d="M1 5h8M2.5 3 1 5l1.5 2M7.5 3 9 5 7.5 7"
							fill="none"
							stroke="currentColor"
							strokeWidth="1.2"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
				</span>
			)}
		</div>
	);
};
