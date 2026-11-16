// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { auth } from '@/auth/auth';
import { Role } from '@/enums/auth';

/** Authoritative session lookup for server components and route handlers. */
export const getCurrentSession = async () => auth.api.getSession({ headers: await headers() });

/**
 * Require any authenticated user; redirect to /login otherwise.
 *
 * The redirect carries `next` when the middleware recorded the requested path
 * (`x-all-ontology-pathname`), so a session that expires mid-session returns
 * the caller to the page they were on rather than dropping them at /chat.
 */
export const requireUser = async () => {
	const session = await getCurrentSession();
	if (!session) {
		const requestedPath = (await headers()).get('x-all-ontology-pathname');
		redirect(requestedPath ? `/login?next=${encodeURIComponent(requestedPath)}` : '/login');
	}
	return session;
};

/**
 * Require an admin. This is the real authorization gate — proxy.ts only does an
 * optimistic cookie-presence check and cannot read the role.
 */
export const requireAdmin = async () => {
	const session = await requireUser();
	if (session.user.role !== Role.Admin) redirect('/chat');
	return session;
};
