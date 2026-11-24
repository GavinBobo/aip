// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { redirect } from 'next/navigation';

// The batch form moved to the section root (/parsing) when the two pages were
// swapped; keep the old link working for anyone who bookmarked it.
export default function ParsingBatchPage() {
	redirect('/parsing');
}
