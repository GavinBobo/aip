// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { ConnectionType } from '@/enums/connection';

export type DatabricksConnectionParams = {
	type: ConnectionType.DATABRICKS;
	host: string;
	http_path: string;
	password: string;
	database: string;
	/** Optional ingestion allowlist: only these schemas are ingested. Empty/absent = all. */
	schemas?: string[];
	/**
	 * Single schema to ingest, entered on the form instead of picking from a list.
	 * Verified by the connection test, then sent as `schemas`; never persisted itself.
	 */
	schema?: string;
	/**
	 * Run chat queries as the signed-in user by exchanging their SSO token for a
	 * Databricks token, instead of using the stored access token. Ingestion is
	 * unaffected and always uses the stored token.
	 */
	sso_federation?: boolean;
};

export type PostgresConnectionParams = {
	type: ConnectionType.POSTGRESQL;
	host: string;
	port: string;
	user: string;
	password: string;
	database: string;
};

export type MySqlConnectionParams = {
	type: ConnectionType.MYSQL;
	host: string;
	port: string;
	user: string;
	password: string;
	database: string;
};

/**
 * A table uploaded as a spreadsheet, delimited file, or Parquet.
 *
 * The bytes live on the catalog database; the backend materialises them and
 * this record keeps what the operator chose so the edit form can show it.
 */
export type FileConnectionParams = {
	type: ConnectionType.FILE;
	database: string;
	filename: string;
	/** Sheet the data came from, for a workbook. */
	sheet?: string | null;
	/** Separator used for a delimited file; absent means it was detected. */
	delimiter?: string | null;
	/** Zero-based row the column names came from. */
	header_row: number;
	/** Column names in file order, after any renames. */
	columns: string[];
	/** Table name inside the materialised dataset. */
	table: string;
	row_count: number;
	/**
	 * The shared-folder file this connection was loaded from, when it was not
	 * uploaded through the browser. Null for ordinary uploads.
	 */
	source_path?: string | null;
};

export type ServerPathEntry = {
	name: string;
	path: string;
	kind: 'directory' | 'file';
	/** Bytes, for files. */
	size?: number;
	/** One of the configured roots shown at the top of the picker. */
	is_root?: boolean;
};

export type ServerPathListing = {
	roots: string[];
	path: string | null;
	parent: string | null;
	entries: ServerPathEntry[];
};

export type ApiColumn = { source: string; name: string };

export type ApiAuthType = 'none' | 'bearer' | 'basic';

/**
 * A table fetched from a REST endpoint and stored as a snapshot.
 *
 * Request settings are kept as JSON objects; the edit form shows them as text.
 * `token` / `password` are stripped from API responses, so a blank one on save
 * keeps the stored value.
 */
export type ApiConnectionParams = {
	type: ConnectionType.API;
	database: string;
	url: string;
	method: string;
	headers?: Record<string, unknown>;
	params?: Record<string, unknown>;
	body?: unknown;
	records_path?: string;
	auth_type: ApiAuthType;
	token?: string;
	user?: string;
	password?: string;
	timeout_s?: number;
	columns: ApiColumn[];
	row_count: number;
	fetched_at: string;
};

export type MssqlConnectionParams = {
	type: ConnectionType.MSSQL;
	host: string;
	/** Optional named instance, e.g. SQLEXPRESS. */
	instance?: string;
	/** Defaults to 1433 for the default instance when empty. */
	port: string;
	user: string;
	password: string;
	database: string;
	/** ODBC driver name; empty means "newest SQL Server driver installed". */
	driver?: string;
	/** ODBC Encrypt keyword: yes, no, or strict. Empty leaves the driver default. */
	encrypt?: string;
	/** Trust a self-signed server certificate (ODBC Driver 18 encrypts by default). */
	trust_server_certificate?: boolean;
	/** Optional ingestion allowlist: only these schemas are ingested. Empty/absent = all. */
	schemas?: string[];
};

export type SnowflakeConnectionParams = {
	type: ConnectionType.SNOWFLAKE;
	account: string;
	warehouse: string;
	user: string;
	/**
	 * Empty when authenticating with `private_key`. Accounts that enforce MFA
	 * reject password sign-in for person users and forbid passwords on service
	 * users, so a key pair is the only credential an unattended service can use.
	 */
	password?: string;
	/** PEM private key for key-pair authentication, used instead of `password`. */
	private_key?: string;
	/** Only required when `private_key` is encrypted. */
	private_key_passphrase?: string;
	database: string;
	/** Optional ingestion allowlist: only these schemas are ingested. Empty/absent = all. */
	schemas?: string[];
};

export type HeavyDBConnectionParams = {
	type: ConnectionType.HEAVYDB;
	host: string;
	port: string;
	user: string;
	password: string;
	database: string;
	protocol: string;
};

/**
 * Ingestion filters offered on every connector, regardless of type.
 *
 * Enforced centrally at catalog extraction rather than per driver, so they
 * behave the same everywhere. Both are regexes matched unanchored and
 * case-sensitively against the unqualified table name; deny wins over allow.
 */
export type TableFilterParams = {
	/** Ingest only tables matching this. Empty/absent = every table. */
	table_allow_regex?: string;
	/** Skip tables matching this, even when the allowlist matches them too. */
	table_deny_regex?: string;
};

/** Structured connection form fields, discriminated by `type`. */
export type ConnectionParams = (
	| DatabricksConnectionParams
	| ApiConnectionParams
	| FileConnectionParams
	| PostgresConnectionParams
	| MySqlConnectionParams
	| MssqlConnectionParams
	| SnowflakeConnectionParams
	| HeavyDBConnectionParams
) &
	TableFilterParams;

/** A stored connection returned by the API. */
export type Connection = {
	database_name: string;
	connection: ConnectionParams;
};

/** User-provided fields for testing or creating a connection. */
export type ConnectionInput = ConnectionParams;

/** What the preview endpoint reports about an uploaded file. */
export type FilePreview = {
	filename: string;
	format: string;
	/** Sheet names for a workbook; empty otherwise. */
	sheets: string[];
	sheet: string | null;
	/** Separator actually used for a delimited file; null otherwise. */
	delimiter: string | null;
	/** Raw rows, before any header is applied. */
	rows: (string | null)[][];
	row_count: number;
	column_count: number;
	/** Column names at the detected header row. */
	column_names: string[];
	detected_header_row: number;
	/** False for Parquet, which already carries its schema. */
	supports_header_row: boolean;
};

/** What the preview endpoint reports about a REST response. */
export type ApiPreview = {
	rows: (string | null)[][];
	row_count: number;
	column_count: number;
	columns: ApiColumn[];
	url: string;
	method: string;
};
