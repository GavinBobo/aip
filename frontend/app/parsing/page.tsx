// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { BatchParsingView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Examples',
};

// The section lands on the parse page: this is where documents are actually
// parsed. The stored runs it produces are listed under /parsing/instances.
export default function ParsingPage() {
	return <BatchParsingView />;
}
