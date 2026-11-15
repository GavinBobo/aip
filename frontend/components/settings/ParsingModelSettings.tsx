// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';

import { parsingApi, type ParsingBackendDescription } from '@/api/parsing';
import { Button } from '@/common/Button';
import { Toast } from '@/common/Toast';
import { ButtonTheme, Size } from '@/enums/button';
import { ToastVariant } from '@/enums/toast';
import { t } from '@/i18n';
import type { ParsingMode } from '@/lib/parsingConfigurations';

const fieldClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 disabled:cursor-not-allowed disabled:bg-zinc-100 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300 dark:disabled:bg-zinc-800/50';
const labelClassName = 'flex flex-col gap-1.5';
const captionClassName = 'text-[11px] leading-snug text-secondary dark:text-zinc-400';

type Form = {
	mode: ParsingMode;
	vllm_url: string;
	vllm_model: string;
	vllm_api_key: string;
	vllm_concurrency: string;
	vllm_timeout: string;
	local_model_dir: string;
	local_host: string;
	local_port: string;
	local_threads: string;
	local_dtype: 'float32' | 'bfloat16';
	local_startup_timeout: string;
	layout_url: string;
	layout_batch_size: string;
	layout_concurrency: string;
	layout_timeout: string;
	layout_retry_times: string;
	layout_score_threshold: string;
	layout_nms_iou: string;
	layout_provides_reading_order: boolean;
	upload_dir: string;
	image_dir: string;
};

const emptyForm: Form = {
	mode: 'none',
	vllm_url: '',
	vllm_model: '',
	vllm_api_key: '',
	vllm_concurrency: '',
	vllm_timeout: '',
	local_model_dir: '',
	local_host: '',
	local_port: '',
	local_threads: '',
	local_dtype: 'float32',
	local_startup_timeout: '',
	layout_url: '',
	layout_batch_size: '',
	layout_concurrency: '',
	layout_timeout: '',
	layout_retry_times: '',
	layout_score_threshold: '',
	layout_nms_iou: '',
	layout_provides_reading_order: false,
	upload_dir: '',
	image_dir: '',
};

const fromDescription = (description: ParsingBackendDescription): Form => ({
	mode: description.mode,
	vllm_url: description.vllm.url,
	vllm_model: description.vllm.model_name,
	vllm_api_key: '',
	vllm_concurrency: String(description.vllm.max_concurrency),
	vllm_timeout: String(description.vllm.timeout),
	local_model_dir: description.local.model_dir,
	local_host: description.local.host,
	local_port: String(description.local.port),
	local_threads: String(description.local.threads),
	local_dtype: description.local.dtype,
	local_startup_timeout: String(description.local.startup_timeout),
	layout_url: description.layout.url,
	layout_batch_size: String(description.layout.batch_size),
	layout_concurrency: String(description.layout.max_concurrency),
	layout_timeout: String(description.layout.timeout),
	layout_retry_times: String(description.layout.retry_times),
	layout_score_threshold: String(description.layout.score_threshold),
	layout_nms_iou: String(description.layout.nms_iou_threshold ?? 0.6),
	layout_provides_reading_order: description.layout.provides_reading_order,
	upload_dir: description.paths.upload_dir,
	image_dir: description.paths.image_dir,
});

const asNumber = (value: string, fallback: number): number => {
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : fallback;
};

