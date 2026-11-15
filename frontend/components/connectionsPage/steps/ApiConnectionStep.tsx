// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { t } from '@/i18n';

import type { ChangeEvent } from 'react';
import { Spinner } from '@nvidia/foundations-react-core';
import type { ApiAuthType, ApiPreview } from '@/types/connection';

/** Request settings as the form holds them: every value is text. */
export type ApiFormValues = {
	database: string;
	url: string;
	method: string;
	headers: string;
	params: string;
	body: string;
	recordsPath: string;
	authType: ApiAuthType;
	token: string;
	user: string;
	password: string;
	timeout: string;
};

export const EMPTY_API_FORM: ApiFormValues = {
	database: '',
	url: '',
	method: 'GET',
	headers: '',
	params: '',
	body: '',
	recordsPath: '',
	authType: 'none',
	token: '',
	user: '',
	password: '',
	timeout: '30',
};

export type ApiConnectionStepProps = {
	values: ApiFormValues;
	onFieldChange: (key: keyof ApiFormValues, value: string) => void;
	/** Editing: the connection's name is the catalog key and is fixed. */
	nameReadOnly?: boolean;
	preview: ApiPreview | null;
	columnNames: string[];
	onColumnNameChange: (index: number, name: string) => void;
	onLoad: () => void;
	busy: boolean;
	error: string | null;
	/** Shown after a successful fetch, so the operator knows when data is from. */
	fetchedAt?: string | null;
};

const inputClassName =
	'rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-heading outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100';

const labelClassName = 'text-sm font-medium text-heading dark:text-zinc-200';
const hintClassName = 'text-xs text-secondary dark:text-zinc-400';

