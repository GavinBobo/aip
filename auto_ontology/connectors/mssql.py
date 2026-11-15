# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Microsoft SQL Server connector implementing Auto Ontology's SQLDatabase ABC.

Uses ``pyodbc`` and the Microsoft ODBC driver. SQL Server is a three-part
namespace (``database.schema.table``) but the connection string binds the
database, so the base class's two-level ``schema.table`` qualification is
correct and :meth:`MSSQLDatabase.qualify` is not overridden.

``dialect`` reports ``"tsql"``: that is the name sqlglot knows, and every
caller (prompt construction, parsing, identifier quoting) passes it straight
through with no translation layer.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import pyodbc

from auto_ontology.catalog.constants import TableTypes
from auto_ontology.connectors.base import SQLDatabase, StatementTimeout

logger = logging.getLogger(__name__)

DEFAULT_MSSQL_PORT = 1433

# ODBC drivers tried in order when the connection does not name one. The
# Microsoft drivers are versioned and not every host has the newest; the bare
# "SQL Server" driver ships with Windows and is the last resort (it predates
# TLS-by-default, so it is only picked when nothing newer exists).
DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)

# SQLSTATEs pyodbc reports when the server/client stopped a statement at the
# query timeout: ``HYT00`` is "timeout expired", ``S1T00`` is the ODBC 3.x
# spelling of the same condition.
_TIMEOUT_SQLSTATES = frozenset({"HYT00", "S1T00"})

# Schemas every database carries that are never part of a customer's model:
# the system catalogue, the metadata views, and the ``guest`` login's schema
# (objects there are visible to every login, which is why good practice keeps
# it empty). User schemas all have a ``schema_id`` below 16384; database-role
# schemas start there.
_SYSTEM_SCHEMAS = ("sys", "INFORMATION_SCHEMA", "guest")
_MAX_USER_SCHEMA_ID = 16384


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_driver(configured: str) -> str:
    """Return *configured*, or the newest SQL Server ODBC driver installed."""
    if configured:
        return configured
    installed = set(pyodbc.drivers())
    for candidate in DRIVER_PREFERENCE:
        if candidate in installed:
            return candidate
    raise ValueError(
        "No SQL Server ODBC driver found. Install 'ODBC Driver 18 for SQL "
        "Server' (or 17) on the host running Auto-Ontology, or name an "
        "installed driver in the connection's Driver field. Installed ODBC "
        f"drivers: {sorted(installed) or 'none'}"
    )


def _parse_connection_string(connection_string: str) -> dict[str, Any]:
    """Convert an ``mssql://`` URL into the fields the ODBC string needs.

    Expected formats::

        mssql://USER:PASSWORD@HOST:1433/DATABASE
        mssql://USER:PASSWORD@HOST/DATABASE?driver=ODBC+Driver+18+for+SQL+Server
            &trust_server_certificate=yes

    ``mssql+pyodbc://`` and ``sqlserver://`` are accepted as aliases.
    """
    parsed = urlparse(connection_string)
    scheme = parsed.scheme.split("+", 1)[0].lower()
    if scheme not in ("mssql", "sqlserver"):
        raise ValueError(f"Invalid SQL Server connection string: {connection_string!r}")
    if not parsed.hostname:
        raise ValueError("SQL Server connection string is missing a host")

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("SQL Server connection string is missing a database")

    query = parse_qs(parsed.query)

    def first(key: str) -> str:
        return (query.get(key, [""])[0] or "").strip()

    encrypt = first("encrypt").lower()
    if encrypt and encrypt not in ("yes", "no", "strict", "mandatory", "optional"):
        raise ValueError(
            "SQL Server 'encrypt' must be one of yes, no, optional, mandatory, "
            f"strict; got {encrypt!r}"
        )

    return {
        "host": parsed.hostname,
        "port": parsed.port or DEFAULT_MSSQL_PORT,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "driver": unquote(first("driver")),
        "encrypt": encrypt,
        "trust_server_certificate": _truthy(first("trust_server_certificate")),
    }


