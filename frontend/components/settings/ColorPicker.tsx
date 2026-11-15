// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { t } from '@/i18n';

import { Popover } from '@/common/Popover';
import { ColorSwatch } from '@/components/settings/ColorSwatch';
import { Size } from '@/enums/button';

export type ColorOption = {
	value: string;
	label: string;
	colorClass: string;
};

/**
 * The colour set offered for zones and user groups.
 *
 * Values are Tailwind's 500-shade hexes and each option's `colorClass` names
 * the same shade, so the swatch and the stored value always agree — the rest of
 * the app paints with the raw hex, not with a class, so a new option needs no
 * other registry. Six was too few to tell a dozen zones apart; sixteen covers
 * the hue wheel with light/dark separation.
 */
export const COLOR_OPTIONS: readonly ColorOption[] = [
	{ value: '#3b82f6', label: 'Blue', colorClass: 'bg-blue-500' },
	{ value: '#0ea5e9', label: 'Sky', colorClass: 'bg-sky-500' },
	{ value: '#06b6d4', label: 'Cyan', colorClass: 'bg-cyan-500' },
	{ value: '#14b8a6', label: 'Teal', colorClass: 'bg-teal-500' },
	{ value: '#10b981', label: 'Emerald', colorClass: 'bg-emerald-500' },
	{ value: '#22c55e', label: 'Green', colorClass: 'bg-green-500' },
	{ value: '#eab308', label: 'Yellow', colorClass: 'bg-yellow-500' },
	{ value: '#f59e0b', label: 'Amber', colorClass: 'bg-amber-500' },
	{ value: '#f97316', label: 'Orange', colorClass: 'bg-orange-500' },
	{ value: '#ef4444', label: 'Red', colorClass: 'bg-red-500' },
	{ value: '#f43f5e', label: 'Rose', colorClass: 'bg-rose-500' },
	{ value: '#ec4899', label: 'Pink', colorClass: 'bg-pink-500' },
	{ value: '#a855f7', label: 'Purple', colorClass: 'bg-purple-500' },
	{ value: '#8b5cf6', label: 'Violet', colorClass: 'bg-violet-500' },
	{ value: '#6366f1', label: 'Indigo', colorClass: 'bg-indigo-500' },
	{ value: '#64748b', label: 'Slate', colorClass: 'bg-slate-500' },
];

type ColorPickerProps = {
	colors: readonly ColorOption[];
	value: string;
	onChange: (next: string) => void;
	fallbackColorClass?: string;
};

export const ColorPicker = ({
	colors,
	value,
	onChange,
	fallbackColorClass = 'bg-zinc-400',
}: ColorPickerProps) => {
	const selectedColorClass =
		colors.find((color) => color.value === value)?.colorClass ?? fallbackColorClass;

	return (
		<Popover
			className="shrink-0"
			panelClassName="w-52 p-2"
			trigger={({ toggle }) => (
				<ColorSwatch
					colorClass={selectedColorClass}
					size={Size.LARGE}
					onClick={toggle}
					aria-label={t('Pick Color')}
					title={t('Pick Color')}
				/>
			)}
		>
			{({ close }) => (
				<div className="grid grid-cols-4 gap-2">
					{colors.map((color) => (
						<ColorSwatch
							key={color.value}
							colorClass={color.colorClass}
							selected={value === color.value}
							onClick={() => {
								onChange(color.value);
								close();
							}}
							title={t(color.label)}
							aria-label={t('Color {0}', { 0: t(color.label) })}
						/>
					))}
				</div>
			)}
		</Popover>
	);
};
