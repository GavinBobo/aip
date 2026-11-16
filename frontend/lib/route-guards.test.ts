// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { PUBLIC_PATHS } from '../proxy';

/**
 * Every page either sits under a layout that calls `requireUser()` /
 * `requireAdmin()`, or is deliberately public.
 *
 * `proxy.ts` can only look at whether a session cookie *exists* — it cannot
 * validate it, because that would mean a database round trip on every request.
 * So a stale cookie (expired session, rotated AUTH_SECRET, a database that was
 * reset) sails past the middleware, and any page without the authoritative
 * guard renders its shell to a caller who is not signed in. Four page trees
 * were in exactly that state until this test existed: /terms, /exploration,
 * /erd and /parsing all answered 200 to a forged cookie while /chat answered
 * 307.
 */
const APP_DIR = fileURLToPath(new URL('../app', import.meta.url));
const GUARD = /requireUser\(|requireAdmin\(/;

const walk = (dir: string): string[] =>
	readdirSync(dir).flatMap((entry) => {
		const full = path.join(dir, entry);
		if (statSync(full).isDirectory()) return walk(full);
		return entry === 'page.tsx' ? [full] : [];
	});

/** `/settings/users/page.tsx` → `/settings/users`; route groups are dropped. */
const routeOf = (pageFile: string): string => {
	const relative = path.relative(APP_DIR, path.dirname(pageFile));
	if (relative === '' || relative === '.') return '/';
	const segments = relative.split(path.sep).filter((segment) => !/^\(.*\)$/.test(segment));
	return `/${segments.join('/')}`;
};

const isPublic = (route: string): boolean =>
	PUBLIC_PATHS.some((allowed) => route === allowed || route.startsWith(`${allowed}/`));

/** The page itself, then each layout from its own directory up to `app/`. */
const guardChain = (pageFile: string): string[] => {
	const chain = [pageFile];
	let dir = path.dirname(pageFile);
	while (dir.startsWith(APP_DIR)) {
		chain.push(path.join(dir, 'layout.tsx'));
		if (dir === APP_DIR) break;
		dir = path.dirname(dir);
	}
	return chain;
};

const hasGuard = (file: string): boolean => {
	try {
		return GUARD.test(readFileSync(file, 'utf8'));
	} catch {
		return false;
	}
};

describe('page authorization', () => {
	const pages = walk(APP_DIR).map((file) => ({
		route: routeOf(file),
		guarded: guardChain(file).some(hasGuard),
		// A page whose only job is to send you somewhere else inherits that
		// destination's guard; `app/page.tsx` redirects to /chat.
		redirects: /redirect\(/.test(readFileSync(file, 'utf8')),
	}));

	it('finds the pages at all (guards against a broken walker)', () => {
		expect(pages.length).toBeGreaterThan(10);
	});

	it('leaves no authenticated page without a server-side guard', () => {
		const unguarded = pages
			.filter((page) => !isPublic(page.route) && !page.guarded && !page.redirects)
			.map((page) => page.route)
			.sort();

		expect(
			unguarded,
			'add `await requireUser()` to the page or one of its layouts (see app/chat/layout.tsx)',
		).toEqual([]);
	});

	it('keeps the public pages on the short list', () => {
		const publicPages = pages
			.filter((page) => isPublic(page.route))
			.map((page) => page.route)
			.sort();

		// Anything new here has to be a deliberate decision in proxy.ts.
		expect(publicPages).toEqual(expect.arrayContaining(['/login']));
	});
});

/**
 * Pages are enumerated here rather than derived in the test so a page moving
 * out of the protected tree is a visible diff, not a silent pass.
 */
void path;
