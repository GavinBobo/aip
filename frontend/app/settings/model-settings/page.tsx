// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import { llmSettingsApi, type LlmSettingSource, type LlmSettings } from '@/api/settings';
import { Button } from '@/common/Button';
import { Toast } from '@/common/Toast';
import { ButtonTheme, Size } from '@/enums/button';
import { ToastVariant } from '@/enums/toast';
import { t } from '@/i18n';
import { ParsingModelSettings } from '@/components/settings/ParsingModelSettings';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-disabled dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300 dark:disabled:bg-zinc-800/50';

const sourceLabel = (source: LlmSettingSource): string => {
	if (source === 'saved') return t('Saved in this instance');
	if (source === 'environment') return t('Using environment value');
	return t('Not set');
};

export default function LlmSettingsPage() {
	const [settings, setSettings] = useState<LlmSettings | null>(null);
	const [baseUrl, setBaseUrl] = useState('');
	const [model, setModel] = useState('');
	const [apiKey, setApiKey] = useState('');
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [toast, setToast] = useState<{ message: string; variant: ToastVariant } | null>(null);

	useEffect(() => {
		let cancelled = false;
		llmSettingsApi.get().then((res) => {
			if (cancelled) return;
			setLoading(false);
			if (res.error) {
				setLoadError(res.message ?? t('Failed to load LLM settings.'));
				return;
			}
			setSettings(res);
			setBaseUrl(res.base_url);
			setModel(res.model);
		});
		return () => {
			cancelled = true;
		};
	}, []);

	const handleSave = async () => {
		if (saving) return;
		const trimmedUrl = baseUrl.trim();
		if (trimmedUrl !== '' && !/^https?:\/\//i.test(trimmedUrl)) {
			setToast({
				message: t('Base URL must start with http:// or https://.'),
				variant: ToastVariant.Error,
			});
			return;
		}

		setSaving(true);
		const res = await llmSettingsApi.save({
			base_url: trimmedUrl,
			model: model.trim(),
			...(apiKey.trim() === '' ? {} : { api_key: apiKey.trim() }),
		});
		setSaving(false);

		if (res.error) {
			setToast({
				message: res.message ?? t('Failed to save LLM settings.'),
				variant: ToastVariant.Error,
			});
			return;
		}

		setSettings(res);
		setBaseUrl(res.base_url);
		setModel(res.model);
		setApiKey('');
		setToast({ message: t('LLM settings saved.'), variant: ToastVariant.Success });
	};

	const apiKeyPlaceholder =
		settings?.api_key_source === 'saved'
			? t('Saved key {0} — leave blank to keep it', {
					0: settings.api_key_hint ?? '••••',
				})
			: settings?.api_key_source === 'environment'
				? t('Environment key in use — enter a key to override it')
				: t('Enter the API key');

	return (
		<main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,rgba(255,255,255,1)_0%,rgba(250,250,250,0.6)_100%)] px-7 py-6 sm:px-10 sm:py-7 dark:bg-[linear-gradient(180deg,rgba(9,9,11,1)_0%,rgba(24,24,27,0.5)_100%)]">
			<div className="w-full space-y-5">
				<div>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Model Settings')}
					</h1>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
						{t(
							'Configure the models this instance uses: the conversational endpoint for the agent and semantic compilation, and the document-parsing backends. Embedding and reranking models keep their own configuration.',
						)}
					</p>
				</div>

				{loadError != null ? (
					<div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
						{loadError}
					</div>
				) : (
					<form
						className="space-y-5 rounded-lg border border-zinc-200/90 bg-white/90 p-5 shadow-sm ring-1 ring-zinc-950/[0.04] dark:border-zinc-700/90 dark:bg-zinc-950/50 dark:ring-white/[0.06]"
						onSubmit={(event) => {
							event.preventDefault();
							void handleSave();
						}}
					>
						<div>
							<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
								{t('Language model settings')}
							</h2>
							<p className="mt-1 text-xs leading-relaxed text-secondary dark:text-zinc-400">
								{t('Used by the agent, chat, and semantic compilation.')}
							</p>
						</div>
						<label className="flex flex-col gap-1.5">
							<span className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-heading dark:text-zinc-100">
								{t('Base URL')}
								{settings != null && (
									<span className="text-[10px] font-normal uppercase tracking-wide text-secondary dark:text-zinc-500">
										{sourceLabel(settings.base_url_source)}
									</span>
								)}
							</span>
							<input
								type="url"
								value={baseUrl}
								onChange={(event) => setBaseUrl(event.target.value)}
								placeholder="https://integrate.api.nvidia.com/v1"
								disabled={loading || saving}
								spellCheck={false}
								data-testid="llm-base-url"
								className={`${inputClassName} font-mono`}
							/>
							<span className="text-xs text-secondary dark:text-zinc-400">
								{t(
									'Leave blank to use the endpoint configured by the environment.',
								)}
							</span>
						</label>

						<label className="flex flex-col gap-1.5">
							<span className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-heading dark:text-zinc-100">
								{t('API Key')}
								{settings != null && (
									<span className="text-[10px] font-normal uppercase tracking-wide text-secondary dark:text-zinc-500">
										{sourceLabel(settings.api_key_source)}
									</span>
								)}
							</span>
							<input
								type="password"
								value={apiKey}
								onChange={(event) => setApiKey(event.target.value)}
								placeholder={apiKeyPlaceholder}
								autoComplete="new-password"
								disabled={loading || saving}
								data-testid="llm-api-key"
								className={inputClassName}
							/>
							<span className="text-xs text-secondary dark:text-zinc-400">
								{t(
									'Stored in the instance configuration database and never returned to the browser.',
								)}
							</span>
						</label>

						<label className="flex flex-col gap-1.5">
							<span className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-heading dark:text-zinc-100">
								{t('Model')}
								{settings != null && (
									<span className="text-[10px] font-normal uppercase tracking-wide text-secondary dark:text-zinc-500">
										{sourceLabel(settings.model_source)}
									</span>
								)}
							</span>
							<input
								type="text"
								value={model}
								onChange={(event) => setModel(event.target.value)}
								placeholder="nvidia/nemotron-3.5-lightning-30b-a3b"
								disabled={loading || saving}
								spellCheck={false}
								data-testid="llm-model"
								className={`${inputClassName} font-mono`}
							/>
							<span className="text-xs text-secondary dark:text-zinc-400">
								{t('Leave blank to use the model configured by the environment.')}
							</span>
						</label>

						<div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 pt-4 dark:border-zinc-700">
							<p className="max-w-2xl text-xs leading-relaxed text-secondary dark:text-zinc-400">
								{t(
									'Changes are stored immediately. Restart the API and ingestion services so existing model clients pick up the new values.',
								)}
							</p>
							<Button
								theme={ButtonTheme.Primary}
								size={Size.REGULAR}
								type="submit"
								disabled={loading || saving}
							>
								{saving ? t('Saving…') : t('Save')}
							</Button>
						</div>
					</form>
				)}
			</div>

			<Toast
				open={toast !== null}
				message={toast?.message ?? ''}
				variant={toast?.variant ?? ToastVariant.Info}
				onClose={() => setToast(null)}
			/>

			<div className="mt-5">
				<ParsingModelSettings />
			</div>
		</main>
	);
}
