// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
	Fragment,
	createContext,
	useEffect,
	useCallback,
	useContext,
	useLayoutEffect,
	useMemo,
	useSyncExternalStore,
	type ReactNode,
} from 'react';
import { DEFAULT_LOCALE, HTML_LANG, LOCALE_STORAGE_KEY, type Locale } from './locale';
import { getActiveLocale, readStoredLocale, setActiveLocale, subscribeLocale } from './translate';

type I18nContextValue = {
	locale: Locale;
	setLocale: (locale: Locale) => void;
};

const I18nContext = createContext<I18nContextValue>({
	locale: DEFAULT_LOCALE,
	setLocale: () => undefined,
});

export const useI18n = (): I18nContextValue => useContext(I18nContext);

/**
 * Holds the reader's language for the whole app.
 *
 * The first client render matches the server (English) so hydration is clean;
 * a layout effect then swaps in the stored choice before the browser paints.
 * Changing the language remounts the subtree under a new key, which is what
 * lets `t()` stay a plain function usable from module-level label maps: every
 * component that reads copy renders again, once, without subscribing itself.
 */
export const I18nProvider = ({ children }: { children: ReactNode }) => {
	// The server snapshot keeps hydration on the default; the store's current
	// value takes over once the client mounts.
	const locale = useSyncExternalStore(subscribeLocale, getActiveLocale, () => DEFAULT_LOCALE);

	const setLocale = useCallback((next: Locale) => {
		setActiveLocale(next);
		try {
			window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
		} catch {
			// Private-mode storage failures must not break the switch itself.
		}
	}, []);

	// Read after hydration rather than during it: the stored choice has to be
	// applied in a separate commit so the keyed subtree below actually remounts
	// and every `t()` reads the new locale. On the server, and for the first
	// client render, the app is English — the switch lands in the next commit.
	useEffect(() => {
		const stored = readStoredLocale();
		if (stored != null) {
			setActiveLocale(stored);
		}
	}, []);

	useLayoutEffect(() => {
		setActiveLocale(locale);
		document.documentElement.lang = HTML_LANG[locale];
	}, [locale]);

	const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);

	return (
		<I18nContext value={value}>
			<Fragment key={locale}>{children}</Fragment>
		</I18nContext>
	);
};
