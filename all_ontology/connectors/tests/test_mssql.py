# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
from typing import Any

import pandas as pd
import pyodbc
import pytest
from pytest import MonkeyPatch

from all_ontology.connectors.base import StatementTimeout
from all_ontology.connectors.connection_string_factory import build_connection_string
from all_ontology.connectors.mssql import (
    MSSQLConnectionError,
    MSSQLDatabase,
    _connection_error_message,
    _odbc_connection_string,
    _parse_connection_string,
)
from all_ontology.connectors.registry import create_connector


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
        "instance": "",
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
    assert fields["instance"] == ""
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


def test_parse_connection_string_accepts_camel_case_options() -> None:
    fields = _parse_connection_string(
        "mssql://sa:pw@localhost/db"
        "?TrustServerCertificate=True&Encrypt=True"
        "&Driver=ODBC+Driver+18+for+SQL+Server"
    )

    assert fields["trust_server_certificate"] is True
    assert fields["encrypt"] == "yes"
    assert fields["driver"] == "ODBC Driver 18 for SQL Server"


def test_parse_named_instance_does_not_assume_the_default_port() -> None:
    fields = _parse_connection_string(
        "mssql://sa:pw@db.example.com/sales?instance=SQLEXPRESS"
    )

    assert fields["host"] == "db.example.com"
    assert fields["instance"] == "SQLEXPRESS"
    assert fields["port"] is None


def test_parse_host_with_backslash_instance_and_embedded_port() -> None:
    instance = _parse_connection_string(
        "mssql://sa:pw@db.example.com\\SQLEXPRESS/sales"
    )
    embedded = _parse_connection_string("mssql://sa:pw@db.example.com,1444/sales")

    # urlparse lowercases the netloc; SQL Server instance names are
    # case-insensitive, so compare without case.
    assert instance["instance"].casefold() == "sqlexpress"
    assert instance["host"] == "db.example.com"
    assert embedded["host"] == "db.example.com"
    assert embedded["port"] == 1444


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


def test_build_connection_string_keeps_named_instances_portless() -> None:
    connection_string = build_connection_string(
        {
            "type": "mssql",
            "host": "db",
            "instance": "SQLEXPRESS",
            "user": "sa",
            "password": "pw",
            "database": "master",
        }
    )

    assert connection_string == ("mssql://sa:pw@db/master?instance=SQLEXPRESS")


def test_build_connection_string_reconciles_a_port_in_the_host() -> None:
    connection_string = build_connection_string(
        {
            "type": "mssql",
            "host": "db.example.com,1444",
            "user": "sa",
            "password": "pw",
            "database": "master",
        }
    )

    assert connection_string == "mssql://sa:pw@db.example.com:1444/master"


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


def test_odbc_connection_string_brackets_ipv6_and_supports_instances() -> None:
    ipv6 = _odbc_connection_string(
        {
            "host": "::1",
            "port": 1433,
            "instance": "",
            "user": "sa",
            "password": "pw",
            "database": "master",
            "driver": "ODBC Driver 18 for SQL Server",
            "encrypt": "",
            "trust_server_certificate": False,
        }
    )
    named = _odbc_connection_string(
        {
            "host": "db.example.com",
            "port": None,
            "instance": "SQLEXPRESS",
            "user": "sa",
            "password": "pw",
            "database": "master",
            "driver": "ODBC Driver 18 for SQL Server",
            "encrypt": "",
            "trust_server_certificate": False,
        }
    )

    assert "SERVER={tcp:[::1],1433}" in ipv6
    assert "SERVER={tcp:db.example.com\\SQLEXPRESS}" in named


