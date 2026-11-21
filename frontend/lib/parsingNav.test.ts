// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { activeSectionHref } from './parsingNav';

const HREFS = ['/parsing', '/parsing/instances'];

describe('activeSectionHref', () => {
	it('selects only the parse entry on the section root', () => {
		expect(activeSectionHref('/parsing', HREFS)).toBe('/parsing');
	});

	it('selects only the list entry on the instances page', () => {
		// `/parsing` is a prefix here too; the most specific href must win.
		expect(activeSectionHref('/parsing/instances', HREFS)).toBe('/parsing/instances');
	});

	it('keeps the list entry active on instance detail pages', () => {
		expect(activeSectionHref('/parsing/instances/doc-1/run-1', HREFS)).toBe(
			'/parsing/instances',
		);
	});

	it('ignores trailing slashes', () => {
		expect(activeSectionHref('/parsing/instances/', HREFS)).toBe('/parsing/instances');
		expect(activeSectionHref('/parsing/', HREFS)).toBe('/parsing');
	});

	it('does not match sibling routes that only share a string prefix', () => {
		expect(activeSectionHref('/parsingfoo', HREFS)).toBeNull();
		expect(activeSectionHref('/parsing/instances-2', HREFS)).toBe('/parsing');
	});

	it('returns null outside the section', () => {
		expect(activeSectionHref('/settings/zones', HREFS)).toBeNull();
	});
});
