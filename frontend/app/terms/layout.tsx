// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';

import { requireUser } from '@/auth/auth-guards';

export const metadata: Metadata = {
	title: 'Terms',
};

/**
 * The middleware only checks that a session cookie exists; a stale or rotated
 * one passes it. Every page tree therefore needs this authoritative guard, or
 * the page shell renders for a caller who is not signed in (see
 * `lib/route-guards.test.ts`, which enforces the rule across the app).
 */
export default async function TermsLayout({ children }: { children: React.ReactNode }) {
	await requireUser();
	return children;
}
