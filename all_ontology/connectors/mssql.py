# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Microsoft SQL Server connector implementing All Ontology's SQLDatabase ABC.

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
import re
import time
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import pyodbc

from all_ontology.catalog.constants import TableTypes
from all_ontology.connectors.base import SQLDatabase, StatementTimeout

logger = logging.getLogger(__name__)

DEFAULT_MSSQL_PORT = 1433

# Login timeout for a new connection. An unreachable host otherwise blocks for
# the driver's default. 30s gives a VPN or an Azure SQL serverless resume room
# to finish without making an unreachable host hang for minutes.
DEFAULT_LOGIN_TIMEOUT_S = 30

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


class MSSQLConnectionError(ValueError):
    """A connection failure with an operator-actionable explanation."""


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_driver(configured: str) -> str:
    """Return *configured*, or the newest SQL Server ODBC driver installed."""
    configured = configured.strip().strip("{}").strip()
    if configured:
        # Honour an explicit name even when this process cannot enumerate
        # drivers (some managed ODBC configurations hide the list). The
        # connection error below still explains how to fix a wrong name.
        return configured
    installed = list(pyodbc.drivers())
    installed_by_name = {name.casefold(): name for name in installed}
    for candidate in DRIVER_PREFERENCE:
        match = installed_by_name.get(candidate.casefold())
        if match is not None:
            if candidate in ("SQL Server", "SQL Server Native Client 11.0"):
                logger.warning(
                    "Using legacy SQL Server ODBC driver %r. Install 'ODBC "
                    "Driver 18 for SQL Server' for TLS and current SQL Server "
                    "features.",
                    match,
                )
            return match
    raise ValueError(
        "No SQL Server ODBC driver found. Install 'ODBC Driver 18 for SQL "
        "Server' (or 17) on the host running All-Ontology, or name an "
        "installed driver in the connection's Driver field. Installed ODBC "
        f"drivers: {sorted(installed) or 'none'}"
    )


def _query_option(query: dict[str, list[str]], *names: str) -> str:
    """Read a query option case- and separator-insensitively.

    People paste SQL Server URLs from other tools, where the option is spelled
    ``TrustServerCertificate`` or ``trustServerCertificate`` rather than the
    snake_case form this project emits. Folding case and separators means those
    URLs keep working instead of silently dropping the TLS setting.
    """
    folded = {
        re.sub(r"[_\-\s]", "", key).casefold(): values[0]
        for key, values in query.items()
        if values
    }
    for name in names:
        value = folded.get(re.sub(r"[_\-\s]", "", name).casefold())
        if value is not None:
            return value.strip()
    return ""


def _split_host(value: str) -> tuple[str, str, str]:
    """Split a host field into ``(host, port, instance)``.

    The Host field is allowed to carry the shapes people copy from SQL Server
    tooling: ``host,1433``, ``host:1433``, ``host\\SQLEXPRESS``, and bracketed
    IPv6. The normal URL parser only understands the last two when they are
    written as URL components, so reconcile them here before building ODBC's
    ``SERVER=`` value.
    """
    host = value.strip()
    if host.casefold().startswith("tcp:"):
        host = host[4:].strip()
    port = ""
    instance = ""

    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            rest = host[end + 1 :].strip()
            host = host[1:end]
            if rest.startswith(":") and rest[1:].isdigit():
                port = rest[1:]
        return host, port, instance

    if "\\" in host:
        host, instance = host.split("\\", 1)
        instance = instance.strip()
        if "," in instance:
            name, _, tail = instance.rpartition(",")
            if name and tail.strip().isdigit():
                instance, port = name.strip(), tail.strip()

    if "," in host:
        head, _, tail = host.rpartition(",")
        if head and tail.strip().isdigit():
            host, port = head, tail.strip()
    elif host.count(":") == 1:
        head, _, tail = host.rpartition(":")
        if head and tail.isdigit():
            host, port = head, tail

    return host.strip(), port, instance


