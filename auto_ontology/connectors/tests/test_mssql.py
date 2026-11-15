# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
from typing import Any

import pandas as pd
import pyodbc
import pytest
from pytest import MonkeyPatch

from auto_ontology.connectors.base import StatementTimeout
from auto_ontology.connectors.connection_string_factory import build_connection_string
from auto_ontology.connectors.mssql import (
    MSSQLDatabase,
    _odbc_connection_string,
    _parse_connection_string,
)
from auto_ontology.connectors.registry import create_connector


def _connection_string(password: str = "secret") -> str:
    # An explicit driver keeps the unit tests independent of which ODBC
    # drivers happen to be installed on the machine running them.
    return (
        f"mssql://user:{password}@localhost:1433/beaver"
        "?driver=ODBC+Driver+18+for+SQL+Server"
    )


def test_parse_connection_string() -> None:
    fields = _parse_connection_string(
        "mssql://user%40domain:secret%2Fvalue@example.com:1434/Beaver%20DB"
        "?driver=ODBC+Driver+17+for+SQL+Server"
        "&trust_server_certificate=yes&encrypt=yes"
    )

    assert fields == {
        "host": "example.com",
        "port": 1434,
        "user": "user@domain",
        "password": "secret/value",
        "database": "Beaver DB",
        "driver": "ODBC Driver 17 for SQL Server",
        "encrypt": "yes",
        "trust_server_certificate": True,
    }


def test_parse_connection_string_defaults_the_port() -> None:
    fields = _parse_connection_string("sqlserver://sa:pw@db.example.com/master")

    assert fields["port"] == 1433
    assert fields["database"] == "master"
    assert fields["driver"] == ""
    assert fields["trust_server_certificate"] is False


@pytest.mark.parametrize(
    "url",
    [
        "mssql://sa:pw@db.example.com/sales",
        "sqlserver://sa:pw@db.example.com/sales",
        # The registry keys off the scheme before ``+``, so the SQLAlchemy-style
        # spelling people paste from other tools has to work too.
        "mssql+pyodbc://sa:pw@db.example.com/sales",
    ],
)
def test_scheme_aliases_all_parse(url: str) -> None:
    fields = _parse_connection_string(url)

    assert fields["host"] == "db.example.com"
    assert fields["database"] == "sales"


def test_parse_connection_string_requires_a_database() -> None:
    with pytest.raises(ValueError, match="missing a database"):
        _parse_connection_string("mssql://sa:pw@localhost")


def test_parse_connection_string_rejects_an_unknown_encrypt_value() -> None:
    with pytest.raises(ValueError, match="encrypt"):
        _parse_connection_string("mssql://sa:pw@localhost/db?encrypt=sometimes")


def test_build_connection_string_round_trips_through_the_parser() -> None:
    connection_string = build_connection_string(
        {
            "type": "mssql",
            "host": "localhost",
            "port": "1434",
            "user": "user@domain",
            "password": "secret/value",
            "database": "beaver db",
            "driver": "ODBC Driver 18 for SQL Server",
            "trust_server_certificate": True,
        }
    )

    assert connection_string.startswith(
        "mssql://user%40domain:secret%2Fvalue@localhost:1434/beaver%20db?"
    )
    fields = _parse_connection_string(connection_string)
    assert fields["user"] == "user@domain"
    assert fields["password"] == "secret/value"
    assert fields["database"] == "beaver db"
    assert fields["trust_server_certificate"] is True


def test_build_connection_string_uses_the_default_port() -> None:
    connection_string = build_connection_string(
        {
            "type": "sqlserver",
            "host": "db",
            "user": "sa",
            "password": "pw",
            "database": "master",
        }
    )

    assert connection_string == "mssql://sa:pw@db:1433/master"


def test_odbc_connection_string_braces_values_and_sets_tls_options() -> None:
    connection = _odbc_connection_string(
        {
            "host": "db.example.com",
            "port": 1433,
            "user": "sa",
            "password": "p;w}d",
            "database": "sales db",
            "driver": "ODBC Driver 18 for SQL Server",
            "encrypt": "",
            "trust_server_certificate": True,
        }
    )

    assert "DRIVER={ODBC Driver 18 for SQL Server}" in connection
    assert "SERVER={tcp:db.example.com,1433}" in connection
    assert "DATABASE={sales db}" in connection
    # A literal ``;`` and ``}`` in a password must not break the string.
    assert "PWD={p;w}}d}" in connection
    assert "TrustServerCertificate=yes" in connection


