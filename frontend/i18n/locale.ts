// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export const LOCALES = ['en', 'zh'] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'en';

/**
 * Persisted in `localStorage` rather than the URL: the app has a single set of
 * routes and switching languages must not navigate. The key is versionless so
 * an upgrade keeps the reader's choice.
 */
export const LOCALE_STORAGE_KEY = 'auto-ontology.locale';

/** Value for the `lang` attribute, so screen readers and hyphenation follow. */
export const HTML_LANG: Record<Locale, string> = {
	en: 'en',
	zh: 'zh-CN',
};

export const LOCALE_LABEL: Record<Locale, string> = {
	en: 'English',
	zh: '中文',
};

export const isLocale = (value: unknown): value is Locale =>
	typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
