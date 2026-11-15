// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import type { PointerEvent as ReactPointerEvent } from 'react';

import { t } from '@/i18n';
import type { ErdArea } from '@/types/erd';

type AreaCardProps = {
	area: ErdArea;
	readOnly: boolean;
	onDragStart: (event: ReactPointerEvent, areaId: string) => void;
	onResizeStart: (event: ReactPointerEvent, areaId: string) => void;
	onRename: (areaId: string, name: string) => void;
	onDelete: (areaId: string) => void;
};

export const AreaCard = ({
	area,
	readOnly,
	onDragStart,
	onResizeStart,
	onRename,
	onDelete,
}: AreaCardProps) => (
	<div
		data-erd-area={area.id}
		className="absolute rounded-xl border"
		onPointerDown={(event) => {
			event.stopPropagation();
			// The body is a drag surface too: a table card painted above the
			// header would otherwise make the region impossible to grab.
			if (!readOnly) onDragStart(event, area.id);
		}}
		style={{
			left: area.x,
			top: area.y,
			width: area.width,
			height: area.height,
			backgroundColor: area.color ?? '#eff6ff',
			borderColor: 'rgba(37, 99, 235, 0.35)',
		}}
	>
		<div
			className={`flex h-8 items-center gap-1.5 rounded-t-xl px-2 ${
				readOnly ? '' : 'cursor-grab active:cursor-grabbing'
			}`}
			onPointerDown={(event) => {
				if (!readOnly) onDragStart(event, area.id);
			}}
		>
			{!readOnly && (
				<span
					className="shrink-0 cursor-grab px-0.5 text-[10px] leading-none text-blue-700/60 active:cursor-grabbing"
					onPointerDown={(event) => {
						event.stopPropagation();
						onDragStart(event, area.id);
					}}
					role="button"
					aria-label={t('Move area')}
				>
					⠿
				</span>
			)}
			<span className="h-2 w-2 shrink-0 rounded-full bg-blue-500" aria-hidden />
			<input
				value={area.name}
				readOnly={readOnly}
				onPointerDown={(event) => event.stopPropagation()}
				onChange={(event) => onRename(area.id, event.target.value)}
				placeholder={t('Area name')}
				className="min-w-0 flex-1 bg-transparent text-xs font-medium text-blue-900 outline-none placeholder:text-blue-900/40"
			/>
			{!readOnly && (
				<button
					type="button"
					className="rounded px-1 text-blue-900/60 hover:bg-blue-900/10"
					onPointerDown={(event) => event.stopPropagation()}
					onClick={() => onDelete(area.id)}
					aria-label={t('Delete area')}
				>
					✕
				</button>
			)}
		</div>
		{!readOnly && (
			<span
				className="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-blue-400 bg-white"
				onPointerDown={(event) => {
					event.stopPropagation();
					onResizeStart(event, area.id);
				}}
				role="button"
				aria-label={t('Resize area')}
			/>
		)}
	</div>
);
