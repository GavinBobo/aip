// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { ParsingTasksView } from '@/components/parsingPage';

export const metadata: Metadata = {
	title: 'Parsing Tasks',
};

export default function ParsingTasksPage() {
	return <ParsingTasksView />;
}