def test_odbc_connection_string_prefers_the_newest_installed_driver(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.drivers",
        lambda: ["SQL Server", "ODBC Driver 17 for SQL Server"],
    )

    connection = _odbc_connection_string(
        {
            "host": "db",
            "port": 1433,
            "user": "sa",
            "password": "pw",
            "database": "master",
            "driver": "",
            "encrypt": "",
            "trust_server_certificate": False,
        }
    )

    assert "DRIVER={ODBC Driver 17 for SQL Server}" in connection


def test_missing_driver_names_what_to_install(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.drivers", lambda: ["SQLite3"]
    )

    with pytest.raises(ValueError, match="No SQL Server ODBC driver"):
        _odbc_connection_string(
            {
                "host": "db",
                "port": 1433,
                "user": "sa",
                "password": "pw",
                "database": "master",
                "driver": "",
                "encrypt": "",
                "trust_server_certificate": False,
            }
        )


def test_registry_creates_mssql_connector(monkeypatch: MonkeyPatch) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("auto_ontology.connectors.mssql.pyodbc.connect", connect)

    database = create_connector(_connection_string())

    assert isinstance(database, MSSQLDatabase)
    assert database.dialect == "tsql"
    assert database.database_name == "beaver"
    assert connections[0].pinged
    assert connections[0].closed


def test_execute_returns_a_dataframe_and_closes_everything(
    monkeypatch: MonkeyPatch,
) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("auto_ontology.connectors.mssql.pyodbc.connect", connect)
    database = MSSQLDatabase(_connection_string())

    result = database.execute("SELECT ? AS value", [1])

    assert result.to_dict(orient="records") == [{"value": 1}]
    executed = connections[1].cursor_instance.executed
    assert executed == ("SELECT ? AS value", [1])
    assert connections[1].cursor_instance.closed
    assert connections[1].closed


def test_execute_sets_the_query_timeout_on_its_own_connection(
    monkeypatch: MonkeyPatch,
) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("auto_ontology.connectors.mssql.pyodbc.connect", connect)
    database = MSSQLDatabase(_connection_string())

    database.execute("SELECT 1", timeout_s=30)
    database.execute("SELECT 1")

    assert connections[1].timeout == 30
    # The cap belongs to that statement's connection only; the next one is
    # opened fresh, so nothing leaks onto it.
    assert connections[2].timeout == 0


@pytest.mark.parametrize("sqlstate", ["HYT00", "S1T00"])
def test_timeout_sqlstates_become_statement_timeouts(
    monkeypatch: MonkeyPatch, sqlstate: str
) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect",
        lambda *_a, **_k: Connection(fail=pyodbc.OperationalError(sqlstate, "expired")),
    )
    # Built without __init__: its connectivity ping would raise the same
    # timeout before the statement under test ran.
    database = MSSQLDatabase.__new__(MSSQLDatabase)
    database._odbc_string = "DRIVER={x}"
    database._database_name = "beaver"
    database._schema_filter = None

    with pytest.raises(StatementTimeout):
        database.execute("SELECT 1", timeout_s=5)


def test_other_driver_errors_are_left_alone(monkeypatch: MonkeyPatch) -> None:
    error = pyodbc.ProgrammingError("42S02", "Invalid object name 'nope'")
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect",
        lambda *_a, **_k: Connection(fail=error),
    )
    database = MSSQLDatabase.__new__(MSSQLDatabase)
    database._odbc_string = "DRIVER={x}"
    database._database_name = "beaver"
    database._schema_filter = None

    with pytest.raises(pyodbc.ProgrammingError):
        database.execute("SELECT * FROM nope", timeout_s=5)


def test_introspection_pushes_the_schema_allowlist_down(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string(), schemas=["dbo", "sales"])
    captured: list[tuple[str, list[str] | None]] = []

    def execute(
        sql: str, parameters: list[str] | None = None, **_kwargs: Any
    ) -> pd.DataFrame:
        captured.append((sql, parameters))
        return pd.DataFrame(columns=["table_schema", "table_name", "table_type"])

    monkeypatch.setattr(database, "execute", execute)
    database.get_tables()
    database.get_columns()

    assert all("s.name IN (?, ?)" in sql for sql, _ in captured)
    assert all(params == ["dbo", "sales"] for _, params in captured)


def test_introspection_scopes_to_user_tables_and_views(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string())
    captured: list[str] = []

    def execute(sql: str, parameters: list[str] | None = None) -> pd.DataFrame:
        captured.append(sql)
        return pd.DataFrame(columns=["x"])

    monkeypatch.setattr(database, "execute", execute)
    database.get_tables()
    database.get_columns()
    database.get_pks()
    database.get_fks()
    database.get_views()

    # Both relation queries must agree on the relation set, or catalog
    # extraction fails closed on the relations one lists but the other cannot
    # describe.
    for sql in captured[:2]:
        assert "o.type IN ('U', 'V', 'ET')" in sql
        assert "o.is_ms_shipped = 0" in sql
        assert "s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')" in sql


