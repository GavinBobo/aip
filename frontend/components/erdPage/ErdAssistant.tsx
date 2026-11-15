// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useMemo, useRef, useState } from 'react';

import { erdApi, type AssistantCanvasInput } from '@/api/erd';
import { Button } from '@/common/Button';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdAssistantAction, ErdNode, ErdRelationship } from '@/types/erd';

type Turn = {
	role: 'user' | 'assistant';
	content: string;
	/** How many edits the browser actually applied for this answer. */
	applied?: number;
	/** Actions the server refused to hand back, plus any that failed to apply. */
	warnings?: string[];
};

type ErdAssistantProps = {
	zoneId: string | null;
	readOnly: boolean;
	nodes: ErdNode[];
	relationships: ErdRelationship[];
	/** Apply one validated batch. Must return how many edits landed. */
	onApply: (actions: ErdAssistantAction[]) => Promise<{ applied: number; failed: number }>;
};

/** How much conversation to send back; the server trims further. */
const HISTORY_TURNS = 8;

const RobotIcon = () => (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
		<rect x="4" y="7.5" width="16" height="12" rx="4" />
		<path d="M12 4v3.5M9 13h.01M15 13h.01M9.5 16.5h5" strokeLinecap="round" />
		<circle cx="12" cy="3.2" r="1.2" fill="currentColor" stroke="none" />
	</svg>
);

const toCanvasInput = (
	nodes: ErdNode[],
	relationships: ErdRelationship[],
): AssistantCanvasInput => {
	const nameById = new Map(nodes.map((node) => [node.id, node.name]));
	return {
		nodes: nodes.map((node) => ({
			id: node.id,
			name: node.name,
			table_id: node.table_id,
			columns: node.columns.map((column) => ({
				name: column.name,
				data_type: column.data_type,
				note: column.note ?? null,
			})),
			note: node.note,
		})),
		relationships: relationships.map((relationship) => ({
			id: relationship.id,
			source: nameById.get(relationship.source_node_id) ?? '',
			target: nameById.get(relationship.target_node_id) ?? '',
			source_columns: relationship.source_columns,
			target_columns: relationship.target_columns,
			cardinality: relationship.cardinality,
			label: relationship.label,
		})),
	};
};

