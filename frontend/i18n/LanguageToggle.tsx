// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { LOCALES, LOCALE_LABEL, type Locale } from './locale';
import { useI18n } from './I18nProvider';
import { t } from './translate';

const SHORT_LABEL: Record<Locale, string> = {
	en: 'EN',
	zh: '中',
};

/**
 * Small segmented switch beside the account menu. It stays visible on the
 * signed-out screens too, so somebody who cannot read English can change the
 * language before signing in.
 */
export const LanguageToggle = () => {
	const { locale, setLocale } = useI18n();

	return (
		<div
			role="group"
			aria-label={t('Language')}
			className="flex h-8 items-center rounded-full border border-zinc-200 bg-zinc-50 p-0.5 dark:border-zinc-700 dark:bg-zinc-900"
		>
			{LOCALES.map((item) => {
				const selected = item === locale;
				return (
					<button
						key={item}
						type="button"
						onClick={() => setLocale(item)}
						aria-pressed={selected}
						title={LOCALE_LABEL[item]}
						className={`flex h-7 min-w-8 cursor-pointer items-center justify-center rounded-full px-2 text-xs font-medium transition-colors ${
							selected
								? 'bg-white text-heading shadow-sm dark:bg-zinc-700 dark:text-zinc-100'
								: 'text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-200'
						}`}
					>
						{SHORT_LABEL[item]}
					</button>
				);
			})}
		</div>
	);
};
