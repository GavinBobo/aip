// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { KnowledgeNetworkView } from '@/components/knowledgePage';

export const metadata: Metadata = {
	title: 'Knowledge Network',
};

const KnowledgeNetworkPage = async ({
	params,
}: {
	params: Promise<{ network_id: string }>;
}) => {
	const { network_id } = await params;
	return <KnowledgeNetworkView networkId={decodeURIComponent(network_id)} />;
};

export default KnowledgeNetworkPage;
