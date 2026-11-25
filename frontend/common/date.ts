// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import dayjs from 'dayjs';
import { getActiveLocale } from '@/i18n';

export type DateInput = string | number | Date;

export const formatDate = (value: DateInput, format = 'MMM DD YYYY'): string =>
	dayjs(value).format(format);

/**
 * A date and time in the reader's language.
 *
 * `Date#toLocaleString()` follows the browser, not the app's language switch,
 * so an English reader on a Chinese machine saw Chinese-formatted timestamps.
 */
export const formatDateTime = (value: DateInput): string =>
	new Intl.DateTimeFormat(getActiveLocale() === 'zh' ? 'zh-CN' : 'en-US', {
		dateStyle: 'medium',
		timeStyle: 'short',
	}).format(dayjs(value).toDate());
