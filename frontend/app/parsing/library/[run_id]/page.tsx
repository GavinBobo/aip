// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingRunDetailView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Result',
};

const ParsingLibraryRunPage = async ({ params }: { params: Promise<{ run_id: string }> }) => {
	const { run_id } = await params;
	return <ParsingRunDetailView runId={decodeURIComponent(run_id)} />;
};

export default ParsingLibraryRunPage;
