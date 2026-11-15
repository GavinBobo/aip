// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * `configurations` keys owned by the document-parsing feature.
 *
 * These mirror `auto_ontology/parsing/settings.py` one for one. The backend
 * reads them straight from the table on a short cache; this file exists so the
 * Next route handler writes the same names rather than string literals.
 */
export const PARSING_KEYS = {
	mode: 'parsing_mode',
	vllmUrl: 'parsing_vllm_url',
	vllmModel: 'parsing_vllm_model',
	vllmApiKey: 'parsing_vllm_api_key',
	vllmConcurrency: 'parsing_vllm_concurrency',
	vllmTimeout: 'parsing_vllm_timeout',
	localModelDir: 'parsing_local_model_dir',
	localHost: 'parsing_local_host',
	localPort: 'parsing_local_port',
	localThreads: 'parsing_local_threads',
	localDtype: 'parsing_local_dtype',
	localStartupTimeout: 'parsing_local_startup_timeout',
	layoutUrl: 'parsing_layout_url',
	layoutBatchSize: 'parsing_layout_batch_size',
	layoutConcurrency: 'parsing_layout_concurrency',
	layoutTimeout: 'parsing_layout_timeout',
	layoutRetryTimes: 'parsing_layout_retry_times',
	layoutScoreThreshold: 'parsing_layout_score_threshold',
	layoutNmsIou: 'parsing_layout_nms_iou',
	layoutProvidesReadingOrder: 'parsing_layout_provides_reading_order',
	uploadDir: 'parsing_upload_dir',
	imageDir: 'parsing_image_dir',
} as const;

export type ParsingMode = 'none' | 'vllm' | 'local';

export type ParsingSettingsInput = {
	mode: ParsingMode;
	vllm_url: string;
	vllm_model: string;
	/** Only sent when the user typed a new one; empty keeps the stored key. */
	vllm_api_key?: string;
	clear_vllm_api_key?: boolean;
	vllm_concurrency: number;
	vllm_timeout: number;
	local_model_dir: string;
	local_host: string;
	local_port: number;
	local_threads: number;
	local_dtype: 'float32' | 'bfloat16';
	local_startup_timeout: number;
	layout_url: string;
	layout_batch_size: number;
	layout_concurrency: number;
	layout_timeout: number;
	layout_retry_times: number;
	layout_score_threshold: number;
	layout_nms_iou: number;
	layout_provides_reading_order: boolean;
	/** Where the uploaded source files are kept. Empty means the default. */
	upload_dir: string;
	/** Where extracted pictures are written. Empty means the default. */
	image_dir: string;
};