def _brace(value: str) -> str:
    """Wrap a value for an ODBC connection string, doubling literal braces."""
    return "{" + value.replace("}", "}}") + "}"


def _odbc_connection_string(fields: dict[str, Any]) -> str:
    """Build the semicolon-delimited string ``pyodbc.connect`` expects."""
    server = f"tcp:{fields['host']},{fields['port']}"
    parts = [
        f"DRIVER={_brace(_resolve_driver(fields['driver']))}",
        f"SERVER={_brace(server)}",
        f"DATABASE={_brace(fields['database'])}",
        f"UID={_brace(fields['user'])}",
        f"PWD={_brace(fields['password'])}",
        "APP=auto-ontology",
    ]
    if fields["encrypt"]:
        parts.append(f"Encrypt={_brace(fields['encrypt'])}")
    if fields["trust_server_certificate"]:
        # ODBC Driver 18 encrypts by default and rejects a self-signed server
        # certificate. Trusting it is the usual on-premise setup, but it is an
        # explicit opt-in because it disables the certificate identity check.
        parts.append("TrustServerCertificate=yes")
    return ";".join(parts)


def _is_timeout(exc: pyodbc.Error) -> bool:
    """Whether *exc* is the query timeout, not some other ODBC failure."""
    sqlstate = str(exc.args[0]).strip().upper() if exc.args else ""
    return sqlstate in _TIMEOUT_SQLSTATES or "timeout expired" in str(exc).lower()


