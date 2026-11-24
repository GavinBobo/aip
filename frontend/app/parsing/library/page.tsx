// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingLibraryView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Result Library',
};

export default function ParsingLibraryPage() {
	return <ParsingLibraryView />;
}
