// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { isEditableTarget } from './shortcuts';

describe('isEditableTarget', () => {
	it.each(['INPUT', 'TEXTAREA', 'SELECT'])('keeps native shortcuts in <%s>', (tagName) => {
		expect(isEditableTarget({ tagName })).toBe(true);
	});

	it('keeps native shortcuts inside contenteditable blocks', () => {
		expect(isEditableTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true);
	});

	it('lets canvas shortcuts run on ordinary elements', () => {
		expect(isEditableTarget({ tagName: 'DIV' })).toBe(false);
		expect(isEditableTarget(null)).toBe(false);
	});
});