export const ApiConnectionStep = ({
	values,
	onFieldChange,
	nameReadOnly = false,
	preview,
	columnNames,
	onColumnNameChange,
	onLoad,
	busy,
	error,
	fetchedAt = null,
}: ApiConnectionStepProps) => {
	const text =
		(key: keyof ApiFormValues) =>
		({ target }: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
			onFieldChange(key, target.value);

	return (
		<div className="flex flex-1 flex-col gap-4 p-2">
			<p className="text-sm text-body dark:text-zinc-400">
				{t(
					'Read a REST endpoint into a table. The response is fetched when the connection is created and whenever you refresh it; questions query the stored snapshot.',
				)}{' '}
			</p>

			<label className="flex flex-col gap-1.5">
				<span className={labelClassName}>
					{t('Name')}
					<span className="ml-0.5 text-red-500">*</span>
				</span>
				<input
					type="text"
					value={values.database}
					onChange={text('database')}
					readOnly={nameReadOnly}
					placeholder={t('crm_customers')}
					data-testid="api-connection-name"
					className={
						nameReadOnly
							? `${inputClassName} cursor-not-allowed bg-zinc-50 text-secondary dark:bg-zinc-800/60 dark:text-zinc-400`
							: inputClassName
					}
				/>
				<span className={hintClassName}>
					{nameReadOnly
						? t('The connection name is fixed once created.')
						: t(
								'Letters, digits, and underscores; must not start with a digit. One endpoint becomes one table.',
							)}
				</span>
			</label>

			<div className="flex gap-2">
				<label className="flex w-28 flex-col gap-1.5">
					<span className={labelClassName}>{t('Method')}</span>
					<select
						value={values.method}
						onChange={text('method')}
						data-testid="api-connection-method"
						className={inputClassName}
					>
						<option value="GET">GET</option>
						<option value="POST">POST</option>
					</select>
				</label>
				<label className="flex flex-1 flex-col gap-1.5">
					<span className={labelClassName}>
						URL<span className="ml-0.5 text-red-500">*</span>
					</span>
					<input
						type="text"
						value={values.url}
						onChange={text('url')}
						placeholder="https://api.example.com/v1/customers"
						spellCheck={false}
						data-testid="api-connection-url"
						className={`${inputClassName} font-mono`}
					/>
				</label>
			</div>

			<div className="flex gap-2">
				<label className="flex w-40 flex-col gap-1.5">
					<span className={labelClassName}>{t('Authentication')}</span>
					<select
						value={values.authType}
						onChange={text('authType')}
						data-testid="api-connection-auth"
						className={inputClassName}
					>
						<option value="none">{t('None')}</option>
						<option value="bearer">{t('Bearer token')}</option>
						<option value="basic">{t('Basic auth')}</option>
					</select>
				</label>
				{values.authType === 'bearer' && (
					<label className="flex flex-1 flex-col gap-1.5">
						<span className={labelClassName}>{t('Token')}</span>
						<input
							type="password"
							value={values.token}
							onChange={text('token')}
							autoComplete="new-password"
							placeholder={t('Leave empty to keep the stored token')}
							data-testid="api-connection-token"
							className={inputClassName}
						/>
					</label>
				)}
				{values.authType === 'basic' && (
					<>
						<label className="flex flex-1 flex-col gap-1.5">
							<span className={labelClassName}>{t('User')}</span>
							<input
								type="text"
								value={values.user}
								onChange={text('user')}
								data-testid="api-connection-user"
								className={inputClassName}
							/>
						</label>
						<label className="flex flex-1 flex-col gap-1.5">
							<span className={labelClassName}>{t('Password')}</span>
							<input
								type="password"
								value={values.password}
								onChange={text('password')}
								autoComplete="new-password"
								placeholder={t('Leave empty to keep the stored password')}
								data-testid="api-connection-password"
								className={inputClassName}
							/>
						</label>
					</>
				)}
				<label className="flex w-28 flex-col gap-1.5">
					<span className={labelClassName}>{t('Timeout (s)')}</span>
					<input
						type="number"
						min={1}
						max={300}
						value={values.timeout}
						onChange={text('timeout')}
						data-testid="api-connection-timeout"
						className={inputClassName}
					/>
				</label>
			</div>

			<div className="grid grid-cols-2 gap-2">
				<label className="flex flex-col gap-1.5">
					<span className={labelClassName}>{t('Headers (JSON)')}</span>
					<textarea
						value={values.headers}
						onChange={text('headers')}
						rows={3}
						spellCheck={false}
						placeholder={'{"Accept": "application/json"}'}
						data-testid="api-connection-headers"
						className={`${inputClassName} resize-y font-mono text-xs`}
					/>
				</label>
				<label className="flex flex-col gap-1.5">
					<span className={labelClassName}>{t('Query params (JSON)')}</span>
					<textarea
						value={values.params}
						onChange={text('params')}
						rows={3}
						spellCheck={false}
						placeholder={'{"limit": "1000"}'}
						data-testid="api-connection-params"
						className={`${inputClassName} resize-y font-mono text-xs`}
					/>
				</label>
			</div>

			{values.method === 'POST' && (
				<label className="flex flex-col gap-1.5">
					<span className={labelClassName}>{t('Body (JSON)')}</span>
					<textarea
						value={values.body}
						onChange={text('body')}
						rows={3}
						spellCheck={false}
						placeholder={'{"query": "..."}'}
						data-testid="api-connection-body"
						className={`${inputClassName} resize-y font-mono text-xs`}
					/>
				</label>
			)}

			<label className="flex flex-col gap-1.5">
				<span className={labelClassName}>{t('Records path')}</span>
				<input
					type="text"
					value={values.recordsPath}
					onChange={text('recordsPath')}
					placeholder="data.items"
					spellCheck={false}
					data-testid="api-connection-records-path"
					className={`${inputClassName} font-mono`}
				/>
				<span className={hintClassName}>
					{t(
						'Where the row array sits in the JSON, dot-separated. Leave empty to detect common wrappers (data, items, results, rows).',
					)}{' '}
				</span>
			</label>

			<div className="flex items-center gap-3">
				<button
					type="button"
					onClick={onLoad}
					disabled={busy || values.url.trim() === ''}
					data-testid="api-connection-load"
					className="rounded-lg bg-[#76b900] px-4 py-2 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
				>
					{busy ? t('Loading…') : preview == null ? t('Load data') : t('Reload data')}
				</button>
				{busy && <Spinner aria-label={t('Calling the API')} className="h-4 w-4" />}
				{preview != null && (
					<span className={hintClassName}>
						{preview.row_count.toLocaleString()} {t('rows ×')} {preview.column_count}{' '}
						{t('columns')}{' '}
						{fetchedAt ? ` · fetched ${new Date(fetchedAt).toLocaleString()}` : ''}
					</span>
				)}
			</div>

			{error != null && (
				<p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
					{error}
				</p>
			)}

			{preview != null && (
				<div className="flex flex-col gap-3">
					<div className="max-h-[220px] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="min-w-full border-collapse text-xs">
							<tbody>
								{preview.rows.map((row, rowIndex) => (
									<tr key={rowIndex}>
										<td className="w-10 border-r border-zinc-200 px-2 py-1 text-right text-secondary dark:border-zinc-700 dark:text-zinc-500">
											{rowIndex + 1}
										</td>
										{Array.from(
											{ length: preview.column_count },
											(_, columnIndex) => (
												<td
													key={columnIndex}
													className="max-w-[220px] truncate whitespace-nowrap border-r border-zinc-100 px-2 py-1 last:border-r-0 dark:border-zinc-800"
												>
													{row[columnIndex] ?? ''}
												</td>
											),
										)}
									</tr>
								))}
							</tbody>
						</table>
					</div>

					<div className="flex flex-col gap-2">
						<span className={labelClassName}>{t('Column names')}</span>
						<div className="grid max-h-[200px] grid-cols-2 gap-2 overflow-y-auto pr-1">
							{columnNames.map((name, index) => (
								<label
									key={preview.columns[index]?.source ?? index}
									className="flex flex-col gap-1"
								>
									<span className="text-[11px] text-secondary dark:text-zinc-500">
										{preview.columns[index]?.source ??
											t('Column {0}', { 0: index + 1 })}
									</span>
									<input
										type="text"
										value={name}
										onChange={({ target }) =>
											onColumnNameChange(index, target.value)
										}
										data-testid={`api-connection-column-${index}`}
										className={`${inputClassName} px-2 py-1 text-xs`}
									/>
								</label>
							))}
						</div>
						<span className={hintClassName}>
							{t(
								"Renames are matched by the API's field name, so they survive fields appearing in a different order.",
							)}{' '}
						</span>
					</div>
				</div>
			)}
		</div>
	);
};