export const ErdAssistant = ({
	zoneId,
	readOnly,
	nodes,
	relationships,
	onApply,
}: ErdAssistantProps) => {
	const [open, setOpen] = useState(false);
	const [turns, setTurns] = useState<Turn[]>([]);
	const [draft, setDraft] = useState('');
	const [busy, setBusy] = useState(false);
	const listRef = useRef<HTMLDivElement>(null);

	const canvasInput = useMemo(() => toCanvasInput(nodes, relationships), [nodes, relationships]);

	const scrollToEnd = useCallback(() => {
		const list = listRef.current;
		if (list) list.scrollTop = list.scrollHeight;
	}, []);

	const send = useCallback(async () => {
		const message = draft.trim();
		if (!message || busy || readOnly || !zoneId) return;
		setDraft('');
		setTurns((current) => [...current, { role: 'user', content: message }]);
		setBusy(true);
		window.setTimeout(scrollToEnd, 0);

		const history = turns
			.slice(-HISTORY_TURNS)
			.map((turn) => ({ role: turn.role, content: turn.content }));
		const response = await erdApi.askAssistant({
			zone_id: zoneId,
			message,
			canvas: canvasInput,
			history,
		});

		if (response.error || !response.data) {
			setTurns((current) => [
				...current,
				{
					role: 'assistant',
					content: response.message ?? t('The assistant is unavailable right now.'),
					warnings: [],
				},
			]);
			setBusy(false);
			window.setTimeout(scrollToEnd, 0);
			return;
		}

		const { reply, actions, warnings } = response.data;
		let applied = 0;
		const failed: string[] = [];
		if (actions.length > 0) {
			const result = await onApply(actions);
			applied = result.applied;
			if (result.failed > 0) {
				failed.push(
					t('{0} change(s) could not be applied and were skipped.', {
						0: String(result.failed),
					}),
				);
			}
		}

		setTurns((current) => [
			...current,
			{ role: 'assistant', content: reply, applied, warnings: [...warnings, ...failed] },
		]);
		setBusy(false);
		window.setTimeout(scrollToEnd, 0);
	}, [busy, canvasInput, draft, onApply, readOnly, scrollToEnd, turns, zoneId]);

	if (!open) {
		return (
			<button
				type="button"
				onClick={() => setOpen(true)}
				className="absolute bottom-5 left-5 z-20 flex h-12 w-12 items-center justify-center rounded-full bg-[#76b900] text-white shadow-lg shadow-black/20 transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#76b900]/50"
				aria-label={t('Canvas assistant')}
				title={t('Ask the assistant to change this diagram')}
			>
				<span className="h-6 w-6">
					<RobotIcon />
				</span>
			</button>
		);
	}

	return (
		<section
			role="dialog"
			aria-label={t('Canvas assistant')}
			className="absolute bottom-5 left-5 z-20 flex max-h-[70vh] w-[360px] flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
		>
			<header className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
				<span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#76b900]/15 text-[#5c9200] dark:text-[#a3e635]">
					<span className="h-4 w-4">
						<RobotIcon />
					</span>
				</span>
				<h2 className="flex-1 truncate text-sm font-semibold text-heading dark:text-zinc-100">
					{t('Canvas assistant')}
				</h2>
				<Button
					theme={ButtonTheme.IconNeutral}
					size={Size.SMALL}
					iconOnly
					onClick={() => setOpen(false)}
					aria-label={t('Close')}
				>
					✕
				</Button>
			</header>

			<div ref={listRef} className="min-h-[160px] flex-1 space-y-3 overflow-y-auto px-3 py-3">
				{turns.length === 0 && (
					<div className="space-y-2 text-xs text-secondary dark:text-zinc-400">
						<p>{t('Tell me what to change and I will edit this canvas.')}</p>
						<ul className="space-y-1">
							<li>· {t('Add a shipped_at column to orders')}</li>
							<li>· {t('Link orders to customers on customer_id')}</li>
							<li>· {t('What is this table for?')}</li>
						</ul>
					</div>
				)}
				{turns.map((turn, index) => (
					<div
						// Turns are append-only and never reordered, so the index is stable.
						key={`${turn.role}-${index}`}
						className={
							turn.role === 'user'
								? 'ml-8 rounded-2xl rounded-br-sm bg-[#76b900] px-3 py-2 text-xs text-white'
								: 'mr-6 rounded-2xl rounded-bl-sm bg-zinc-100 px-3 py-2 text-xs text-body dark:bg-zinc-800 dark:text-zinc-200'
						}
					>
						<p className="whitespace-pre-wrap break-words">{turn.content}</p>
						{turn.applied != null && turn.applied > 0 && (
							<p className="mt-1 text-[11px] text-emerald-600 dark:text-emerald-400">
								{t('Applied {0} change(s). Undo (Ctrl+Z) reverts the batch.', {
									0: String(turn.applied),
								})}
							</p>
						)}
						{turn.warnings != null && turn.warnings.length > 0 && (
							<ul className="mt-1 space-y-0.5 text-[11px] text-amber-600 dark:text-amber-400">
								{turn.warnings.map((warning) => (
									<li key={warning}>· {warning}</li>
								))}
							</ul>
						)}
					</div>
				))}
				{busy && (
					<p className="text-[11px] text-secondary dark:text-zinc-400">
						{t('Thinking…')}
					</p>
				)}
			</div>

			<div className="border-t border-zinc-200 p-2 dark:border-zinc-700">
				<textarea
					value={draft}
					onChange={(event) => setDraft(event.target.value)}
					onKeyDown={(event) => {
						if (event.key === 'Enter' && !event.shiftKey) {
							event.preventDefault();
							void send();
						}
					}}
					rows={2}
					disabled={busy || readOnly}
					placeholder={
						readOnly
							? t('Only an admin can change this diagram.')
							: t('Describe the change, Enter to send')
					}
					className="w-full resize-none rounded-lg border border-zinc-300 bg-white p-2 text-xs text-body outline-none focus:border-[#76b900] disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-950 dark:text-zinc-200"
				/>
				<div className="mt-1 flex items-center justify-end gap-2">
					<Button
						theme={ButtonTheme.Primary}
						size={Size.SMALL}
						loading={busy}
						disabled={busy || readOnly || draft.trim() === ''}
						onClick={() => void send()}
					>
						{t('Send')}
					</Button>
				</div>
			</div>
		</section>
	);
};
