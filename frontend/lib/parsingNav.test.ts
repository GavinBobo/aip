// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { activeSectionHref } from './parsingNav';

const HREFS = ['/parsing', '/parsing/batch'];

describe('activeSectionHref', () => {
	it('selects only the instances entry on the list page', () => {
		expect(activeSectionHref('/parsing', HREFS)).toBe('/parsing');
	});

	it('selects only the batch entry on the batch page', () => {
		// `/parsing` is a prefix here too; the most specific href must win.
		expect(activeSectionHref('/parsing/batch', HREFS)).toBe('/parsing/batch');
	});

	it('keeps the instances entry active on instance detail pages', () => {
		expect(activeSectionHref('/parsing/instances/doc-1/run-1', HREFS)).toBe('/parsing');
	});

	it('ignores trailing slashes', () => {
		expect(activeSectionHref('/parsing/batch/', HREFS)).toBe('/parsing/batch');
		expect(activeSectionHref('/parsing/', HREFS)).toBe('/parsing');
	});

	it('does not match sibling routes that only share a string prefix', () => {
		expect(activeSectionHref('/parsingfoo', HREFS)).toBeNull();
		expect(activeSectionHref('/parsing/batch-2', HREFS)).toBe('/parsing');
	});

	it('returns null outside the section', () => {
		expect(activeSectionHref('/settings/zones', HREFS)).toBeNull();
	});
});
