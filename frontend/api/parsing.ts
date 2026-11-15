// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ParsingMode, ParsingSettingsInput } from '@/lib/parsingConfigurations';

/** The three groups `model_backend.describe()` reports. */
export type ParsingBackendDescription = {
	mode: ParsingMode;
	local: {
		model_dir: string;
		python: string | null;
		host: string;
		port: number;
		threads: number;
		dtype: 'float32' | 'bfloat16';
		startup_timeout: number;
		max_tokens: number;
	};
	vllm: {
		url: string;
		model_name: string;
		/** Always null: the stored key never leaves the server. */
		api_key: string | null;
		api_key_configured: boolean;
		max_concurrency: number;
		timeout: number;
		connect_timeout: number;
		retry_times: number;
	};
	layout: {
		url: string;
		batch_size: number;
		max_concurrency: number;
		timeout: number;
		retry_times: number;
		score_threshold: number;
		nms_iou_threshold: number | null;
		provides_reading_order: boolean;
	};
	status: {
		state: string;
		detail: string;
		error: string | null;
		ready: boolean;
		active_url: string | null;
		model_name: string;
		pid: number | null;
		log_path: string;
	};
	ready: boolean;
	model_url: string | null;
	layout_url: string | null;
	instance: string;
	/** Absolute paths the parser writes to, as the backend resolved them. */
	paths: {
		upload_dir: string;
		image_dir: string;
		image_url_prefix: string;
	};
};

export type ParsingCapabilities = {
	mode: ParsingMode;
	state: string;
	detail: string | null;
	error: string | null;
	model_url: string | null;
	layout_url: string | null;
	ready: boolean;
	output_formats: string[];
	element_formats: Record<string, string[]>;
	element_format_defaults: Record<string, string>;
	model_options: string[];
};

export type ParsedDocument = {
	file_name: string;
	outputs: Record<string, unknown>;
	metadata: Record<string, unknown>;
};

export type ParsingJob = {
	task_id: string;
	status: 'queuing' | 'processing' | 'success' | 'failed';
	instance: string | null;
	file_name: string | null;
	result: { file_name: string; outputs: Record<string, unknown> } | null;
	error: string | null;
	metadata: Record<string, unknown>;
};

export const parsingApi = {
	capabilities: () => requests.get<{ data: ParsingCapabilities }>('parsing/capabilities'),

	/** Effective parsing settings, credential masked (Settings > 模型设置). */
	settings: () => requests.get<{ data: ParsingBackendDescription }>('configurations/parsing'),

	saveSettings: (input: ParsingSettingsInput) =>
		requests.put<{ ok: boolean }>('configurations/parsing', input),

	testBackend: (config?: Record<string, unknown>) =>
		requests.post<{ data: Record<string, unknown> }>('parsing/backends/test', config ?? {}),

	testLayout: (config?: Record<string, unknown>) =>
		requests.post<{ data: Record<string, unknown> }>('parsing/layout/test', config ?? {}),

	/** Parse one document and wait. multipart, so it goes through `postForm`. */
	parse: (form: FormData) =>
		requests.postForm<{ data: ParsedDocument }>('parsing/documents', form),

	submit: (form: FormData) => requests.postForm<{ data: ParsingJob }>('parsing/jobs', form),

	job: (taskId: string) =>
		requests.get<{ data: ParsingJob }>(`parsing/jobs/${encodeURIComponent(taskId)}`),
};
