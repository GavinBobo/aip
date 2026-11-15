// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Suspense } from 'react';

import { Spinner } from '@/common/Spinner';
import { ErdView } from '@/components/erdPage';
import { t } from '@/i18n';

export default function ErdPage() {
	return (
		<Suspense
			fallback={
				<div
					className="flex h-full items-center justify-center"
					role="status"
					aria-label={t('Loading ER canvas')}
				>
					<Spinner />
				</div>
			}
		>
			<ErdView />
		</Suspense>
	);
}