export const ParsingModelSettings = () => {
	const [description, setDescription] = useState<ParsingBackendDescription | null>(null);
	const [form, setForm] = useState<Form>(emptyForm);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState<'backend' | 'layout' | null>(null);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [toast, setToast] = useState<{ message: string; variant: ToastVariant } | null>(null);

	useEffect(() => {
		// Same shape as the LLM form above: one fetch on mount, ignored if the
		// panel unmounts first. Reading through `.then` (rather than awaiting in
		// an async effect body) is what the `set-state-in-effect` rule asks for.
		let cancelled = false;
		parsingApi.settings().then((response) => {
			if (cancelled) return;
			setLoading(false);
			if (response.error || !response.data) {
				setLoadError(response.message ?? t('Failed to load parsing settings.'));
				return;
			}
			setDescription(response.data);
			setForm(fromDescription(response.data));
		});
		return () => {
			cancelled = true;
		};
	}, []);

	/** Re-read after a save, so the panel shows the state the backend settled on. */
	const reload = () => {
		parsingApi.settings().then((response) => {
			if (response.error || !response.data) return;
			setDescription(response.data);
			setForm(fromDescription(response.data));
		});
	};

	const patch = (next: Partial<Form>) => setForm((current) => ({ ...current, ...next }));

	const handleSave = async () => {
		if (saving || form.mode === 'none') {
			if (form.mode === 'none') {
				setToast({
					message: t('Choose a recognition backend before saving.'),
					variant: ToastVariant.Error,
				});
			}
			return;
		}
		if (form.vllm_url !== '' && !/^https?:\/\//i.test(form.vllm_url)) {
			setToast({
				message: t('The vLLM URL must start with http:// or https://.'),
				variant: ToastVariant.Error,
			});
			return;
		}

		setSaving(true);
		const response = await parsingApi.saveSettings({
			mode: form.mode,
			vllm_url: form.vllm_url.trim(),
			vllm_model: form.vllm_model.trim(),
			...(form.vllm_api_key.trim() === '' ? {} : { vllm_api_key: form.vllm_api_key.trim() }),
			vllm_concurrency: asNumber(form.vllm_concurrency, 16),
			vllm_timeout: asNumber(form.vllm_timeout, 300),
			local_model_dir: form.local_model_dir.trim(),
			local_host: form.local_host.trim(),
			local_port: asNumber(form.local_port, 8080),
			local_threads: asNumber(form.local_threads, 0),
			local_dtype: form.local_dtype,
			local_startup_timeout: asNumber(form.local_startup_timeout, 900),
			layout_url: form.layout_url.trim(),
			layout_batch_size: asNumber(form.layout_batch_size, 8),
			layout_concurrency: asNumber(form.layout_concurrency, 2),
			layout_timeout: asNumber(form.layout_timeout, 120),
			layout_retry_times: asNumber(form.layout_retry_times, 3),
			layout_score_threshold: asNumber(form.layout_score_threshold, 0.5),
			layout_nms_iou: asNumber(form.layout_nms_iou, 0.6),
			layout_provides_reading_order: form.layout_provides_reading_order,
			upload_dir: form.upload_dir.trim(),
			image_dir: form.image_dir.trim(),
		});
		setSaving(false);

		if (response.error) {
			setToast({
				message: response.message ?? t('Failed to save parsing settings.'),
				variant: ToastVariant.Error,
			});
			return;
		}
		setToast({ message: t('Parsing settings saved.'), variant: ToastVariant.Success });
		// The backend applies a change within a few seconds; re-reading shows the
		// state it settled on rather than the one we hoped for.
		reload();
	};

	const test = async (which: 'backend' | 'layout') => {
		setTesting(which);
		const config =
			which === 'backend'
				? {
						mode: form.mode,
						vllm: {
							url: form.vllm_url.trim(),
							model_name: form.vllm_model.trim(),
							max_concurrency: asNumber(form.vllm_concurrency, 16),
							timeout: asNumber(form.vllm_timeout, 300),
						},
						layout: { url: form.layout_url.trim() },
					}
				: {
						url: form.layout_url.trim(),
						batch_size: asNumber(form.layout_batch_size, 8),
						max_concurrency: asNumber(form.layout_concurrency, 2),
						timeout: asNumber(form.layout_timeout, 120),
						retry_times: asNumber(form.layout_retry_times, 3),
						score_threshold: asNumber(form.layout_score_threshold, 0.5),
						nms_iou_threshold: asNumber(form.layout_nms_iou, 0.6),
						provides_reading_order: form.layout_provides_reading_order,
					};
		const response =
			which === 'backend'
				? await parsingApi.testBackend(config)
				: await parsingApi.testLayout(config);
		setTesting(null);

		const data = response.data as Record<string, unknown> | undefined;
		const ok = data != null && (data.ok === undefined ? !response.error : data.ok !== false);
		setToast({
			message: ok
				? t('Connection succeeded.')
				: String(
						(data?.detail as string | undefined) ??
							response.message ??
							t('Connection failed.'),
					),
			variant: ok ? ToastVariant.Success : ToastVariant.Error,
		});
	};

	const status = description?.status;

	return (
		<section className="space-y-5 rounded-lg border border-zinc-200/90 bg-white/90 p-5 shadow-sm ring-1 ring-zinc-950/[0.04] dark:border-zinc-700/90 dark:bg-zinc-950/50 dark:ring-white/[0.06]">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
						{t('Document parsing')}
					</h2>
					<p className="mt-1 max-w-2xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'The parser needs two endpoints: a recognition model (vLLM, or the bundled local gateway) and the layout-analysis service. Changes take effect within a few seconds — no restart.',
						)}
					</p>
				</div>
				{status != null && (
					<span
						className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
							description?.ready
								? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
								: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
						}`}
					>
						{t(status.state)}
					</span>
				)}
			</div>

			{loadError != null ? (
				<div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{loadError}
				</div>
			) : (
				<>
					{status?.detail != null && status.detail !== '' && (
						// The backend's state strings are English product copy; the
						// dictionary translates the ones it knows and lets the rest
						// through unchanged.
						<p className={captionClassName}>{t(status.detail)}</p>
					)}

					<div className="grid gap-4 sm:grid-cols-2">
						<label className={labelClassName}>
							<span className="text-sm font-medium text-heading dark:text-zinc-100">
								{t('Recognition backend')}
							</span>
							<select
								value={form.mode}
								disabled={loading || saving}
								onChange={(event) =>
									patch({ mode: event.target.value as ParsingMode })
								}
								className={fieldClassName}
							>
								<option value="none">{t('Not configured')}</option>
								<option value="vllm">vLLM (OpenAI-compatible)</option>
								<option value="local">{t('Local model gateway')}</option>
							</select>
						</label>
					</div>

					{form.mode === 'vllm' && (
						<div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
							<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
								vLLM
							</h3>
							<div className="grid gap-4 sm:grid-cols-2">
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Base URL')}</span>
									<input
										value={form.vllm_url}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ vllm_url: event.target.value })
										}
										placeholder="http://127.0.0.1:8080/v1"
										spellCheck={false}
										className={`${fieldClassName} font-mono`}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Model name')}</span>
									<input
										value={form.vllm_model}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ vllm_model: event.target.value })
										}
										placeholder="oxr"
										spellCheck={false}
										className={`${fieldClassName} font-mono`}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('API key')}</span>
									<input
										type="password"
										value={form.vllm_api_key}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ vllm_api_key: event.target.value })
										}
										placeholder={
											description?.vllm.api_key_configured
												? t('Saved — leave blank to keep it')
												: t('Optional bearer token')
										}
										autoComplete="new-password"
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Max concurrency')}</span>
									<input
										type="number"
										min={1}
										value={form.vllm_concurrency}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ vllm_concurrency: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Timeout (seconds)')}
									</span>
									<input
										type="number"
										min={1}
										value={form.vllm_timeout}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ vllm_timeout: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
							</div>
						</div>
					)}

					{form.mode === 'local' && (
						<div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
							<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
								{t('Local model gateway')}
							</h3>
							<p className={captionClassName}>
								{t(
									'The gateway is started on demand from the model directory and stopped when the backend changes. It needs the transformers stack installed on the host.',
								)}
							</p>
							<div className="grid gap-4 sm:grid-cols-2">
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Model directory')}</span>
									<input
										value={form.local_model_dir}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ local_model_dir: event.target.value })
										}
										placeholder="models/OXR-1.0"
										spellCheck={false}
										className={`${fieldClassName} font-mono`}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Host')}</span>
									<input
										value={form.local_host}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ local_host: event.target.value })
										}
										placeholder="127.0.0.1"
										spellCheck={false}
										className={`${fieldClassName} font-mono`}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Port')}</span>
									<input
										type="number"
										min={1}
										max={65535}
										value={form.local_port}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ local_port: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Threads (0 = auto)')}
									</span>
									<input
										type="number"
										min={0}
										value={form.local_threads}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ local_threads: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Precision')}</span>
									<select
										value={form.local_dtype}
										disabled={loading || saving}
										onChange={(event) =>
											patch({
												local_dtype: event.target
													.value as Form['local_dtype'],
											})
										}
										className={fieldClassName}
									>
										<option value="float32">float32</option>
										<option value="bfloat16">bfloat16</option>
									</select>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Startup timeout (s)')}
									</span>
									<input
										type="number"
										min={1}
										value={form.local_startup_timeout}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ local_startup_timeout: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
							</div>
						</div>
					)}

					{form.mode !== 'none' && (
						<div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
							<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
								{t('Layout analysis')}
							</h3>
							<div className="grid gap-4 sm:grid-cols-2">
								{/* The address belongs to this card: it is the layout endpoint,
								    not a property of the recognition backend above. */}
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Layout service URL')}
									</span>
									<input
										value={form.layout_url}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_url: event.target.value })
										}
										placeholder="http://127.0.0.1:8081"
										spellCheck={false}
										className={`${fieldClassName} font-mono`}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Pages per request')}
									</span>
									<input
										type="number"
										min={1}
										value={form.layout_batch_size}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_batch_size: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Max concurrency')}</span>
									<input
										type="number"
										min={1}
										value={form.layout_concurrency}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_concurrency: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Timeout (seconds)')}
									</span>
									<input
										type="number"
										min={1}
										value={form.layout_timeout}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_timeout: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('Retries')}</span>
									<input
										type="number"
										min={1}
										value={form.layout_retry_times}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_retry_times: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>
										{t('Score threshold (0–1)')}
									</span>
									<input
										type="number"
										min={0}
										max={1}
										step={0.05}
										value={form.layout_score_threshold}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_score_threshold: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
								<label className={labelClassName}>
									<span className={captionClassName}>{t('NMS IoU (0–1)')}</span>
									<input
										type="number"
										min={0}
										max={1}
										step={0.05}
										value={form.layout_nms_iou}
										disabled={loading || saving}
										onChange={(event) =>
											patch({ layout_nms_iou: event.target.value })
										}
										className={fieldClassName}
									/>
								</label>
							</div>
							<label className="flex items-center gap-2 text-xs text-body dark:text-zinc-300">
								<input
									type="checkbox"
									checked={form.layout_provides_reading_order}
									disabled={loading || saving}
									onChange={(event) =>
										patch({
											layout_provides_reading_order: event.target.checked,
										})
									}
								/>
								{t('The layout service already returns blocks in reading order')}
							</label>
						</div>
					)}

					<div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
						<h3 className="text-xs font-semibold text-heading dark:text-zinc-100">
							{t('File storage')}
						</h3>
						<p className={captionClassName}>
							{t(
								'Absolute path, or a path relative to the repository root. The folders are created on first use.',
							)}
						</p>
						<div className="grid gap-4 sm:grid-cols-2">
							<label className={labelClassName}>
								<span className={captionClassName}>{t('Uploaded files')}</span>
								<input
									value={form.upload_dir}
									disabled={loading || saving}
									onChange={(event) => patch({ upload_dir: event.target.value })}
									placeholder="logs/parsing-uploads"
									spellCheck={false}
									className={`${fieldClassName} font-mono`}
								/>
							</label>
							<label className={labelClassName}>
								<span className={captionClassName}>{t('Extracted images')}</span>
								<input
									value={form.image_dir}
									disabled={loading || saving}
									onChange={(event) => patch({ image_dir: event.target.value })}
									placeholder="logs/parsing-assets"
									spellCheck={false}
									className={`${fieldClassName} font-mono`}
								/>
							</label>
						</div>
					</div>

					<div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 pt-4 dark:border-zinc-700">
						<div className="flex flex-wrap gap-2">
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								loading={testing === 'backend'}
								disabled={loading || saving || testing !== null}
								onClick={() => void test('backend')}
							>
								{t('Test recognition')}
							</Button>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								loading={testing === 'layout'}
								disabled={loading || saving || testing !== null}
								onClick={() => void test('layout')}
							>
								{t('Test layout')}
							</Button>
						</div>
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							loading={saving}
							disabled={loading || saving || form.mode === 'none'}
							onClick={() => void handleSave()}
						>
							{saving ? t('Saving…') : t('Save')}
						</Button>
					</div>
				</>
			)}

			<Toast
				open={toast !== null}
				message={toast?.message ?? ''}
				variant={toast?.variant ?? ToastVariant.Info}
				onClose={() => setToast(null)}
			/>
		</section>
	);
};
