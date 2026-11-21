// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingInstancesView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Create Batch Parsing Task',
};

// The stored runs, with the detail pages nested below this route
// (/parsing/instances/{document}/{run}).
export default function ParsingInstancesPage() {
	return <ParsingInstancesView />;
}
