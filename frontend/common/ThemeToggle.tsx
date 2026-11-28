// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';

import { Icon, IconName } from '@/common/icons';
import { t } from '@/i18n';

export const THEME_STORAGE_KEY = 'all-ontology-theme';

const isDark = (): boolean =>
	typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

/** Sun/moon switch for the application color mode. */
export const ThemeToggle = () => {
	const [dark, setDark] = useState(false);

	useEffect(() => {
		const frame = window.requestAnimationFrame(() => setDark(isDark()));
		return () => window.cancelAnimationFrame(frame);
	}, []);

	const toggle = () => {
		const next = !isDark();
		document.documentElement.classList.toggle('dark', next);
		document.documentElement.style.colorScheme = next ? 'dark' : 'light';
		try {
			localStorage.setItem(THEME_STORAGE_KEY, next ? 'dark' : 'light');
		} catch {
			// Storage can be unavailable in private modes; the visual toggle
			// still works for this page.
		}
		setDark(next);
	};

	return (
		<button
			type="button"
			onClick={toggle}
			aria-label={t(dark ? 'Switch to light mode' : 'Switch to dark mode')}
			title={t(dark ? 'Switch to light mode' : 'Switch to dark mode')}
			aria-pressed={dark}
			className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full border border-zinc-200 bg-zinc-50 text-body transition-colors hover:bg-zinc-100 hover:text-heading dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
		>
			<Icon name={dark ? IconName.Sun : IconName.Moon} className="h-4 w-4" />
		</button>
	);
};
