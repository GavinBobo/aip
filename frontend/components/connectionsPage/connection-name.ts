// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';

/**
 * Connection names double as the catalog key, so the rule mirrors the
 * backend's `validate_name` in all_ontology/server/connections/files.py:
 * starts with a letter or underscore, then letters, digits, or underscores,
 * at most 64 characters, and not a name shadowed by a fixed API route.
 */
export const CONNECTION_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

/** `test`, `source`, `file`, and `api` are fixed `/api/connections/...` routes. */
export const RESERVED_CONNECTION_NAMES = new Set(['test', 'source', 'file', 'api']);

export type ConnectionNameIssue = 'empty' | 'pattern' | 'reserved';

export const connectionNameIssue = (name: string): ConnectionNameIssue | null => {
	const trimmed = name.trim();
	if (trimmed === '') return 'empty';
	if (!CONNECTION_NAME_PATTERN.test(trimmed)) return 'pattern';
	if (RESERVED_CONNECTION_NAMES.has(trimmed.toLowerCase())) return 'reserved';
	return null;
};

export const isValidConnectionName = (name: string): boolean =>
	connectionNameIssue(name) === null;

/** The message shown when the typed name would be rejected by the backend. */
export const connectionNameErrorMessage = (name: string): string | null => {
	switch (connectionNameIssue(name)) {
		case 'empty':
			return t('A name is required.');
		case 'pattern':
			return t(
				'Use letters, digits, and underscores; start with a letter or underscore (max 64 characters).',
			);
		case 'reserved':
			return t('This name is reserved by the API; choose a different name.');
		default:
			return null;
	}
};
