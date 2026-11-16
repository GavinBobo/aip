// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const stripTrailingSlash = (path: string): string =>
	path.length > 1 ? path.replace(/\/+$/, '') : path;

const owns = (root: string, pathname: string): boolean =>
	root === '/' || pathname === root || pathname.startsWith(`${root}/`);

/**
 * Returns the nav href that owns `pathname`, or `null` when the path is
 * outside the section.
 *
 * The longest href wins. `/parsing` is both the instances page and the parent
 * segment of `/parsing/batch`, so a plain "does any prefix match" test selects
 * both entries at once; comparing match lengths keeps exactly one active.
 */
export const activeSectionHref = (pathname: string, hrefs: readonly string[]): string | null => {
	const path = stripTrailingSlash(pathname);
	let best: string | null = null;
	for (const href of hrefs) {
		const root = stripTrailingSlash(href);
		if (!owns(root, path)) continue;
		if (best === null || root.length > stripTrailingSlash(best).length) {
			best = href;
		}
	}
	return best;
};
