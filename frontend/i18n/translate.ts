// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, isLocale, type Locale } from './locale';
import { messages } from './messages';

/**
 * The active locale for this browser tab.
 *
 * Translation is a plain function rather than a hook because most of the copy
 * lives in tables, option lists and module-level label maps. The provider
 * remounts its subtree when the locale changes, so every one of those readers
 * runs again. Server rendering always sees `DEFAULT_LOCALE`: server components
 * render English and the browser applies the stored choice during hydration.
 */
let activeLocale: Locale = DEFAULT_LOCALE;
const listeners = new Set<() => void>();

export const getActiveLocale = (): Locale => activeLocale;

export const setActiveLocale = (locale: Locale): void => {
	if (activeLocale === locale) return;
	activeLocale = locale;
	for (const listener of listeners) listener();
};

/**
 * Subscription used by `useSyncExternalStore`. The active locale lives in this
 * module rather than in React state so `t()` can stay a plain function; the
 * provider only mirrors it for re-rendering and for the switch control.
 */
export const subscribeLocale = (listener: () => void): (() => void) => {
	listeners.add(listener);
	return () => listeners.delete(listener);
};

export type TranslateParams = Record<string, string | number>;

const interpolate = (template: string, params?: TranslateParams): string => {
	if (params == null) return template;
	return template.replace(/\{(\w+)\}/g, (match, name: string) => {
		const value = params[name];
		return value == null ? match : String(value);
	});
};

/**
 * Translates an English source string. The English text is itself the key, so
 * an unknown string falls back to readable copy instead of a key name, and
 * adding a string never requires touching a second registry.
 *
 * `{name}` placeholders are filled from `params`.
 */
export const t = (source: string, params?: TranslateParams): string => {
	const template = messages[activeLocale][source] ?? source;
	return interpolate(template, params);
};

export const readStoredLocale = (): Locale | null => {
	if (typeof window === 'undefined') return null;
	try {
		const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
		return isLocale(stored) ? stored : null;
	} catch {
		// Storage can be blocked by browser privacy settings; the app still runs.
		return null;
	}
};