class MSSQLDatabase(SQLDatabase):
    """Concrete :class:`SQLDatabase` backed by SQL Server via ``pyodbc``."""

    supports_statement_timeout = True

    def __init__(
        self,
        connection_string: str,
        schemas: list[str] | None = None,
    ) -> None:
        self._connection_string = connection_string
        self._fields = _parse_connection_string(connection_string)
        self._database_name = str(self._fields["database"])
        self._odbc_string = _odbc_connection_string(self._fields)
        # Ingestion allowlist. ``None`` means every visible user schema.
        self._schema_filter: list[str] | None = (
            [schema.strip() for schema in schemas if schema.strip()]
            if schemas
            else None
        )
        self.ping()

    @property
    def dialect(self) -> str:
        return "tsql"

    @property
    def database_name(self) -> str:
        return self._database_name

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self, timeout_s: float | None = None) -> pyodbc.Connection:
        """Open one connection, applying *timeout_s* as its query timeout."""
        # ``timeout`` here is the login timeout; the query cap is set on the
        # connection below. Both matter: an unreachable host otherwise blocks
        # for the driver's 15-30s default before any statement runs.
        connection = pyodbc.connect(self._odbc_string, autocommit=True, timeout=15)
        if timeout_s is not None:
            # pyodbc's Connection.timeout is the per-connection query timeout,
            # so a fresh connection per statement keeps the cap from leaking
            # onto the next query.
            connection.timeout = max(1, int(math.ceil(timeout_s)))
        return connection

    def _schema_clause(self) -> tuple[str, list[str]]:
        """``AND s.name IN (...)`` for the ingestion allowlist, if set."""
        if not self._schema_filter:
            return "", []
        placeholders = ", ".join("?" for _ in self._schema_filter)
        return f" AND s.name IN ({placeholders})", list(self._schema_filter)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        sql: str,
        parameters: Optional[list] = None,
        *,
        timeout_s: float | None = None,
    ) -> pd.DataFrame:
        """Run *sql*; with *timeout_s*, the client stops it after that long.

        SQL Server has no per-session statement timeout, so the cap is the ODBC
        query timeout on this call's own connection.

        Raises:
            StatementTimeout: the statement exceeded the cap and was cancelled.
        """
        connection = self._connect(timeout_s)
        try:
            cursor = connection.cursor()
            started = time.monotonic()
            try:
                # pyodbc binds positionally with ``?``; ``None`` must be passed
                # as no parameters rather than an empty sequence, which pyodbc
                # rejects for statements that have no placeholders.
                if parameters is None:
                    cursor.execute(sql)
                else:
                    cursor.execute(sql, parameters)
                if cursor.description is None:
                    return pd.DataFrame()
                columns = [description[0] for description in cursor.description]
                rows = cursor.fetchall()
                return pd.DataFrame.from_records(rows, columns=columns)
            except pyodbc.Error as exc:
                if timeout_s is not None and _is_timeout(exc):
                    raise StatementTimeout.since(timeout_s, started) from exc
                raise
            finally:
                cursor.close()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def _relation_scope(self) -> tuple[str, list[str]]:
        """WHERE-clause fragment selecting user tables and views.

        Shared by :meth:`get_tables` and :meth:`get_columns` on purpose: the
        catalog fails closed when a listed relation has no column rows, so the
        two queries have to describe exactly the same set.

        ``is_ms_shipped = 0`` hides system objects; ``schema_id < 16384`` drops
        the database roles that ``sys.schemas`` also reports; and the type
        filter keeps ordinary tables (``U``), views (``V``) and external tables
        (``ET``), leaving out internal tables (``IT``) and synonyms (``SN``).
        """
        schema_clause, params = self._schema_clause()
        scope = (
            "WHERE o.type IN ('U', 'V', 'ET')"
            " AND o.is_ms_shipped = 0"
            f" AND s.schema_id < {_MAX_USER_SCHEMA_ID}"
            " AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')" + schema_clause
        )
        return scope, params

    def get_tables(self) -> pd.DataFrame:
        view_type = TableTypes.VIEW
        base_table_type = TableTypes.BASE_TABLE
        scope, params = self._relation_scope()
        return self.execute(
            f"""
            SELECT
                s.name AS table_schema,
                o.name AS table_name,
                CASE WHEN o.type = 'V' THEN '{view_type}'
                     ELSE '{base_table_type}' END AS table_type
            FROM sys.objects AS o
            JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            {scope}
            ORDER BY s.name, o.name
            """,
            params or None,
        )

    def get_columns(self) -> pd.DataFrame:
        """Columns with their declared type spelled as ``nvarchar(50)``.

        ``sys.types.name`` plus the length/precision/scale columns gives the
        model the same string its DDL would use, which is what the text-to-SQL
        prompt needs to write valid casts and comparisons.
        """
        scope, params = self._relation_scope()
        return self.execute(
            f"""
            SELECT
                s.name AS table_schema,
                o.name AS table_name,
                c.name AS column_name,
                ty.name + CASE
                    WHEN ty.name IN ('nvarchar', 'nchar') THEN
                        '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                   ELSE CONVERT(varchar(10), c.max_length / 2)
                              END + ')'
                    WHEN ty.name IN ('varchar', 'char', 'varbinary', 'binary') THEN
                        '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                   ELSE CONVERT(varchar(10), c.max_length)
                              END + ')'
                    WHEN ty.name IN ('decimal', 'numeric') THEN
                        '(' + CONVERT(varchar(10), c.precision) + ',' +
                        CONVERT(varchar(10), c.scale) + ')'
                    WHEN ty.name IN ('datetime2', 'time', 'datetimeoffset') THEN
                        '(' + CONVERT(varchar(10), c.scale) + ')'
                    ELSE ''
                END AS data_type,
                c.is_nullable AS is_nullable,
                c.column_id AS ordinal_position
            FROM sys.columns AS c
            JOIN sys.objects AS o ON o.object_id = c.object_id
            JOIN sys.schemas AS s ON s.schema_id = o.schema_id
            JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
            {scope}
            ORDER BY s.name, o.name, c.column_id
            """,
            params or None,
        )

    def get_views(self) -> pd.DataFrame:
        schema_clause, params = self._schema_clause()
        return self.execute(
            f"""
            SELECT
                s.name AS table_schema,
                v.name AS table_name,
                m.definition AS view_definition
            FROM sys.views AS v
            JOIN sys.schemas AS s ON s.schema_id = v.schema_id
            LEFT JOIN sys.sql_modules AS m ON m.object_id = v.object_id
            WHERE v.is_ms_shipped = 0
              AND s.schema_id < {_MAX_USER_SCHEMA_ID}
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
              {schema_clause}
            ORDER BY s.name, v.name
            """,
            params or None,
        )

    def get_queries(self, hours: int = 24) -> pd.DataFrame:
        """Recent statements from the plan cache, when the login may read it.

        ``sys.dm_exec_query_stats`` needs VIEW SERVER STATE. Ingestion must not
        fail because a least-privilege login lacks it, so a refused DMV read
        degrades to an empty history — the same contract MySQL's connector
        keeps.
        """
        try:
            return self.execute(
                """
                SELECT TOP (500)
                    qs.last_execution_time AS end_time,
                    st.text AS query_text
                FROM sys.dm_exec_query_stats AS qs
                CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
                WHERE qs.last_execution_time >= DATEADD(hour, ?, SYSDATETIME())
                  AND st.text IS NOT NULL
                ORDER BY qs.last_execution_time DESC
                """,
                [-int(hours)],
            )
        except pyodbc.Error:
            logger.info(
                "SQL Server query history unavailable for %s (VIEW SERVER STATE?)",
                self._database_name,
            )
            return pd.DataFrame(columns=["end_time", "query_text"])

    def get_pks(self) -> pd.DataFrame:
        schema_clause, params = self._schema_clause()
        return self.execute(
            f"""
            SELECT
                s.name AS table_schema,
                t.name AS table_name,
                c.name AS column_name,
                ic.key_ordinal AS ordinal_position
            FROM sys.key_constraints AS kc
            JOIN sys.tables AS t ON t.object_id = kc.parent_object_id
            JOIN sys.schemas AS s ON s.schema_id = t.schema_id
            JOIN sys.index_columns AS ic
              ON ic.object_id = kc.parent_object_id
             AND ic.index_id = kc.unique_index_id
            JOIN sys.columns AS c
              ON c.object_id = ic.object_id
             AND c.column_id = ic.column_id
            WHERE kc.type = 'PK'
              AND t.is_ms_shipped = 0
              AND s.schema_id < {_MAX_USER_SCHEMA_ID}
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
              {schema_clause}
            ORDER BY s.name, t.name, ic.key_ordinal
            """,
            params or None,
        )

    def get_fks(self) -> pd.DataFrame:
        schema_clause, params = self._schema_clause()
        return self.execute(
            f"""
            SELECT
                s.name AS table_schema,
                tp.name AS table_name,
                cp.name AS column_name,
                sr.name AS referenced_schema,
                tr.name AS referenced_table,
                cr.name AS referenced_column
            FROM sys.foreign_key_columns AS fkc
            JOIN sys.tables AS tp ON tp.object_id = fkc.parent_object_id
            JOIN sys.schemas AS s ON s.schema_id = tp.schema_id
            JOIN sys.columns AS cp
              ON cp.object_id = fkc.parent_object_id
             AND cp.column_id = fkc.parent_column_id
            JOIN sys.tables AS tr ON tr.object_id = fkc.referenced_object_id
            JOIN sys.schemas AS sr ON sr.schema_id = tr.schema_id
            JOIN sys.columns AS cr
              ON cr.object_id = fkc.referenced_object_id
             AND cr.column_id = fkc.referenced_column_id
            WHERE tp.is_ms_shipped = 0
              AND s.schema_id < {_MAX_USER_SCHEMA_ID}
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
              {schema_clause}
            ORDER BY s.name, tp.name, cp.name
            """,
            params or None,
        )

    def get_schemas(self) -> list[str]:
        """User schemas visible to this login, for the UI schema picker."""
        frame = self.execute(
            f"""
            SELECT s.name AS schema_name
            FROM sys.schemas AS s
            WHERE s.schema_id < {_MAX_USER_SCHEMA_ID}
              AND s.name NOT IN ({", ".join("'" + name + "'" for name in _SYSTEM_SCHEMAS)})
            ORDER BY s.name
            """
        )
        return [str(value) for value in frame["schema_name"].tolist()]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ping(self) -> None:
        """Verify connectivity, credentials, and that the database is reachable."""
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
            finally:
                cursor.close()
        finally:
            connection.close()

    def close(self) -> None:
        """No-op because each operation owns and closes its connection."""
