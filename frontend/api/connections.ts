// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ApiPreview, Connection, FilePreview, ServerPathListing } from '@/types/connection';
import type { ConnectionInput } from '@/types/connection';
import type { ApiError, ApiResponse, ResponseWithCount } from './types';

type CreateResponse = ApiError | { data: Connection };
// A successful test also returns the connection's schemas (for the picker).
type TestResponse = ApiError | { success: true; schemas: string[] };

const err = (message: string): ApiError => ({ error: true, message });

/** Fields the file endpoints read from the form body, plus the file itself. */
const fileForm = (
	file: File,
	fields: Record<string, string | number | string[] | number[] | null | undefined>,
): FormData => {
	const formData = new FormData();
	formData.append('file', file);
	Object.entries(fields).forEach(([key, value]) => {
		if (value == null || value === '') return;
		formData.append(key, Array.isArray(value) ? JSON.stringify(value) : String(value));
	});
	return formData;
};

export type FileConnectionInput = {
	database: string;
	sheet?: string | null;
	delimiter?: string | null;
	header_row: number;
	columns: string[];
	/** Zero-based positions to keep; omit to keep every column. */
	keep_columns?: number[];
};

export type FileServerPathInput = Omit<FileConnectionInput, 'database'> & {
	database: string;
	path: string;
};

export const connectionsApi = {
	getAll: (): Promise<ApiResponse<Connection[]>> =>
		requests.get<ResponseWithCount<Connection[]>>('connections'),

	isEnvSource: () => requests.get<boolean>('connections/source'),

	create: (input: ConnectionInput): Promise<CreateResponse> =>
		requests.post<{ data: Connection }>('connections', { connection: input }),

	test: async (input: ConnectionInput, replacing?: string): Promise<TestResponse> => {
		const res = await requests.post<{ success: boolean; schemas?: string[] }>(
			'connections/test',
			{ connection: input, ...(replacing == null ? {} : { replacing }) },
		);

		if (res.error || res.success !== true) {
			return err(res.message ?? 'Connection test failed.');
		}

		// The test also reports the connection's schemas (empty for connectors
		// that don't enumerate them) so the UI can offer a schema picker.
		return { success: true, schemas: res.schemas ?? [] };
	},

	// Rewrites every setting except the connection's identity: `database` (which
	// doubles as the connection's name) and `type` come back as a 422 if they
	// differ from the stored ones. Credentials left blank keep their stored
	// value, since `getAll` strips them and the edit form has none to send back.
	update: (databaseName: string, input: ConnectionInput): Promise<CreateResponse> =>
		requests.put<{ data: Connection }>(`connections/${encodeURIComponent(databaseName)}`, {
			connection: input,
		}),

	// Narrow update: flips "authenticate as signed-in user" without re-sending
	// credentials, so the connections page can toggle it inline.
	setSsoFederation: (databaseName: string, enabled: boolean) =>
		requests.patch<{ data: { database_name: string; sso_federation: boolean } }>(
			`connections/${encodeURIComponent(databaseName)}/sso-federation`,
			{ enabled },
		),

	delete: (databaseName: string) =>
		requests.delete<{ data: { database_name: string } }>(
			`connections/${encodeURIComponent(databaseName)}`,
		),

	// Reads the first rows of an upload so the wizard can offer header and
	// column-name choices. Nothing is stored by this call.
	previewFile: (file: File, sheet?: string | null, delimiter?: string | null) =>
		requests.postForm<FilePreview>(
			'connections/file/preview',
			fileForm(file, { sheet, delimiter }),
		),

	// Browse the server's configured shared folders. Nothing is read until the
	// operator explicitly previews or creates a connection.
	browseServerPaths: (path?: string | null) =>
		requests.get<ServerPathListing>(
			'connections/file/browse',
			path == null || path === '' ? {} : { path },
		),

	previewServerFile: (path: string, sheet?: string | null, delimiter?: string | null) =>
		requests.post<FilePreview>('connections/file/preview-path', {
			path,
			sheet,
			delimiter,
		}),

	// Stores the upload and registers it as a connection; the backend
	// materialises the chosen shape and triggers ingest.
	createFile: (file: File, input: FileConnectionInput) =>
		requests.postForm<{ data: Connection }>(
			'connections/file',
			fileForm(file, {
				database: input.database,
				sheet: input.sheet,
				delimiter: input.delimiter,
				header_row: input.header_row,
				columns: input.columns,
				keep_columns: input.keep_columns,
			}),
		),

	createServerFile: (input: FileServerPathInput) =>
		requests.post<{ data: Connection }>('connections/file-path', input),

	// Replaces the data behind an existing file connection (keeps its name).
	replaceFile: (databaseName: string, file: File, input: Omit<FileConnectionInput, 'database'>) =>
		requests.putForm<{ data: Connection }>(
			`connections/${encodeURIComponent(databaseName)}/file`,
			fileForm(file, {
				sheet: input.sheet,
				delimiter: input.delimiter,
				header_row: input.header_row,
				columns: input.columns,
				keep_columns: input.keep_columns,
			}),
		),

	replaceServerFile: (databaseName: string, input: Omit<FileServerPathInput, 'database'>) =>
		requests.put<{ data: Connection }>(
			`connections/${encodeURIComponent(databaseName)}/file-path`,
			input,
		),

	// Fetch a REST endpoint once so the wizard can offer the rename step.
	// `replacing` lets an edit reuse the stored token/password while previewing.
	previewApi: (connection: Record<string, unknown>, replacing?: string) =>
		requests.post<ApiPreview>('connections/api/preview', {
			connection,
			...(replacing == null ? {} : { replacing }),
		}),

	createApi: (connection: Record<string, unknown>) =>
		requests.post<{ data: Connection }>('connections/api', { connection }),

	// Rewrites the request settings and fetches the endpoint again.
	updateApi: (databaseName: string, connection: Record<string, unknown>) =>
		requests.put<{ data: Connection }>(`connections/${encodeURIComponent(databaseName)}/api`, {
			connection,
		}),

	// Re-fetches a REST connection with its stored settings.
	refresh: (databaseName: string) =>
		requests.post<{ data: Connection }>(
			`connections/${encodeURIComponent(databaseName)}/refresh`,
		),
};
