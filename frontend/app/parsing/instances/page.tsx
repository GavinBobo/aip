// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { redirect } from 'next/navigation';

// The old list URL predates durable runs. Keep it working for bookmarks;
// detail URLs under /parsing/instances/{document}/{run} still resolve.
export default function ParsingInstancesPage() {
	redirect('/parsing/library');
}
