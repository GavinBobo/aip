// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ErdColumn, ErdColumnStyle } from '@/types/erd';

export const COLUMN_STYLE_OPTIONS: { value: ErdColumnStyle; label: string }[] = [
	{ value: 'normal', label: 'Normal' },
	{ value: 'bold', label: 'Bold' },
	{ value: 'italic', label: 'Italic' },
	{ value: 'monospace', label: 'Monospace' },
];

export const columnStyleClass = (style: ErdColumn['style']) => {
	if (style === 'bold') return 'font-semibold';
	if (style === 'italic') return 'italic';
	if (style === 'monospace') return 'font-mono';
	return '';
};
