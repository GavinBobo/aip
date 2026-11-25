// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Resolve the All Ontology user behind a request, for handlers that accept both browser
// and service callers.
//
// Five identities are accepted, in order:
//   0. A trusted gateway's delegated subject (`x-all-ontology-delegation-key`
//      plus `x-all-ontology-subject` — see auth/delegation.ts). Off unless
//      ALL_ONTOLOGY_DELEGATION_KEY is configured.
//   1. A Better Auth session cookie (browser).
//   2. An All Ontology API token, `x-api-key: all_ontology_...` (scripts, CI — see auth/api-token.ts).
//      Checked before the SSO bearer because both may arrive as `Authorization:
//      Bearer`, and only the API-token path recognises the `all_ontology_` prefix.
//   3. An All Ontology-issued OAuth access token (an MCP client whose user signed in
//      through All Ontology — see auth/oauth-token.ts). Opaque like an API token, so it
//      is checked after that path has claimed the `all_ontology_` prefix.
//   4. An SSO id token (e.g. AI-Q), which authenticates with the same NVIDIA SSO
//      identity but has no All Ontology session, so it is mapped to the All Ontology user sharing
//      the token's email, falling back to the SSO account link by subject.

import { headers } from 'next/headers';
import { getCurrentSession } from '@/auth/auth-guards';
import { extractApiToken, verifyApiToken } from '@/auth/api-token';
import { extractOAuthToken, verifyOAuthToken } from '@/auth/oauth-token';
import { verifyBearer } from '@/auth/bearer';
import { resolveDelegatedUser } from '@/auth/delegation';
import { getPrisma } from '@/lib/prisma';

export type ResolvedUser = { id: string; role: string | null };

/**
 * Resolve the All Ontology user behind the current request — from the session cookie, a
 * All Ontology API token, an All Ontology-issued OAuth access token, or a verified SSO bearer token
 * (matched by email, then by SSO account subject). Returns null when the caller
 * is unauthenticated or has no matching All Ontology user. This is the single entry point
 * browser, script, and service callers all go through, so every protected API
 * accepts any of the four credentials.
 */
export async function resolveUser(): Promise<ResolvedUser | null> {
	const session = await getCurrentSession();
	if (session?.user.id) return { id: session.user.id, role: session.user.role ?? null };

	const requestHeaders = await headers();

	// A trusted gateway may name the person the request is for (see
	// auth/delegation.ts). Checked before the credential paths because a
	// delegated request deliberately carries no user credential of its own;
	// `null` is a hard rejection rather than a fall-through.
	const delegated = await resolveDelegatedUser(requestHeaders);
	if (delegated !== undefined) return delegated;

	// An All Ontology token is unambiguous, so presenting one settles which credential is
	// being offered: a revoked or expired token is a 401, not an invitation to
	// try it again as an SSO id token (which would only log a confusing "not a
	// decodable JWT" on the way to the same answer).
	if (extractApiToken(requestHeaders)) return verifyApiToken(requestHeaders);

	// Likewise settled by shape: an opaque bearer cannot be an SSO id token, so
	// there is nothing to fall through to.
	if (extractOAuthToken(requestHeaders)) return verifyOAuthToken(requestHeaders);

	const principal = await verifyBearer(requestHeaders);
	if (!principal) return null;

	const prisma = getPrisma();

	if (principal.email) {
		const user = await prisma.user.findFirst({
			where: { email: principal.email },
			select: { id: true, role: true },
		});
		if (user) return { id: user.id, role: user.role };
	}

	if (principal.subject) {
		const account = await prisma.account.findFirst({
			where: { accountId: principal.subject },
			select: { user: { select: { id: true, role: true } } },
		});
		if (account?.user) return { id: account.user.id, role: account.user.role };
	}

	return null;
}

/**
 * Convenience wrapper returning just the resolved user id (or null). See
 * {@link resolveUser}.
 */
export async function resolveUserId(): Promise<string | null> {
	return (await resolveUser())?.id ?? null;
}
