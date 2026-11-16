// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { requireUser } from '@/auth/auth-guards';
import { BackPanelLayout } from '@/common/BackPanelLayout';
import { ParsingNav } from '@/components/parsingPage/ParsingNav';
import { t } from '@/i18n';

export const metadata: Metadata = {
	title: 'Document Parsing',
};

// The section menu matches Settings': parsing has grown from one form into two
// destinations — the runs it has kept, and the batch form that makes new ones.
export default async function ParsingLayout({ children }: { children: React.ReactNode }) {
	await requireUser();
	return (
		<BackPanelLayout
			panelAriaLabel={t('Document parsing sections')}
			expandAriaLabel={t('Expand parsing menu')}
			collapseAriaLabel={t('Collapse parsing menu')}
			panel={<ParsingNav />}
		>
			{children}
		</BackPanelLayout>
	);
}
