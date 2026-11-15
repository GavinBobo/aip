// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { Button } from '@/common/Button';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdCardinality, ErdNode, ErdRelationship } from '@/types/erd';

const CARDINALITIES: { value: ErdCardinality; label: string }[] = [
	{ value: 'many-to-one', label: 'N : 1' },
	{ value: 'one-to-many', label: '1 : N' },
	{ value: 'one-to-one', label: '1 : 1' },
	{ value: 'many-to-many', label: 'N : M' },
];

type RelationshipPanelProps = {
	relationship: ErdRelationship;
	source: ErdNode | undefined;
	target: ErdNode | undefined;
	readOnly: boolean;
	onChange: (patch: { cardinality?: ErdCardinality; label?: string }) => void;
	onDelete: () => void;
	onClose: () => void;
};

export const RelationshipPanel = ({
	relationship,
	source,
	target,
	readOnly,
	onChange,
	onDelete,
	onClose,
}: RelationshipPanelProps) => {
	const [label, setLabel] = useState(relationship.label ?? '');

	return (
		<div className="absolute bottom-4 right-4 z-20 w-72 rounded-xl border border-zinc-200 bg-white p-3 shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
			<div className="mb-2 flex items-center justify-between">
				<span className="text-xs font-semibold text-heading dark:text-zinc-200">
					{t('Relationship')}
				</span>
				<Button
					theme={ButtonTheme.IconNeutral}
					size={Size.SMALL}
					iconOnly
					type="button"
					onClick={onClose}
					aria-label={t('Close')}
				>
					✕
				</Button>
			</div>
			<p
				className="mb-2 truncate text-[11px] text-secondary dark:text-zinc-400"
				title={`${source?.name} → ${target?.name}`}
			>
				{source?.name} → {target?.name}
			</p>
			<label className="block text-[11px] font-medium text-body dark:text-zinc-300">
				{t('Cardinality')}
				<select
					value={relationship.cardinality}
					disabled={readOnly}
					onChange={(event) =>
						onChange({ cardinality: event.target.value as ErdCardinality })
					}
					className="mt-1 h-8 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs text-body disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200"
				>
					{CARDINALITIES.map((option) => (
						<option key={option.value} value={option.value}>
							{option.label}
						</option>
					))}
				</select>
			</label>
			<label className="mt-2 block text-[11px] font-medium text-body dark:text-zinc-300">
				{t('Note')}
				<input
					value={label}
					disabled={readOnly}
					onChange={(event) => setLabel(event.target.value)}
					onBlur={() => {
						if (label !== (relationship.label ?? '')) onChange({ label });
					}}
					className="mt-1 h-8 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs text-body outline-none focus:border-[#76b900] disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200"
				/>
			</label>
			{!readOnly && (
				<div className="mt-2">
					<Button
						theme={ButtonTheme.DangerSubtle}
						size={Size.SMALL}
						type="button"
						full
						onClick={onDelete}
					>
						{t('Delete relationship')}
					</Button>
				</div>
			)}
		</div>
	);
};
