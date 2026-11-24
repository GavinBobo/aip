// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import { instanceApiPath } from '@/lib/parsingInstances';
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

/** One stored parse run, as the 解析实例 list shows it. */
export type ParsingInstance = {
	id: string;
	file_name: string | null;
	source_name: string | null;
	created: string | null;
	page_num: number | null;
	processing_time_ms: number | null;
	has_markdown: boolean;
};

/** The same run with its answers, fetched when the detail view opens. */
export type ParsingInstanceDetail = {
	id: string;
	document: string;
	run: string;
	file_name: string | null;
	source_name: string | null;
	created: string | null;
	outputs: Record<string, unknown>;
	metadata: Record<string, unknown>;
};

export type ParsingProfile = {
	id: string;
	name: string;
	description: string | null;
	options: Record<string, unknown>;
	is_default: boolean;
};

export type ParsingTaskDocument = {
	id: string;
	file_name: string;
	source_name: string | null;
	instance_id: string | null;
	status: string;
	stage: string | null;
	progress_done: number;
	progress_total: number;
	progress_percent: number;
	page_count: number | null;
	processing_time_ms: number | null;
	error_code: string | null;
	error_message: string | null;
};

export type ParsingTask = {
	id: string;
	name: string;
	created_by: string | null;
	status: string;
	profile: string;
	options: Record<string, unknown>;
	total_documents: number;
	completed_documents: number;
	failed_documents: number;
	created: string | null;
	started: string | null;
	finished: string | null;
	documents: ParsingTaskDocument[];
	runs: {
		id: string;
		document_id: string;
		attempt: number;
		status: string;
		progress_done: number;
		progress_total: number;
		progress_percent: number;
		result_path: string | null;
		error_code: string | null;
		error_message: string | null;
		created: string | null;
		finished: string | null;
	}[];
};

export type ParsingRunSummary = {
	id: string;
	task_id: string;
	document_id: string;
	task_name: string | null;
	file_name: string | null;
	source_name: string | null;
	attempt: number;
	profile: string;
	status: string;
	stage: string | null;
	progress_done: number;
	progress_total: number;
	progress_percent: number;
	page_count: number | null;
	processing_time_ms: number | null;
	quality: Record<string, unknown>;
	error_code: string | null;
	error_message: string | null;
	reviewed: boolean;
	created: string | null;
	finished: string | null;
};

export type ParsingRunDetail = ParsingRunSummary & {
	instance_id: string | null;
	options: Record<string, unknown>;
	model_snapshot: Record<string, unknown>;
	layout_snapshot: Record<string, unknown>;
	pipeline_version: string | null;
	outputs: Record<string, unknown>;
	metadata: Record<string, unknown>;
	edits: Record<
		string,
		{
			content: string;
			format: string | null;
			edited_by: string | null;
			edited_at: string | null;
		}
	>;
	reviewed_by: string | null;
	reviewed_at: string | null;
	review_note: string | null;
};

export type ParsingHealth = {
	ok: boolean;
	backend: Record<string, unknown>;
	layout: Record<string, unknown>;
};

export type ParsingSourceEntry = {
	name: string;
	path: string;
	kind: 'directory' | 'file';
	size?: number;
	is_root?: boolean;
};

export type ParsingSourceListing = {
	roots: string[];
	path: string | null;
	parent: string | null;
	entries: ParsingSourceEntry[];
};

