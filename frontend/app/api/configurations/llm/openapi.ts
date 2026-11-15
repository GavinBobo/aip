// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { z } from 'zod';
import type { OpenApiRoute } from '@/types/openapi';

const sourceSchema = z.enum(['saved', 'environment', 'unset']);

export const llmSettingsSchema = z.object({
	base_url: z.string(),
	base_url_source: sourceSchema,
	model: z.string(),
	model_source: sourceSchema,
	api_key_configured: z.boolean(),
	api_key_source: sourceSchema,
	api_key_hint: z.string().nullable(),
});

const optionalUrl = z.string().trim().max(2048);

export const llmSettingsBody = z
	.object({
		base_url: optionalUrl,
		model: z.string().trim().max(512),
		api_key: z.string().max(8192).optional(),
		clear_api_key: z.boolean().optional(),
	})
	.superRefine((value, ctx) => {
		if (value.base_url === '') return;
		if (!/^https?:\/\//i.test(value.base_url)) {
			ctx.addIssue({
				code: 'custom',
				path: ['base_url'],
				message: 'Base URL must start with http:// or https://.',
			});
		}
	});

export const openapi: OpenApiRoute = {
	get: {
		responses: {
			200: {
				description:
					'The effective conversational LLM endpoint/model and whether a credential is configured. The API key itself is never returned.',
				schema: llmSettingsSchema,
			},
		},
	},
	put: {
		body: {
			description:
				'Save the conversational LLM endpoint, model, and optional API key. Blank endpoint/model values remove that override. A blank API key keeps the stored one unless `clear_api_key` is true.',
			schema: llmSettingsBody,
		},
		responses: {
			200: { description: 'The saved effective settings.', schema: llmSettingsSchema },
			400: { description: 'Body is not JSON, or a field is invalid.' },
		},
	},
};
