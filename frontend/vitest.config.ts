// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/**
 * Unit tests for the pure modules under `lib/`.
 *
 * Deliberately narrow: no DOM, no React, no network. The canvas geometry, the
 * undo stack and the clipboard serialisation are exactly where a silent
 * regression costs the most and where a test costs the least, so they run in
 * plain Node with only the `@/` alias mapped.
 */
export default defineConfig({
	resolve: {
		alias: {
			'@': fileURLToPath(new URL('.', import.meta.url)).replace(/[\\/]$/, ''),
		},
	},
	test: {
		environment: 'node',
		include: ['lib/**/*.test.ts'],
	},
});
