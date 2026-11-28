// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import path from 'node:path';
import dotenv from 'dotenv';
import type { NextConfig } from 'next';

dotenv.config({ path: path.resolve(__dirname, '..', '.env') });

/**
 * Hostnames the browser may use to reach the dev server. Next only trusts the
 * hostname it was started with (`localhost` by default); opening the app at
 * `127.0.0.1` or a LAN name otherwise makes every `/_next/*` request 403, so
 * the page never hydrates.
 *
 * This option matches hostnames only - no scheme and no port. Better Auth's
 * `trustedOrigins` needs the opposite shape, so the same env variable is read
 * here and stripped down instead of maintained as a second list.
 */
const devOriginHostnames = (): string[] => {
	const hosts = new Set(['127.0.0.1', '[::1]']);

	const addHost = (value: string | undefined): void => {
		if (!value) return;
		try {
			hosts.add(new URL(value).hostname);
		} catch {
			// A bare `host:port` is not a valid origin. Skipping it keeps the
			// dev server bootable while Better Auth reports the bad value.
		}
	};

	addHost(process.env.APP_URL);
	for (const origin of (process.env.AUTH_TRUSTED_ORIGINS ?? '').split(',')) {
		addHost(origin.trim());
	}

	return [...hosts];
};

// NOTE: there are intentionally no `rewrites()`. Every /api/* path that used to
// be proxied to the Python backend via a rewrite is now served by a dedicated,
// permission-gated route handler under app/api/** that forwards to the backend
// (see auth/proxy-backend.ts + withPermission). Rewrites bypass route handlers,
// so they can't be access-controlled — hence the move.
const nextConfig: NextConfig = {
	allowedDevOrigins: devOriginHostnames(),
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
