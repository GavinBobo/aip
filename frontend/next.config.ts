// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import path from 'node:path';
import dotenv from 'dotenv';
import type { NextConfig } from 'next';

dotenv.config({ path: path.resolve(__dirname, '..', '.env') });

// NOTE: there are intentionally no `rewrites()`. Every /api/* path that used to
// be proxied to the Python backend via a rewrite is now served by a dedicated,
// permission-gated route handler under app/api/** that forwards to the backend
// (see auth/proxy-backend.ts + withPermission). Rewrites bypass route handlers,
// so they can't be access-controlled — hence the move.
const nextConfig: NextConfig = {
	// The dev indicator is Next.js's own overlay (Route / Bundler / Preferences)
	// and is not part of this app's UI; it is also English-only, so keeping it
	// on makes the product look half-localized during demos. Errors still surface
	// without it. Remove this line to get the indicator back while debugging.
	// Next 16 accepts `false` or a position object here; `true` no longer type
	// checks and fails `next build`.
	devIndicators: false,
	// Slow CI/host machines can exceed Next's 60s per-page default while the
	// settings pages initialize Prisma/auth; this only widens the build timeout.
	staticPageGenerationTimeout: 180,
	output: process.env.NEXT_OUTPUT === 'standalone' ? 'standalone' : undefined,
	outputFileTracingRoot: path.resolve(__dirname, '..'),
	transpilePackages: ['@nvidia/foundations-react-core'],
	turbopack: {
		rules: {
			'*.svg': {
				loaders: [{ loader: '@svgr/webpack', options: { svgo: false } }],
				as: '*.js',
			},
		},
	},
};

export default nextConfig;
