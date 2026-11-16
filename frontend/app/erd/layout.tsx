// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { requireUser } from '@/auth/auth-guards';

export const metadata: Metadata = {
	title: 'ER Model',
};

export default async function ErdLayout({ children }: { children: React.ReactNode }) {
	await requireUser();
	return children;
}
