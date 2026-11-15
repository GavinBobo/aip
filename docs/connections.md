<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Connections and credential storage

Auto-Ontology reads source databases from two places: connections added in the
UI, and the `CONNECTION_STRINGS` environment variable. Use one per deployment,
because the two code paths order them differently:

- **Answering questions** uses UI-managed connections when any exist, and falls
  back to `CONNECTION_STRINGS`.
- **Ingestion** uses `CONNECTION_STRINGS` whenever it's set, and reads
  UI-managed connections only when it's empty.

## Connections added in the UI

Add connections under **Settings → Connections**, or through the API
(`POST /api/connections/test`, then `POST /api/connections`; permission
`connection:manage`).

Each connection can be scoped with a schema allowlist plus
`table_allow_regex` / `table_deny_regex`, applied at catalog extraction. Deny
wins, and names are unqualified and case-sensitive.

Where the credentials live depends on whether Vault is configured:

- **Without Vault.** The full connection object, password included, is
  serialized to JSON and stored unencrypted on the catalog's database row in
  Postgres.
- **With Vault.** Credentials are written to Vault, keyed by database name, and
  the catalog row stores none. The database name is the lookup key.

## `CONNECTION_STRINGS`

A comma- or newline-separated list of connection URLs supplied at deploy time
(`.env` for Docker Compose, `--set connectionStrings=...` for Helm). It carries
no schema or table filters. `GET /api/connections/source` reports whether it is set.

The URL scheme selects the connector:

| Engine        | Scheme                      | Add in the UI |
| ------------- | --------------------------- | :-----------: |
| PostgreSQL    | `postgresql://`, `postgres://` | yes        |
| MySQL         | `mysql://`                  | yes           |
| SQL Server    | `mssql://`, `sqlserver://`  | yes           |
| Databricks    | `databricks://`             | yes           |
| Snowflake     | `snowflake://`              | yes           |
| ClickHouse    | `clickhouse://`             | yes           |
| Trino         | `trino://`                  | yes           |
| Apache Kyuubi | `kyuubi://`                 | yes           |
| HeavyDB       | `heavydb://`                | yes           |
| DuckDB        | `duckdb://`                 | no            |
| SQLite        | `sqlite://`                 | no            |

The registry lives in
[`auto_ontology/connectors/registry.py`](../auto_ontology/connectors/registry.py).

### SQL Server

SQL Server uses SQL authentication over `pyodbc` and needs a Microsoft ODBC
driver on the host running Auto-Ontology: `ODBC Driver 18 for SQL Server`
preferred, 17 accepted. The published backend image installs 18; for a local
run install it from Microsoft's repository for your platform. The driver field
is optional — when empty the connector picks the newest one installed.

```
mssql://USER:PASSWORD@HOST:1433/DATABASE
mssql://USER:PASSWORD@HOST/DATABASE?driver=ODBC+Driver+17+for+SQL+Server
    &trust_server_certificate=yes
```

Path segments are URL-encoded, so a password containing `@`, `/`, or `?` must
be percent-encoded (`p@ss/w0rd` → `p%40ss%2Fw0rd`). ODBC Driver 18 encrypts by
default and rejects a self-signed certificate: set
`trust_server_certificate=yes` (the "Trust Server Certificate" checkbox in the
UI) for an on-premise server whose certificate is not issued by a public CA.
`encrypt=no` is available for a listener that has no TLS at all.

One connection covers one database; schemas inside it (`dbo`, `sales`, …) can
be scoped with the schema picker the connection test returns. Windows and
Microsoft Entra ID authentication are not supported — use a SQL login.

### Files: Excel, CSV, and Parquet

**Settings → Connections → Excel / CSV** turns a file into a queryable source
without a database server. The wizard uploads the file, shows the first rows,
and lets you pick which row holds the column names and rename the columns
before anything is catalogued.

The file picker has two modes. **Upload file** sends a file from the browser.
**Server shared folder** browses and reads a file that is already mounted where
the backend runs, so large or scheduled exports do not have to pass through the
browser. Server-side paths are restricted to `FILE_SOURCE_ROOTS` (a
path-separator- or comma-separated allowlist); when that variable is unset, the
local `./shared` directory is the only root. Symlinks are resolved and rejected
when they point outside an allowlisted root.

- Accepted formats: `.csv`, `.tsv`, `.txt`, `.pcl`, `.xlsx`, `.xls`, `.xlsm`,
  `.parquet`, `.pq`. Delimited files are read as UTF-8 (BOM tolerated) with a
  GB18030 fallback, and the separator is detected.
- `.pcl` is treated as delimited text, like CSV. Its separator varies by the
  tool that wrote it, so the preview offers a **Delimiter** choice — auto-detect
  (default), comma, tab, semicolon, pipe, space, or any single custom
  character. Changing it re-reads the file and refreshes the preview.
- `.pkl` / pickle is deliberately **not** accepted: unpickling executes
  arbitrary code from the file.
- One file becomes one table in one connection. Use one connection per file.
- The connection name must be a plain SQL identifier (letters, digits,
  underscores; not starting with a digit, up to 64 characters). Generated SQL
  names the table as `name.main.table`, so a space or dash in it would produce
  a query the database rejects.
- Uploads are capped at 100 MB, configurable with `FILE_UPLOAD_MAX_BYTES`.
- Server-side files use the same size limit and format checks as uploads. The
  chosen file is copied into the catalog's stored Parquet, so moving or removing
  the original later does not break the connection.

The chosen shape is materialised once as Parquet and stored on the catalog
Postgres database, not on a mounted volume — the API and the ingestion service
run in separate containers/deployments, and a file only one of them could see
would produce a catalog nothing can query. Queries run against it through
DuckDB, exactly as they do for a `duckdb://` source.

Editing a file connection replaces its data: choose the file again (the stored
Parquet is rebuilt and the catalog re-ingested). The connection name is fixed
once created.

### REST APIs

**Settings → Connections → REST API** reads a JSON or CSV endpoint into a
table. Give it a URL, a method (GET or POST), optional headers/query
parameters/JSON body, and one of three auth modes — none, a bearer token, or
basic auth. `Records path` says where the row array sits in the JSON
(`data.items`); leave it empty to detect the usual wrappers (`data`, `items`,
`results`, `rows`, `records`).

- Nested objects are flattened into dotted column names (`profile.country`);
  arrays are kept as JSON text.
- Column renames are matched by the API's field name, so they survive fields
  appearing in a different order.
- The endpoint is called when the connection is created and again whenever you
  press **Refresh Data** on its card. Questions query the stored snapshot, so a
  slow or rate-limited endpoint never sits in the path of an answer. Refreshing
  also rebuilds the catalog.
- One endpoint becomes one table and one connection. Responses are capped at
  100 MB and requests time out after the configured timeout (default 30s, max
  300s).

Creation fetches the endpoint from the Auto-Ontology backend, so the URL must be
reachable from that host. The feature is admin-only (`connection:manage`),
like every other connection write.

## Vault

Vault is off by default. It turns on only when all four of these are set:

- `VAULT_ADDR`
- `VAULT_NAMESPACE`
- `VAULT_ROLE_ID`
- `VAULT_SECRET_ID`

`VAULT_AUTH_MOUNT` and `VAULT_KV_MOUNT` are optional overrides. A partial
configuration is ignored with a warning, and credentials fall back to plaintext
storage in Postgres.
