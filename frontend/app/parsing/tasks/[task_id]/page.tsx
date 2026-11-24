// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingTaskDetailView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Task',
};

const ParsingTaskPage = async ({ params }: { params: Promise<{ task_id: string }> }) => {
	const { task_id } = await params;
	return <ParsingTaskDetailView taskId={decodeURIComponent(task_id)} />;
};

export default ParsingTaskPage;
