// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingWorkspace } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Workspace',
};

// The section lands on the workspace: upload, profile, and the current task.
// Durable tasks live under /parsing/tasks and results under /parsing/library.
export default function ParsingPage() {
	return <ParsingWorkspace />;
}
