// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';
import { getPrisma } from '@/lib/prisma';
import { PARSING_KEYS, type ParsingSettingsInput } from '@/lib/parsingConfigurations';

/** `configurations` key for each stored field of the form. */
const KEY_BY_FIELD: Record<Exclude<keyof ParsingSettingsInput, 'clear_vllm_api_key'>, string> = {
	mode: PARSING_KEYS.mode,
	vllm_url: PARSING_KEYS.vllmUrl,
	vllm_model: PARSING_KEYS.vllmModel,
	vllm_api_key: PARSING_KEYS.vllmApiKey,
	vllm_concurrency: PARSING_KEYS.vllmConcurrency,
	vllm_timeout: PARSING_KEYS.vllmTimeout,
	local_model_dir: PARSING_KEYS.localModelDir,
	local_host: PARSING_KEYS.localHost,
	local_port: PARSING_KEYS.localPort,
	local_threads: PARSING_KEYS.localThreads,
	local_dtype: PARSING_KEYS.localDtype,
	local_startup_timeout: PARSING_KEYS.localStartupTimeout,
	layout_url: PARSING_KEYS.layoutUrl,
	layout_batch_size: PARSING_KEYS.layoutBatchSize,
	layout_concurrency: PARSING_KEYS.layoutConcurrency,
	layout_timeout: PARSING_KEYS.layoutTimeout,
	layout_retry_times: PARSING_KEYS.layoutRetryTimes,
	layout_score_threshold: PARSING_KEYS.layoutScoreThreshold,
	layout_nms_iou: PARSING_KEYS.layoutNmsIou,
	layout_provides_reading_order: PARSING_KEYS.layoutProvidesReadingOrder,
	upload_dir: PARSING_KEYS.uploadDir,
	image_dir: PARSING_KEYS.imageDir,
};

// The settings page reads the *effective* values from the backend, which knows
// the defaults and masks the credential. Forwarding beats duplicating that
// resolution in two languages.
//
// The path is rewritten because reads and writes deliberately live in different
// places: writes belong to whoever owns `configurations` (Prisma, here), while
// the answer — defaults, masking, live state — belongs to the parser. Same URL
// for the browser, two different upstreams.
export const GET = withPermission({ catalog: ['edit'] })((req) =>
	proxyToBackend(
		new Request(new URL('/api/parsing/settings', new URL(req.url)), {
			method: 'GET',
			headers: req.headers,
		}),
	),
);

/**
 * Save the document-parsing settings.
 *
 * Written to the same `configurations` table as every other instance setting,
 * so it is covered by the existing backup and the existing "one row per key"
 * audit trail. The backend re-reads them on a 5 second cache, so a save takes
 * effect without a restart.
 */
export const PUT = withPermission({ catalog: ['edit'] })(async (req) => {
	let raw: unknown;
	try {
		raw = await req.json();
	} catch {
		return NextResponse.json({ error: 'Body must be JSON.' }, { status: 400 });
	}
	if (raw == null || typeof raw !== 'object') {
		return NextResponse.json({ error: 'Body must be an object.' }, { status: 400 });
	}

	const body = raw as Partial<ParsingSettingsInput>;
	const mode = body.mode;
	if (mode !== 'none' && mode !== 'vllm' && mode !== 'local') {
		return NextResponse.json(
			{ error: "mode must be 'none', 'vllm' or 'local'." },
			{ status: 400 },
		);
	}
	for (const field of ['vllm_url', 'layout_url'] as const) {
		const value = body[field];
		if (value != null && value !== '' && !/^https?:\/\//i.test(String(value))) {
			return NextResponse.json(
				{ error: `${field} must start with http:// or https://` },
				{ status: 400 },
			);
		}
	}

	const prisma = getPrisma();
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

	for (const [field, key] of Object.entries(KEY_BY_FIELD)) {
		const name = field as keyof ParsingSettingsInput;
		// The credential has its own rule: an empty field means "keep what is
		// stored", and clearing it is an explicit checkbox.
		if (name === 'vllm_api_key') continue;
		const value = body[name];
		if (value == null) continue;
		await putOrDelete(key, String(value));
	}

	if (body.vllm_api_key != null && body.vllm_api_key.trim() !== '') {
		await putOrDelete(PARSING_KEYS.vllmApiKey, body.vllm_api_key.trim());
	} else if (body.clear_vllm_api_key === true) {
		await putOrDelete(PARSING_KEYS.vllmApiKey, '');
	}

	return NextResponse.json({ ok: true });
});