def test_odbc_connection_string_prefers_the_newest_installed_driver(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "all_ontology.connectors.mssql.pyodbc.drivers",
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
        "all_ontology.connectors.mssql.pyodbc.drivers", lambda: ["SQLite3"]
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


def test_connection_errors_name_the_likely_fix() -> None:
    fields = {
        "host": "db.example.com",
        "port": 1433,
        "instance": "",
    }

    certificate = _connection_error_message(
        pyodbc.OperationalError(
            "08001",
            "[08001] [Microsoft][ODBC Driver 18 for SQL Server]SSL Provider: "
            "The certificate chain was issued by an authority that is not trusted.",
        ),
        fields,
    )
    login = _connection_error_message(
        pyodbc.OperationalError("28000", "Login failed for user 'reporter'."),
        fields,
    )
    network = _connection_error_message(
        pyodbc.OperationalError(
            "08001",
            "[08001] TCP Provider: A network-related error occurred while "
            "establishing a connection.",
        ),
        fields,
    )
    redacted = _connection_error_message(
        pyodbc.OperationalError("08001", "failed PWD=hunter2;UID=reporter"),
        fields,
    )

    assert "Trust Server Certificate" in certificate
    assert "SQL authentication" in login
    assert "host/port is unreachable" in network
    assert "db.example.com,1433" in certificate
    assert "hunter2" not in redacted


def test_connection_error_separates_login_from_database_access() -> None:
    fields = {
        "host": "ws009412",
        "port": 1433,
        "instance": "SCA_PBI",
        "database": "SCA_PBI",
    }

    message = _connection_error_message(
        pyodbc.OperationalError(
            "28000",
            "[28000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]"
            "Login failed for user 'SCA_IE_Dig_R'. (18456); "
            "[28000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]"
            'Cannot open database "SCA_PBI" requested by the login. '
            "The login failed. (4060)",
        ),
        fields,
    )

    assert "SCA_PBI" in message
    assert "master" in message
    assert "ONLINE" in message
    assert "CONNECT" in message


def test_connect_failure_is_raised_as_a_connection_error(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "all_ontology.connectors.mssql.pyodbc.connect",
        lambda *_a, **_k: (_ for _ in ()).throw(
            pyodbc.OperationalError(
                "08001",
                "SSL Provider: The certificate chain was issued by an "
                "authority that is not trusted.",
            )
        ),
    )

    with pytest.raises(MSSQLConnectionError, match="Trust Server Certificate"):
        MSSQLDatabase(_connection_string())


def test_registry_creates_mssql_connector(monkeypatch: MonkeyPatch) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("all_ontology.connectors.mssql.pyodbc.connect", connect)

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

    monkeypatch.setattr("all_ontology.connectors.mssql.pyodbc.connect", connect)
    database = MSSQLDatabase(_connection_string())

    result = database.execute("SELECT ? AS value", [1])

    assert result.to_dict(orient="records") == [{"value": 1}]
    executed = connections[1].cursor_instance.executed
    assert executed == ("SELECT ? AS value", [1])
    assert connections[1].cursor_instance.closed
    assert connections[1].closed


def test_execute_treats_an_empty_parameter_list_as_no_parameters(
    monkeypatch: MonkeyPatch,
) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("all_ontology.connectors.mssql.pyodbc.connect", connect)
    database = MSSQLDatabase(_connection_string())

    database.execute("SELECT 1", [])

    assert connections[1].cursor_instance.executed == ("SELECT 1", None)


def test_execute_sets_the_query_timeout_on_its_own_connection(
    monkeypatch: MonkeyPatch,
) -> None:
    connections: list["Connection"] = []

    def connect(*_args: Any, **_kwargs: Any) -> "Connection":
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("all_ontology.connectors.mssql.pyodbc.connect", connect)
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
        "all_ontology.connectors.mssql.pyodbc.connect",
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
        "all_ontology.connectors.mssql.pyodbc.connect",
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
        "all_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
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
        "all_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
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
        "all_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
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
        "all_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string())

    def denied(*_args: Any, **_kwargs: Any) -> pd.DataFrame:
        raise pyodbc.ProgrammingError("42000", "permission denied")

    monkeypatch.setattr(database, "execute", denied)

    result = database.get_queries()
    assert list(result.columns) == ["end_time", "query_text"]
    assert result.empty


def test_query_history_degrades_when_the_server_is_unreachable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "all_ontology.connectors.mssql.pyodbc.connect", lambda *_a, **_k: Connection()
    )
    database = MSSQLDatabase(_connection_string())

    def unreachable(*_args: Any, **_kwargs: Any) -> pd.DataFrame:
        raise MSSQLConnectionError("Could not connect to SQL Server db")

    monkeypatch.setattr(database, "execute", unreachable)

    result = database.get_queries()
    assert list(result.columns) == ["end_time", "query_text"]
    assert result.empty


def _live_connection() -> dict[str, Any]:
    # Opt in explicitly so pytest never dials a real server just because
    # MSSQL_* happens to be exported in the shell.
    if os.environ.get("ALL_ONTOLOGY_LIVE_MSSQL") != "1":
        pytest.skip("Set ALL_ONTOLOGY_LIVE_MSSQL=1 to run the live SQL Server test")

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
