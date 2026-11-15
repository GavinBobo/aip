// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Locale } from '../locale';
import { zh } from './zh';

/**
 * English is the source language: the copy in the components *is* the English
 * message, so that table is empty and every key resolves to itself.
 */
export const messages: Record<Locale, Record<string, string>> = {
	en: {},
	zh,
};

export { zh };
