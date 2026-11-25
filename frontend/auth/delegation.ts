// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Delegated identity for trusted gateways (an MCP host, an agent platform).
//
// Some callers can name the person a request is for, but cannot present that
// person's SSO token or All Ontology API token. For those deployments a trusted
// gateway holds one shared delegation key and sends the subject alongside it:
//
//   x-all-ontology-delegation-key: <ALL_ONTOLOGY_DELEGATION_KEY>
//   x-all-ontology-subject: alice@example.com | <sso subject> | <user id>
//
// The key is the trust anchor and is equivalent to "may act as any user", so it
// lives only in the gateway's secret store and never reaches a browser. When it
// is not configured the headers are ignored entirely.
//
// Resolving the subject here rather than accepting a user id and a department
// list is deliberate: a caller that supplied departments could invent a
// membership and widen its own access. The gateway names a *person*; this
// module looks up that person, and the backend derives departments and zones
// from the authoritative store on every request.

import { timingSafeEqual } from 'node:crypto';

import type { ResolvedUser } from '@/auth/resolve-user';
import { getPrisma } from '@/lib/prisma';

export const DELEGATION_KEY_HEADER = 'x-all-ontology-delegation-key';
export const DELEGATION_SUBJECT_HEADER = 'x-all-ontology-subject';

/** A key short enough to guess must not enable impersonation. */
const MIN_KEY_LENGTH = 32;

/** `undefined` means "not a delegated request"; `null` means "delegation failed". */
export type DelegationResult = ResolvedUser | null | undefined;

const configuredKey = (): string => {
	const key = (process.env.ALL_ONTOLOGY_DELEGATION_KEY ?? '').trim();
	if (key && key.length < MIN_KEY_LENGTH) {
		console.warn(
			`[delegation] ALL_ONTOLOGY_DELEGATION_KEY is shorter than ${MIN_KEY_LENGTH} characters; ignoring it.`,
		);
		return '';
	}
	return key;
};

const keysMatch = (expected: string, presented: string): boolean => {
	const left = Buffer.from(expected);
	const right = Buffer.from(presented);
	return left.length === right.length && timingSafeEqual(left, right);
};

const stripPrefix = (value: string, prefix: string): string | null =>
	value.toLowerCase().startsWith(prefix) ? value.slice(prefix.length).trim() : null;

/**
 * Resolve a delegated subject to an All Ontology user.
 *
 * Accepted spellings, in order: an explicit `email:` / `sso:` / `id:` prefix,
 * then a bare value tried as email, SSO subject, and finally user id. SSO
 * subjects are what an IdP puts in the `sub` claim (Better Auth stores that as
 * `account.accountId`), so an agent platform that already knows its users by
 * subject does not need a second mapping table.
 */
const findUser = async (subject: string) => {
	const prisma = getPrisma();
	const select = { id: true, role: true, banned: true } as const;

	const email = stripPrefix(subject, 'email:');
	if (email) {
		return prisma.user.findUnique({ where: { email }, select });
	}

	const sso = stripPrefix(subject, 'sso:');
	if (sso) {
		const account = await prisma.account.findFirst({
			where: { accountId: sso },
			select: { user: { select } },
		});
		return account?.user ?? null;
	}

	const id = stripPrefix(subject, 'id:');
	if (id) {
		return prisma.user.findUnique({ where: { id }, select });
	}

	const byEmail = await prisma.user.findUnique({ where: { email: subject }, select });
	if (byEmail) return byEmail;

	const bySubject = await prisma.account.findFirst({
		where: { accountId: subject },
		select: { user: { select } },
	});
	if (bySubject?.user) return bySubject.user;

	return prisma.user.findUnique({ where: { id: subject }, select });
};

/**
 * Read and verify delegated identity headers, if they are present.
 *
 * An invalid key or unknown subject is a hard failure (`null`) rather than a
 * fall-through to other credential paths: silently treating a mistyped
 * delegation as anonymous would turn a gateway misconfiguration into a
 * confusing 401 somewhere else.
 */
export async function resolveDelegatedUser(requestHeaders: Headers): Promise<DelegationResult> {
	const presentedKey = (requestHeaders.get(DELEGATION_KEY_HEADER) ?? '').trim();
	const subject = (requestHeaders.get(DELEGATION_SUBJECT_HEADER) ?? '').trim();
	if (!presentedKey && !subject) return undefined;

	const expectedKey = configuredKey();
	if (!expectedKey || !presentedKey || !subject) return null;
	if (!keysMatch(expectedKey, presentedKey)) return null;

	const user = await findUser(subject);
	if (!user || user.banned) return null;

	// One line per delegated request: the key is never logged, and the pair is
	// what an audit needs to explain why a request saw another person's data.
	console.info(`[delegation] subject=${subject} -> user=${user.id}`);
	return { id: user.id, role: user.role };
}
