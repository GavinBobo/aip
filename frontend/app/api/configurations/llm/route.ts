// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { getPrisma } from '@/lib/prisma';
import { LLM_API_KEY_KEY, LLM_BASE_URL_KEY, LLM_MODEL_KEY } from '@/lib/configurations';
import { withPermission } from '@/auth/with-auth';
import { llmSettingsBody } from './openapi';

type Source = 'saved' | 'environment' | 'unset';

const KEYS = [LLM_BASE_URL_KEY, LLM_API_KEY_KEY, LLM_MODEL_KEY] as const;

function firstEnvironment(...names: string[]): string {
	for (const name of names) {
		const value = process.env[name]?.trim();
		if (value) return value;
	}
	return '';
}

function maskKey(value: string): string {
	const trimmed = value.trim();
	if (trimmed === '') return '';
	return trimmed.length <= 4 ? '••••' : `••••${trimmed.slice(-4)}`;
}

async function readSettings() {
	const rows = await getPrisma().configuration.findMany({
		where: { key: { in: [...KEYS] } },
	});
	const stored = Object.fromEntries(rows.map((row) => [row.key, row.value]));

	const envBaseUrl = firstEnvironment(
		'REASONING_ENDPOINT',
		'NON_REASONING_ENDPOINT',
		'DEFAULT_MODELS_ENDPOINT',
		'BASE_URL',
	);
	const envModel = firstEnvironment(
		'REASONING_MODEL',
		'NON_REASONING_MODEL',
		'DEFAULT_MODELS_MODEL',
		'MODEL_NAME',
	);
	const envApiKey = firstEnvironment(
		'REASONING_API_KEY',
		'NON_REASONING_API_KEY',
		'DEFAULT_MODELS_API_KEY',
		'NVIDIA_API_KEY',
	);

	const savedBaseUrl = stored[LLM_BASE_URL_KEY]?.trim() ?? '';
	const savedModel = stored[LLM_MODEL_KEY]?.trim() ?? '';
	const savedApiKey = stored[LLM_API_KEY_KEY]?.trim() ?? '';
	const baseUrlSource: Source = savedBaseUrl ? 'saved' : envBaseUrl ? 'environment' : 'unset';
	const modelSource: Source = savedModel ? 'saved' : envModel ? 'environment' : 'unset';
	const apiKeySource: Source = savedApiKey ? 'saved' : envApiKey ? 'environment' : 'unset';

	return {
		base_url: savedBaseUrl || envBaseUrl,
		base_url_source: baseUrlSource,
		model: savedModel || envModel,
		model_source: modelSource,
		api_key_configured: savedApiKey !== '' || envApiKey !== '',
		api_key_source: apiKeySource,
		api_key_hint: savedApiKey ? maskKey(savedApiKey) : null,
	};
}

// Report the effective conversational LLM settings for Settings > LLM Settings.
// The credential is represented by a source and a masked hint only.
export const GET = withPermission({ catalog: ['edit'] })(async () => {
	return NextResponse.json(await readSettings());
});

// Save the conversational LLM endpoint/model/key (admin-only).
export const PUT = withPermission({ catalog: ['edit'] })(async (req) => {
	let raw: unknown;
	try {
		raw = await req.json();
	} catch {
		return NextResponse.json({ error: 'Body must be JSON.' }, { status: 400 });
	}

	const parsed = llmSettingsBody.safeParse(raw);
	if (!parsed.success) {
		return NextResponse.json(
			{ error: parsed.error.issues[0]?.message ?? 'Invalid LLM settings.' },
			{ status: 400 },
		);
	}

	const prisma = getPrisma();
	const { base_url, model, api_key, clear_api_key } = parsed.data;

	const putOrDelete = async (key: string, value: string): Promise<void> => {
		if (value === '') {
			await prisma.configuration.deleteMany({ where: { key } });
			return;
		}
		await prisma.configuration.upsert({
			where: { key },
			create: { key, value },
			update: { value },
		});
	};

	await putOrDelete(LLM_BASE_URL_KEY, base_url);
	await putOrDelete(LLM_MODEL_KEY, model);

	if (api_key != null && api_key.trim() !== '') {
		await putOrDelete(LLM_API_KEY_KEY, api_key.trim());
	} else if (clear_api_key === true) {
		await putOrDelete(LLM_API_KEY_KEY, '');
	}

	return NextResponse.json(await readSettings());
});
