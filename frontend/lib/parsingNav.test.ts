// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { activeSectionHref } from './parsingNav';

const HREFS = ['/parsing', '/parsing/tasks', '/parsing/library'];

describe('activeSectionHref', () => {
	it('selects only the parse entry on the section root', () => {
		expect(activeSectionHref('/parsing', HREFS)).toBe('/parsing');
	});

	it('selects only the task entry on the tasks page', () => {
		// `/parsing` is a prefix here too; the most specific href must win.
		expect(activeSectionHref('/parsing/tasks', HREFS)).toBe('/parsing/tasks');
	});

	it('keeps the library entry active on run detail pages', () => {
		expect(activeSectionHref('/parsing/library/run-1', HREFS)).toBe('/parsing/library');
	});

	it('ignores trailing slashes', () => {
		expect(activeSectionHref('/parsing/tasks/', HREFS)).toBe('/parsing/tasks');
		expect(activeSectionHref('/parsing/', HREFS)).toBe('/parsing');
	});

	it('does not match sibling routes that only share a string prefix', () => {
		expect(activeSectionHref('/parsingfoo', HREFS)).toBeNull();
		expect(activeSectionHref('/parsing/tasks-2', HREFS)).toBe('/parsing');
	});

	it('returns null outside the section', () => {
		expect(activeSectionHref('/settings/zones', HREFS)).toBeNull();
	});
});
