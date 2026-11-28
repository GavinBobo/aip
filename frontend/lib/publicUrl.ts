// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const LOOPBACK_APP_URL = /^https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/i;

/**
 * The origin to put in a link someone else will open - an invitation or a
 * password reset.
 *
 * `APP_URL` is authoritative when it names a real deployment. The dev default
 * is `http://localhost:3010`, though, and a machine that opens the app from
 * another computer reaches it by the host's LAN address. Keeping localhost in
 * that case produces links that only work on the server itself, so the request
 * origin wins when the configured one is loopback.
 */
export const publicAppUrl = (request: Request): string => {
	const configured = process.env.APP_URL?.replace(/\/+$/, '');
	const requestOrigin = new URL(request.url).origin;
	if (!configured) return requestOrigin;
	return LOOPBACK_APP_URL.test(configured) ? requestOrigin : configured;
};