def _normalize_encrypt(value: str) -> str:
    """Normalize the encryption switch without weakening an explicit choice."""
    raw = value.strip().lower()
    if not raw:
        return ""
    aliases = {
        "1": "yes",
        "true": "yes",
        "on": "yes",
        "0": "no",
        "false": "no",
        "off": "no",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in ("yes", "no", "strict", "mandatory", "optional"):
        raise ValueError(
            "SQL Server 'encrypt' must be one of yes, no, strict, mandatory, "
            f"optional, true, or false; got {value!r}"
        )
    return normalized


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

    host, embedded_port, embedded_instance = _split_host(parsed.hostname)
    instance = _query_option(query, "instance", "instance_name") or embedded_instance
    instance = instance.lstrip("\\").strip()

    # A named instance resolves its own dynamic port through SQL Browser. Only
    # add 1433 for the default instance, or when the caller named a port.
    port: int | None
    query_port = _query_option(query, "port")
    if parsed.port is not None:
        port = parsed.port
    elif query_port:
        try:
            port = int(query_port)
        except ValueError as exc:
            raise ValueError(
                f"SQL Server port must be an integer; got {query_port!r}"
            ) from exc
    elif embedded_port:
        port = int(embedded_port)
    elif instance:
        port = None
    else:
        port = DEFAULT_MSSQL_PORT

    return {
        "host": host,
        "port": port,
        "instance": instance,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "driver": unquote(_query_option(query, "driver")),
        "encrypt": _normalize_encrypt(_query_option(query, "encrypt")),
        "trust_server_certificate": _truthy(
            _query_option(query, "trust_server_certificate", "trustServerCertificate")
        ),
    }


def _brace(value: str) -> str:
    """Wrap a value for an ODBC connection string, doubling literal braces."""
    return "{" + value.replace("}", "}}") + "}"


def _odbc_connection_string(fields: dict[str, Any]) -> str:
    """Build the semicolon-delimited string ``pyodbc.connect`` expects."""
    host = str(fields["host"])
    # ODBC needs brackets around an IPv6 literal; without them the commas in
    # ``tcp:::1,1433`` are parsed as the port separator.
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if fields.get("instance"):
        host += f"\\{fields['instance']}"
    if fields.get("port") is not None:
        host += f",{fields['port']}"
    server = f"tcp:{host}"
    parts = [
        f"DRIVER={_brace(_resolve_driver(fields['driver']))}",
        f"SERVER={_brace(server)}",
        f"DATABASE={_brace(fields['database'])}",
        f"UID={_brace(fields['user'])}",
        f"PWD={_brace(fields['password'])}",
        "APP=all-ontology",
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


def _connection_target(fields: dict[str, Any]) -> str:
    """Describe the endpoint without credentials, for an error message."""
    target = str(fields.get("host") or "")
    if fields.get("instance"):
        target += f"\\{fields['instance']}"
    if fields.get("port") is not None:
        target += f",{fields['port']}"
    return target or "the configured SQL Server"


def _redact_driver_detail(text: str) -> str:
    """Strip a password if a driver ever echoes the connection string."""
    return re.sub(
        r"(?i)\b(?:pwd|password)\s*=\s*(?:\{[^}]*\}|[^;]*)",
        "PWD=***",
        text,
    )


def _connection_error_message(exc: pyodbc.Error, fields: dict[str, Any]) -> str:
    """Turn the driver's terse ODBC error into an operator-facing diagnosis.

    ODBC reports host lookup failures, TLS trust problems, and credential
    problems through similarly shaped ``OperationalError`` values. The raw
    message is kept at the end, but the hint names the setting most likely to
    fix the failure so the connection test is actionable.
    """
    detail = _redact_driver_detail(
        " ".join(str(part) for part in exc.args if part)
    )
    text = detail.casefold()
    sqlstate = str(exc.args[0]).strip().upper() if exc.args else ""
    target = _connection_target(fields)

    hint = ""
    if (
        sqlstate == "IM002"
        or "data source name not found" in text
        or "driver not found" in text
    ):
        try:
            installed = sorted(pyodbc.drivers())
        except Exception:  # pragma: no cover - driver manager unavailable
            installed = []
        hint = (
            "The ODBC driver is missing or its name is wrong. Install "
            "'ODBC Driver 18 for SQL Server' on the All-Ontology host, or "
            "select an installed driver in the Driver field. Installed ODBC "
            f"drivers: {installed or 'none'}."
        )
    elif (
        "certificate chain was issued by an authority that is not trusted" in text
        or "ssl provider" in text
        or "certificate verify failed" in text
        or "self-signed certificate" in text
        or "protocol version" in text
        or "tls10" in text
    ):
        hint = (
            "TLS certificate validation failed. For an on-premise server with "
            "a self-signed certificate, enable 'Trust Server Certificate'. If "
            "the listener has no TLS at all, set Encryption to 'no'."
        )
    elif "cannot open database" in text or "4060" in text:
        hint = (
            "The login reached SQL Server but cannot open the named database. "
            "Check the database name and that the login has CONNECT permission."
        )
    elif (
        "login failed for user" in text
        or "18456" in text
        or sqlstate == "28000"
    ):
        hint = (
            "SQL authentication was rejected. Confirm the login exists, mixed "
            "mode authentication is enabled, and the user/password are correct."
        )
    elif (
        "server was not found or was not accessible" in text
        or "tcp provider" in text
        or "connection refused" in text
        or "could not open a connection" in text
        or "error: 40" in text
        or "network-related" in text
        or sqlstate in ("08001", "08S01")
    ):
        hint = (
            "The host/port is unreachable from the All-Ontology container or "
            "service. Check the server address, firewall, and port; for a "
            "named instance either give its fixed port or make SQL Browser "
            "(UDP 1434) reachable."
        )
    elif "timeout expired" in text or "login timeout" in text:
        hint = (
            "The login timed out. Check that the host is reachable and that "
            "the SQL Server is not overloaded."
        )
    elif "invalid connection string attribute" in text:
        if fields.get("encrypt") in ("mandatory", "optional"):
            hint = (
                "This ODBC driver does not accept Encrypt=mandatory/optional. "
                "Use Encrypt=yes or Encrypt=no."
            )
        else:
            hint = (
                "The selected ODBC driver does not understand one of the "
                "connection options. Use 'ODBC Driver 18 for SQL Server' for "
                "Encrypt/TrustServerCertificate support."
            )
    else:
        hint = (
            "Check the host, port, instance name, credentials, and that the "
            "SQL Server accepts TCP connections."
        )

    return (
        f"Could not connect to SQL Server {target}. {hint} "
        f"Driver message: {detail or exc.__class__.__name__}"
    )


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
        try:
            connection = pyodbc.connect(
                self._odbc_string,
                autocommit=True,
                timeout=DEFAULT_LOGIN_TIMEOUT_S,
            )
        except pyodbc.Error as exc:
            raise MSSQLConnectionError(
                _connection_error_message(exc, getattr(self, "_fields", {}))
            ) from exc
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
                if not parameters:
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
        except (pyodbc.Error, MSSQLConnectionError) as exc:
            logger.info(
                "SQL Server query history unavailable for %s: %s",
                self._database_name,
                exc,
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
                try:
                    cursor.execute("SELECT 1")
                except pyodbc.Error as exc:
                    # The socket can die between connect and the probe. Report
                    # that the same way as a login failure rather than leaking
                    # a bare ODBC tuple to the connection-test UI.
                    raise MSSQLConnectionError(
                        _connection_error_message(exc, getattr(self, "_fields", {}))
                    ) from exc
            finally:
                cursor.close()
        finally:
            connection.close()

    def close(self) -> None:
        """No-op because each operation owns and closes its connection."""
