// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export {
	DEFAULT_LOCALE,
	HTML_LANG,
	LOCALE_LABEL,
	LOCALE_STORAGE_KEY,
	LOCALES,
	isLocale,
	type Locale,
} from './locale';
export { getActiveLocale, setActiveLocale, t, type TranslateParams } from './translate';
export { useI18n } from './I18nProvider';
