// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingInstanceDetailView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Instance',
};

const ParsingInstancePage = async ({
	params,
}: {
	params: Promise<{ document: string; run: string }>;
}) => {
	// The segments arrive encoded; the backend matches them against the folder
	// names it wrote, so they are decoded here rather than compared raw.
	const { document, run } = await params;
	return (
		<ParsingInstanceDetailView
			document={decodeURIComponent(document)}
			run={decodeURIComponent(run)}
		/>
	);
};

export default ParsingInstancePage;
