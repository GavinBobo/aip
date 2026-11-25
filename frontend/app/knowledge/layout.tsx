// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { requireUser } from '@/auth/auth-guards';
import { BackPanelLayout } from '@/common/BackPanelLayout';
import { KnowledgeSidebar } from '@/components/knowledgePage';
import { t } from '@/i18n';

export const metadata: Metadata = {
	title: 'Knowledge Ontology',
};

export default async function KnowledgeLayout({ children }: { children: React.ReactNode }) {
	await requireUser();
	return (
		<BackPanelLayout
			panelAriaLabel={t('Knowledge ontology sections')}
			expandAriaLabel={t('Expand knowledge menu')}
			collapseAriaLabel={t('Collapse knowledge menu')}
			panel={<KnowledgeSidebar />}
		>
			{children}
		</BackPanelLayout>
	);
}
