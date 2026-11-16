// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Instance ids are ``<document>/<run>`` — two path segments by design, because
 * that is also where the run lives on disk. Every URL that carries one has to
 * encode each segment, so the two places that build such a URL share this.
 */
const encodeInstanceId = (id: string): string =>
	id
		.split('/')
		.map((segment) => encodeURIComponent(segment))
		.join('/');

/** The in-app detail page for one stored run. */
export const instanceHref = (id: string): string => `/parsing/instances/${encodeInstanceId(id)}`;

/** The backend path (relative to ``/api``) that answers for one run. */
export const instanceApiPath = (id: string): string => `parsing/instances/${encodeInstanceId(id)}`;

/** A stored run's timestamp, rendered in the reader's own timezone. */
export const formatInstanceTime = (created: string | null): string => {
	if (created == null || created === '') return '—';
	const parsed = new Date(created);
	if (Number.isNaN(parsed.getTime())) return created;
	return parsed.toLocaleString();
};

/** ``1234`` → ``1.2 s``; long runs read better as seconds than as milliseconds. */
export const formatDuration = (milliseconds: number | null): string => {
	if (milliseconds == null || !Number.isFinite(milliseconds)) return '—';
	if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
	return `${(milliseconds / 1000).toFixed(1)} s`;
};
