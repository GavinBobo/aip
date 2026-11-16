// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { BatchParsingView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Create Batch Parsing Task',
};

export default function ParsingBatchPage() {
	return <BatchParsingView />;
}
