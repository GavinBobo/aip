// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Forward a request to the Python (FastAPI) backend, preserving method, path,
// query, and body. Used by route handlers that need permission gating for
// endpoints that would otherwise be plain next.config rewrites — the wrapper
// (withPermission) enforces access, this just relays the call. The frontend and
// backend share the same `/api/...` path, so we forward the incoming pathname
// verbatim.
//
// The authenticated user id is forwarded on every call. The Python tier uses
// it to resolve effective user/department Zone grants once per request, so a
// route cannot accidentally default to an unscoped read.

import { buildInternalIdentityHeaders, INTERNAL_USER_HEADER } from '@/lib/internalIdentity';

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? 'http://127.0.0.1:3001';

/**
 * What every proxied answer is allowed to be kept in, which is nothing shared.
 *
 * Every route that reaches this proxy is behind `withPermission`, so every
 * answer it relays is scoped to the caller who asked for it — `/api/tags` most
 * literally, since it carries author names only for a caller who may manage
 * tags. Next does not cache Route Handlers, so this is about the browser: a GET
 * that states no policy is left to heuristic freshness, and none of these
 * answers may be handed to the next person to use the machine.
 *
 * Exported because a wrapper that rebuilds one of these responses has to carry
 * it through rather than decide it again — see `withTagAuthors`.
 */
export const PROXY_CACHE_CONTROL = 'private, no-store';

/**
 * How long the backend may take to start answering before the proxy gives up.
 *
 * This bounds the wait for response headers, not the body: a slow export or a
 * streamed answer can keep transferring after the timer is cleared. Without
 * it, a backend that accepts the TCP connection but never answers leaves the
 * browser on its loading state until undici's five-minute headers timeout.
 */
const READ_HEADERS_TIMEOUT_MS = 30_000;
const WRITE_HEADERS_TIMEOUT_MS = 120_000;

const upstreamFailure = (timedOut: boolean): Response =>
	new Response(
		JSON.stringify({
			error: timedOut
				? 'The backend did not answer in time.'
				: 'The backend is unavailable right now.',
		}),
		{
			status: timedOut ? 504 : 502,
			headers: {
				'Content-Type': 'application/json',
				'Cache-Control': PROXY_CACHE_CONTROL,
			},
		},
	);

/**
 * `userId` names the caller to the backend, for routes that record who did
 * something (a tag's `created_by`, for instance). Opt-in rather than always
 * forwarded, so a route that has no use for an identity does not imply one.
 *
 * It comes from `withPermission`'s already-resolved user, and the header set is
 * rebuilt from scratch below — so a client cannot smuggle in an identity of its
 * own choosing by sending the header itself.
 */
export async function proxyToBackend(
	req: Request,
	{ userId }: { userId?: string } = {},
): Promise<Response> {
	const incoming = new URL(req.url);
	const target = `${PYTHON_API_URL}${incoming.pathname}${incoming.search}`;

	const headers: Record<string, string> = { Accept: 'application/json' };
	const contentType = req.headers.get('content-type');
	if (contentType) headers['Content-Type'] = contentType;
	const forwardedUserId = userId ?? req.headers.get(INTERNAL_USER_HEADER);
	if (forwardedUserId) {
		Object.assign(headers, buildInternalIdentityHeaders(forwardedUserId));
	}

	const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
	// Bytes, not text: connection setup can upload a spreadsheet or Parquet
	// file, and decoding the multipart body as UTF-8 replaces every non-text
	// byte and corrupts the upload.
	const body = hasBody ? await req.arrayBuffer() : undefined;

	const controller = new AbortController();
	const timer = setTimeout(
		() => controller.abort(),
		req.method === 'GET' || req.method === 'HEAD'
			? READ_HEADERS_TIMEOUT_MS
			: WRITE_HEADERS_TIMEOUT_MS,
	);
	let upstream: Response;
	try {
		upstream = await fetch(target, {
			method: req.method,
			headers,
			body,
			signal: AbortSignal.any([req.signal, controller.signal]),
		});
	} catch {
		// A failed connect and a backend that never sent headers both belong
		// here; the browser is told which one happened where it can be told.
		return upstreamFailure(controller.signal.aborted && !req.signal.aborted);
	} finally {
		clearTimeout(timer);
	}

	// Relayed as bytes: decoding as text would replace every byte of a binary
	// answer, such as the Ossie export's zip, that is not valid UTF-8.
	let respBody: ArrayBuffer;
	try {
		respBody = await upstream.arrayBuffer();
	} catch {
		return upstreamFailure(false);
	}
	return new Response(respBody, {
		status: upstream.status,
		headers: {
			'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
			'Cache-Control': PROXY_CACHE_CONTROL,
		},
	});
}
