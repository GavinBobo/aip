// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { moveItem } from './ordering';

describe('moveItem', () => {
	it('moves an item down without losing the rows in between', () => {
		expect(moveItem(['id', 'name', 'created_at'], 0, 2)).toEqual(['name', 'created_at', 'id']);
	});

	it('moves an item up', () => {
		expect(moveItem(['id', 'name', 'created_at'], 2, 0)).toEqual(['created_at', 'id', 'name']);
	});

	it('leaves the list alone when the move is a no-op or out of bounds', () => {
		expect(moveItem(['id', 'name'], 1, 1)).toEqual(['id', 'name']);
		expect(moveItem(['id', 'name'], -1, 0)).toEqual(['id', 'name']);
		expect(moveItem(['id', 'name'], 0, 2)).toEqual(['id', 'name']);
	});
});
