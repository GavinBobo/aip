// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { KnowledgeSearchView } from '@/components/knowledgePage';

export default async function KnowledgeSearchPage({
	searchParams,
}: {
	searchParams: Promise<{ q?: string | string[] }>;
}) {
	const params = await searchParams;
	return <KnowledgeSearchView initialQuery={typeof params.q === 'string' ? params.q : ''} />;
}
