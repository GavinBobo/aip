// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const prisma = vi.hoisted(() => ({
	user: { findUnique: vi.fn() },
	account: { findFirst: vi.fn() },
}));

vi.mock('@/lib/prisma', () => ({ getPrisma: () => prisma }));

import { resolveDelegatedUser } from '@/auth/delegation';

const KEY = 'k'.repeat(40);

const headers = (values: Record<string, string>): Headers => new Headers(values);

describe('resolveDelegatedUser', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		process.env.ALL_ONTOLOGY_DELEGATION_KEY = KEY;
	});

	afterEach(() => {
		delete process.env.ALL_ONTOLOGY_DELEGATION_KEY;
	});

	it('is not a delegated request without the headers', async () => {
		await expect(resolveDelegatedUser(headers({}))).resolves.toBeUndefined();
	});

	it('resolves an email subject once the key matches', async () => {
		prisma.user.findUnique.mockResolvedValue({ id: 'u1', role: 'viewer', banned: false });

		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': KEY,
					'x-all-ontology-subject': 'alice@example.com',
				}),
			),
		).resolves.toEqual({ id: 'u1', role: 'viewer' });
		expect(prisma.user.findUnique).toHaveBeenCalledWith({
			where: { email: 'alice@example.com' },
			select: { id: true, role: true, banned: true },
		});
	});

	it('resolves an SSO subject through the linked account', async () => {
		prisma.account.findFirst.mockResolvedValue({
			user: { id: 'u2', role: 'admin', banned: false },
		});

		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': KEY,
					'x-all-ontology-subject': 'sso:sub-123',
				}),
			),
		).resolves.toEqual({ id: 'u2', role: 'admin' });
		expect(prisma.account.findFirst).toHaveBeenCalledWith(
			expect.objectContaining({ where: { accountId: 'sub-123' } }),
		);
	});

	it('rejects a wrong key instead of falling through', async () => {
		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': 'wrong',
					'x-all-ontology-subject': 'alice@example.com',
				}),
			),
		).resolves.toBeNull();
		expect(prisma.user.findUnique).not.toHaveBeenCalled();
	});

	it('rejects a subject while delegation is disabled', async () => {
		delete process.env.ALL_ONTOLOGY_DELEGATION_KEY;

		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': KEY,
					'x-all-ontology-subject': 'alice@example.com',
				}),
			),
		).resolves.toBeNull();
	});

	it('ignores a configured key that is too short to be secret', async () => {
		process.env.ALL_ONTOLOGY_DELEGATION_KEY = 'short-key';

		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': 'short-key',
					'x-all-ontology-subject': 'alice@example.com',
				}),
			),
		).resolves.toBeNull();
		expect(prisma.user.findUnique).not.toHaveBeenCalled();
	});

	it('rejects an unknown or banned user', async () => {
		prisma.user.findUnique.mockResolvedValue(null);
		prisma.account.findFirst.mockResolvedValue(null);

		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': KEY,
					'x-all-ontology-subject': 'ghost@example.com',
				}),
			),
		).resolves.toBeNull();

		prisma.user.findUnique.mockResolvedValue({
			id: 'u3',
			role: 'viewer',
			banned: true,
		});
		await expect(
			resolveDelegatedUser(
				headers({
					'x-all-ontology-delegation-key': KEY,
					'x-all-ontology-subject': 'banned@example.com',
				}),
			),
		).resolves.toBeNull();
	});
});
