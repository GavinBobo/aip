// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';

import { publicAppUrl } from './publicUrl';

const requestFrom = (origin: string): Request => new Request(`${origin}/api/invitations`);

const previousAppUrl = process.env.APP_URL;

afterEach(() => {
	if (previousAppUrl === undefined) delete process.env.APP_URL;
	else process.env.APP_URL = previousAppUrl;
});

describe('publicAppUrl', () => {
	it('uses the request origin when APP_URL is unset', () => {
		delete process.env.APP_URL;
		expect(publicAppUrl(requestFrom('http://192.168.1.9:3010'))).toBe(
			'http://192.168.1.9:3010',
		);
	});

	it('keeps a configured public deployment origin', () => {
		process.env.APP_URL = 'https://ontology.example.com/';
		expect(publicAppUrl(requestFrom('http://127.0.0.1:3010'))).toBe(
			'https://ontology.example.com',
		);
	});

	it('prefers the request origin when APP_URL is only loopback', () => {
		process.env.APP_URL = 'http://localhost:3010';
		expect(publicAppUrl(requestFrom('http://192.168.1.9:3010'))).toBe(
			'http://192.168.1.9:3010',
		);
	});

	it('keeps loopback when the caller is also loopback', () => {
		process.env.APP_URL = 'http://localhost:3010';
		expect(publicAppUrl(requestFrom('http://127.0.0.1:3010'))).toBe('http://127.0.0.1:3010');
	});
});
