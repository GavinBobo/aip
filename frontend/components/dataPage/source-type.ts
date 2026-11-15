// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * How a catalog database's source is labelled and grouped in the data tree.
 *
 * `source_type` is the connection type the backend stores (`file`, `api`,
 * `postgresql`, …). Each type is its own group — a file upload and a warehouse
 * are not both merely "databases". Databases configured only through
 * `CONNECTION_STRINGS` have no connection row, so their type is unknown.
 */

import { IconName } from '@/common/icons';

export type SourceKind = {
	/** Stable bucket key, also persisted as part of the folded-group state. */
	group: SourceGroup;
	/** What the group header and the database row badge show. */
	label: string;
	icon: IconName;
};

/** Group keys are connector types, so new engines can appear without a schema change. */
export type SourceGroup = string;

/** File and API sources lead; warehouse engines follow alphabetically. */
export const SOURCE_GROUP_ORDER: SourceGroup[] = [
	'file',
	'api',
	'databricks',
	'clickhouse',
	'duckdb',
	'heavydb',
	'kyuubi',
	'mssql',
	'mysql',
	'postgresql',
	'snowflake',
	'sqlite',
	'trino',
	'unknown',
];

const BY_TYPE: Record<string, SourceKind> = {
	file: { group: 'file', label: 'Excel / CSV', icon: IconName.Upload },
	api: { group: 'api', label: 'REST API', icon: IconName.Link },
	postgresql: { group: 'postgresql', label: 'PostgreSQL', icon: IconName.Database },
	postgres: { group: 'postgresql', label: 'PostgreSQL', icon: IconName.Database },
	mysql: { group: 'mysql', label: 'MySQL', icon: IconName.Database },
	mssql: { group: 'mssql', label: 'SQL Server', icon: IconName.Database },
	sqlserver: { group: 'mssql', label: 'SQL Server', icon: IconName.Database },
	snowflake: { group: 'snowflake', label: 'Snowflake', icon: IconName.Database },
	databricks: { group: 'databricks', label: 'Databricks', icon: IconName.Database },
	clickhouse: { group: 'clickhouse', label: 'ClickHouse', icon: IconName.Database },
	trino: { group: 'trino', label: 'Trino', icon: IconName.Database },
	kyuubi: { group: 'kyuubi', label: 'Apache Kyuubi', icon: IconName.Database },
	heavydb: { group: 'heavydb', label: 'HeavyDB', icon: IconName.Database },
	duckdb: { group: 'duckdb', label: 'DuckDB', icon: IconName.Database },
	sqlite: { group: 'sqlite', label: 'SQLite', icon: IconName.Database },
};

/** Turn an unrecognised connector key into a readable label rather than hiding it. */
function labelForUnknownType(raw: string): string {
	return raw.replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

export const sourceKind = (type?: string | null): SourceKind => {
	const raw = (type ?? '').trim().toLowerCase();
	if (raw === '') {
		return { group: 'unknown', label: 'Unspecified', icon: IconName.Database };
	}
	return (
		BY_TYPE[raw] ?? {
			group: raw,
			label: labelForUnknownType(raw),
			icon: IconName.Database,
		}
	);
};

export const sourceGroupRank = (group: SourceGroup): number => {
	const index = SOURCE_GROUP_ORDER.indexOf(group);
	return index === -1 ? SOURCE_GROUP_ORDER.length : index;
};
