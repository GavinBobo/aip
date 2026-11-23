// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

import { t } from '@/i18n';
import type { ErdNote } from '@/types/erd';

type NoteCardProps = {
	note: ErdNote;
	readOnly: boolean;
	onDragStart: (event: ReactPointerEvent, noteId: string) => void;
	onResizeStart: (event: ReactPointerEvent, noteId: string) => void;
	onTextChange: (noteId: string, text: string) => void;
	onTextCommit: (noteId: string) => void;
	onDelete: (noteId: string) => void;
};

export const NoteCard = ({
	note,
	readOnly,
	onDragStart,
	onResizeStart,
	onTextChange,
	onTextCommit,
	onDelete,
}: NoteCardProps) => {
	const textareaRef = useRef<HTMLTextAreaElement | null>(null);

	// The textarea lives in a scaled layer, so its intrinsic size has to follow
	// the note rather than the other way round.
	useEffect(() => {
		const element = textareaRef.current;
		if (element) element.scrollTop = 0;
	}, []);

	return (
		<div
			data-erd-note={note.id}
			className="absolute rounded-lg border shadow-sm"
			style={{
				left: note.x,
				top: note.y,
				width: note.width,
				height: note.height,
				backgroundColor: note.color ?? '#fef3c7',
				borderColor: 'rgba(180, 83, 9, 0.35)',
			}}
		>
			<div
				className={`flex h-6 items-center justify-between gap-1 rounded-t-lg border-b border-amber-900/20 px-2 text-[10px] font-medium text-amber-900/80 ${
					readOnly ? '' : 'cursor-grab active:cursor-grabbing'
				}`}
				onPointerDown={(event) => {
					if (!readOnly) onDragStart(event, note.id);
				}}
			>
				<span className="truncate">{t('Note')}</span>
				{!readOnly && (
					<button
						type="button"
						className="rounded px-1 text-amber-900/70 hover:bg-amber-900/10"
						onPointerDown={(event) => event.stopPropagation()}
						onClick={() => onDelete(note.id)}
						aria-label={t('Delete note')}
					>
						✕
					</button>
				)}
			</div>
			<textarea
				ref={textareaRef}
				value={note.text}
				readOnly={readOnly}
				onChange={(event) => onTextChange(note.id, event.target.value)}
				onBlur={() => onTextCommit(note.id)}
				placeholder={t('Write a note…')}
				className="h-[calc(100%-1.5rem)] w-full resize-none rounded-b-lg bg-transparent px-2 py-1.5 text-[11px] leading-relaxed text-amber-950 outline-none placeholder:text-amber-900/40"
			/>
			{!readOnly && (
				<span
					className="absolute -bottom-1.5 -right-1.5 z-10 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-amber-500 bg-white"
					onPointerDown={(event) => {
						event.stopPropagation();
						onResizeStart(event, note.id);
					}}
					role="button"
					aria-label={t('Resize note')}
					title={t('Drag to resize note')}
				/>
			)}
		</div>
	);
};