def test_get_schemas_returns_names(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string())
    monkeypatch.setattr(
        database,
        "execute",
        lambda *_a, **_k: pd.DataFrame({"schema_name": ["dbo", "sales"]}),
    )

    assert database.get_schemas() == ["dbo", "sales"]


def test_query_history_degrades_to_empty_without_permission(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string())

    def denied(*_args: Any, **_kwargs: Any) -> pd.DataFrame:
        raise pyodbc.ProgrammingError("42000", "permission denied")

    monkeypatch.setattr(database, "execute", denied)

    result = database.get_queries()
    assert list(result.columns) == ["end_time", "query_text"]
    assert result.empty


def _live_connection() -> dict[str, Any]:
    # Opt in explicitly so pytest never dials a real server just because
    # MSSQL_* happens to be exported in the shell.
    if os.environ.get("AUTO_ONTOLOGY_LIVE_MSSQL") != "1":
        pytest.skip("Set AUTO_ONTOLOGY_LIVE_MSSQL=1 to run the live SQL Server test")

    environment_fields = {
        "host": "MSSQL_HOST",
        "user": "MSSQL_USER",
        "password": "MSSQL_PASSWORD",
        "database": "MSSQL_DATABASE",
    }
    missing = [
        environment_name
        for environment_name in environment_fields.values()
        if not os.environ.get(environment_name)
    ]
    if missing:
        pytest.skip(
            "Live SQL Server credentials are not configured: " + ", ".join(missing)
        )

    connection: dict[str, Any] = {
        "type": "mssql",
        **{
            field: os.environ[environment_name]
            for field, environment_name in environment_fields.items()
        },
    }
    for field, environment_name in (
        ("port", "MSSQL_PORT"),
        ("driver", "MSSQL_DRIVER"),
    ):
        if os.environ.get(environment_name):
            connection[field] = os.environ[environment_name]
    if os.environ.get("MSSQL_TRUST_SERVER_CERTIFICATE") == "1":
        connection["trust_server_certificate"] = True
    return connection


def test_live_mssql_connector_end_to_end() -> None:
    connection = _live_connection()
    database = create_connector(build_connection_string(connection))

    try:
        assert isinstance(database, MSSQLDatabase)
        assert database.dialect == "tsql"
        assert database.database_name == connection["database"]

        database.ping()
        assert database.execute("SELECT 1 AS value").iloc[0]["value"] == 1
        assert database.execute("SELECT ? AS value", ["x"]).iloc[0]["value"] == "x"

        metadata_frames = [
            database.get_tables(),
            database.get_columns(),
            database.get_views(),
            database.get_pks(),
            database.get_fks(),
            database.get_queries(),
        ]
        assert all(isinstance(frame, pd.DataFrame) for frame in metadata_frames)

        tables = database.get_tables()
        assert not tables.empty
        assert set(tables.columns) == {"table_schema", "table_name", "table_type"}
        assert set(tables["table_type"]) <= {"base table", "view"}

        columns = database.get_columns()
        assert not columns.empty
        assert set(columns["table_name"]) <= set(tables["table_name"])
        # The declared type is rendered the way the DDL spells it, not as a
        # bare ODBC type code.
        assert columns["data_type"].astype(str).str.contains(r"\(").any()
        assert columns["is_nullable"].dtype == bool

        table = tables.iloc[0]
        qualified = f"[{table['table_schema']}].[{table['table_name']}]"
        assert (
            database.execute(f"SELECT COUNT(*) AS n FROM {qualified}").iloc[0]["n"] >= 0
        )
    finally:
        database.close()


class Cursor:
    description = [("value",)]
    executed: tuple[str, list[int] | None] | None = None
    closed = False

    def __init__(self, fail: Exception | None = None) -> None:
        self._fail = fail

    def execute(self, statement: str, parameters: list[int] | None = None) -> None:
        if self._fail is not None:
            raise self._fail
        self.executed = (statement, parameters)

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]

    def close(self) -> None:
        self.closed = True


class Connection:
    def __init__(
        self,
        *_args: Any,
        fail: Exception | None = None,
        **_kwargs: Any,
    ) -> None:
        self.timeout = 0
        self.cursor_instance = Cursor(fail)
        self.pinged = fail is None
        self.closed = False

    def cursor(self) -> Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True
