// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import axios, { AxiosError, AxiosResponse, type AxiosRequestConfig } from 'axios';
import { t } from '@/i18n/translate';
import { ApiError, PageParams, ResponseWithError } from './types';

// Query params accepted by `requests.get`. Numbers/booleans are serialised by
// axios at request time, so callers can pass them without stringifying first.
export type QueryParams = Record<
	string,
	string | number | boolean | string[] | number[] | undefined
>;

/**
 * Query params for one page. Both are left out when they say nothing — the
 * backend defaults to the head of the list and, without a `limit`, to all of
 * it — which keeps an unpaged call's URL free of noise.
 */
export const pageQuery = ({ skip, limit }: PageParams = {}): QueryParams => ({
	...(skip ? { skip } : {}),
	...(limit != null ? { limit } : {}),
});

const isServer = typeof window === 'undefined';

const api = axios.create({
	baseURL: isServer ? `${process.env.PYTHON_API_URL ?? 'http://127.0.0.1:3001'}/api` : '/api',
	headers: {
		'Content-Type': 'application/json',
	},
});

/**
 * Failures that mean the request never got an answer, rather than an answer
 * saying no. A GET is safe to send again, and during development the Python
 * server drops in-flight sockets whenever uvicorn reloads.
 *
 * The root layout starts shared reads before the page is streamed and
 * dehydrates them while they are still pending, so a dropped socket there is
 * reported as a failed hydration rather than as the ordinary background read
 * it is. Giving those reads a short window to reconnect keeps a save-and-reload
 * from turning into a console error; HTTP errors are left untouched, because
 * repeating a refusal only spends the same answer again.
 */
const RETRYABLE_GET_CODES = new Set([
	'ECONNRESET',
	'ECONNREFUSED',
	'EPIPE',
	'ETIMEDOUT',
	'EAI_AGAIN',
]);

const SERVER_GET_RETRY_DELAYS_MS = [500, 1500, 3000];

const wait = (ms: number): Promise<void> =>
	new Promise((resolve) => {
		setTimeout(resolve, ms);
	});

const isTransientTransportError = (error: unknown): boolean =>
	axios.isAxiosError(error) &&
	error.response === undefined &&
	typeof error.code === 'string' &&
	RETRYABLE_GET_CODES.has(error.code);

const getWithTransportRetry = async <OutputType>(
	url: string,
	config: AxiosRequestConfig,
): Promise<AxiosResponse<OutputType>> => {
	// The browser's queries already retry through the query client, and its
	// route handlers are a local hop; this window exists for the Next server
	// reading the Python server directly.
	const delays = isServer ? SERVER_GET_RETRY_DELAYS_MS : [];
	for (let attempt = 0; ; attempt += 1) {
		try {
			return await api.get<OutputType>(url, config);
		} catch (error) {
			if (
				!isTransientTransportError(error) ||
				attempt >= delays.length ||
				config.signal?.aborted
			) {
				throw error;
			}
			await wait(delays[attempt]);
			if (config.signal?.aborted) throw error;
		}
	}
};

const responseBody = <DataType>({ data }: AxiosResponse<DataType>): DataType => data;

const extractServerMessage = (data: unknown): string | undefined => {
	if (data == null || typeof data !== 'object') return undefined;
	// `detail` is FastAPI's shape; `error` is what the Next route handlers under
	// app/api use. Reading only the first meant every message those routes went
	// out of their way to produce surfaced as "Request failed with status 400".
	const { detail, error } = data as { detail?: unknown; error?: unknown };
	// The API speaks the source language (English); the dictionary owns the
	// Chinese copy. Translating here means every caller's `message` is already
	// localized instead of each surface remembering to wrap it.
	if (typeof detail === 'string') return t(detail);
	return typeof error === 'string' ? t(error) : undefined;
};

const errorHandler = (err: AxiosError): ApiError => {
	return {
		message: (err.response != null && extractServerMessage(err.response.data)) || err.message,
		error: true,
	};
};

const errorHandlerBlob = async (err: AxiosError): Promise<ApiError> => {
	const data = err.response?.data;
	let message: string | undefined;
	if (data instanceof Blob) {
		try {
			message = extractServerMessage(JSON.parse(await data.text()));
		} catch {
			message = undefined;
		}
	} else {
		message = extractServerMessage(data);
	}
	return { message: message || err.message, error: true };
};

const normalizeQueryParams = (params: QueryParams): QueryParams => {
	const newParams: QueryParams = {};
	Object.entries(params).forEach(([paramKey, paramValue]) => {
		if (Array.isArray(paramValue)) {
			newParams[paramKey] = paramValue.toString();
		} else {
			newParams[paramKey] = paramValue;
		}
	});
	return newParams;
};

export const requests = {
	get: <OutputType>(
		url: string,
		params: QueryParams = {},
		abortController?: AbortController,
		serverUserId?: string,
	) => {
		return getWithTransportRetry<OutputType>(url, {
			params: normalizeQueryParams(params),
			signal: abortController?.signal,
			// Server-side prefetches call the backend directly, bypassing the
			// Next route handler that would normally add this identity. In the
			// browser the route wrapper deletes and replaces it with the
			// authenticated caller before proxying.
			headers: serverUserId ? { 'x-all-ontology-user-id': serverUserId } : undefined,
		})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},

	post: <OutputType>(url: string, data: unknown = {}, abortController?: AbortController) => {
		return api
			.post<OutputType>(url, data, {
				signal: abortController?.signal,
			})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},

	put: <OutputType>(url: string, data: unknown = {}, abortController?: AbortController) => {
		return api
			.put<OutputType>(url, data, {
				signal: abortController?.signal,
			})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},

	/** Like `post`, but for endpoints that respond with a file (e.g. a YAML export) rather than JSON. */
	postBlob: (url: string, data: unknown = {}, abortController?: AbortController) => {
		return api
			.post<Blob>(url, data, {
				responseType: 'blob',
				signal: abortController?.signal,
			})
			.then((res: AxiosResponse<Blob>): { blob: Blob } => ({ blob: res.data }))
			.catch(errorHandlerBlob) as Promise<ResponseWithError<{ blob: Blob }>>;
	},

	/** Like `post`, but sends `FormData` (multipart) instead of a JSON body. */
	postForm: <OutputType>(
		url: string,
		formData: FormData,
		params: QueryParams = {},
		abortController?: AbortController,
	) => {
		return api
			.post<OutputType>(url, formData, {
				params: normalizeQueryParams(params),
				// Let axios/the browser compute the multipart boundary instead of
				// using the instance's default JSON content type.
				headers: { 'Content-Type': undefined },
				signal: abortController?.signal,
			})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},

	/** Like `postForm`, but for a `PUT` (e.g. replacing an uploaded file). */
	putForm: <OutputType>(
		url: string,
		formData: FormData,
		params: QueryParams = {},
		abortController?: AbortController,
	) => {
		return api
			.put<OutputType>(url, formData, {
				params: normalizeQueryParams(params),
				headers: { 'Content-Type': undefined },
				signal: abortController?.signal,
			})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},

	patch: <OutputType>(url: string, body: Record<string, unknown> = {}) => {
		return api.patch<OutputType>(url, body).then(responseBody).catch(errorHandler) as Promise<
			ResponseWithError<OutputType>
		>;
	},

	delete: <OutputType>(url: string, abortController?: AbortController) => {
		return api
			.delete<OutputType>(url, {
				signal: abortController?.signal,
			})
			.then(responseBody)
			.catch(errorHandler) as Promise<ResponseWithError<OutputType>>;
	},
};
