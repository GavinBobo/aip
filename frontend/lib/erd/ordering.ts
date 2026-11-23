// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** Move one item to a new index, returning a new array. */
export const moveItem = <T,>(items: readonly T[], from: number, to: number): T[] => {
	const next = [...items];
	if (from === to || from < 0 || to < 0 || from >= next.length || to >= next.length) {
		return next;
	}
	const [moved] = next.splice(from, 1);
	next.splice(to, 0, moved);
	return next;
};