export type ParsingSourceScan = {
	path: string;
	count: number;
	limit: number;
	files: {
		name: string;
		path: string;
		relative: string;
		size: number;
	}[];
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

	/** Stored runs, newest first, without their (large) answers. */
	instances: (limit = 50) =>
		requests.get<{ data: ParsingInstance[]; count: number }>('parsing/instances', { limit }),

	instance: (id: string) => requests.get<{ data: ParsingInstanceDetail }>(instanceApiPath(id)),

	removeInstance: (id: string) => requests.delete<{ data: { id: string } }>(instanceApiPath(id)),

	/** Where the browser can fetch the stored source file from. */
	instanceSourceUrl: (id: string): string => `/api/${instanceApiPath(id)}/source`,

	/** Built-in fast/standard/accurate presets. */
	profiles: () => requests.get<{ data: ParsingProfile[]; count: number }>('parsing/profiles'),

	/** Probe both services. `ok` is the only trustworthy success flag. */
	health: () => requests.get<{ data: ParsingHealth }>('parsing/health'),

	/** Allowlisted Windows/server shared folders. */
	browseSources: (path?: string | null) =>
		requests.get<{ data: ParsingSourceListing }>(
			'parsing/sources',
			path == null || path === '' ? {} : { path },
		),

	/** Recursively find every PDF below one selected shared folder. */
	scanSources: (path: string) =>
		requests.post<{ data: ParsingSourceScan }>('parsing/sources/scan', { path }),

	/** Create one durable batch task from every PDF below the selected folder. */
	createTaskFromFolder: (input: {
		path: string;
		name?: string;
		profile: string;
		options: Record<string, unknown>;
		page_start?: number;
		page_end?: number;
	}) => requests.post<{ data: ParsingTask }>('parsing/tasks/from-folder', input),

	/** Create a durable batch task; the worker owns it from here. */
	createTask: (form: FormData) => requests.postForm<{ data: ParsingTask }>('parsing/tasks', form),

	tasks: (
		params: {
			limit?: number;
			offset?: number;
			status?: string;
			q?: string;
		} = {},
	) =>
		requests.get<{ data: ParsingTask[]; count: number; total: number }>(
			'parsing/tasks',
			params,
		),

	task: (id: string) =>
		requests.get<{ data: ParsingTask }>(`parsing/tasks/${encodeURIComponent(id)}`),

	deleteTask: (id: string) =>
		requests.delete<{ data: { id: string } }>(`parsing/tasks/${encodeURIComponent(id)}`),

	cancelTask: (id: string) =>
		requests.post<{ data: ParsingTask }>(`parsing/tasks/${encodeURIComponent(id)}/cancel`),

	retryDocument: (id: string) =>
		requests.post<{ data: ParsingTask }>(`parsing/documents/${encodeURIComponent(id)}/retry`),

	runs: (
		params: {
			limit?: number;
			offset?: number;
			status?: string;
			q?: string;
			reviewed?: boolean;
		} = {},
	) =>
		requests.get<{ data: ParsingRunSummary[]; count: number; total: number }>(
			'parsing/runs',
			params,
		),

	run: (id: string) =>
		requests.get<{ data: ParsingRunDetail }>(`parsing/runs/${encodeURIComponent(id)}`),

	previousRun: (id: string) =>
		requests.get<{ data: ParsingRunDetail | null }>(
			`parsing/runs/${encodeURIComponent(id)}/previous`,
		),

	updateBlocks: (id: string, blocks: Record<string, unknown>[]) =>
		requests.patch<{ data: ParsingRunDetail }>(
			`parsing/runs/${encodeURIComponent(id)}/blocks`,
			{ blocks },
		),

	review: (id: string, reviewed: boolean, note?: string) =>
		requests.post<{ data: ParsingRunDetail }>(`parsing/runs/${encodeURIComponent(id)}/review`, {
			reviewed,
			note,
		}),

	reparse: (id: string) =>
		requests.post<{ data: ParsingTask }>(`parsing/runs/${encodeURIComponent(id)}/reparse`),

	removeRun: (id: string) =>
		requests.delete<{ data: { id: string } }>(`parsing/runs/${encodeURIComponent(id)}`),

	runPageUrl: (id: string, page: number): string =>
		`/api/parsing/runs/${encodeURIComponent(id)}/page/${page}`,

	exportRunUrl: (id: string): string => `/api/parsing/runs/${encodeURIComponent(id)}/export`,
};
