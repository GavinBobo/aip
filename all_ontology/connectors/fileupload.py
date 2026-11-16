# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""DuckDB connector over a dataset uploaded through the settings UI.

The upstream bytes live on the catalog database (see
:mod:`all_ontology.dal.uploads`), already shaped by the header row and column
names the operator chose. They are registered as a table in an in-memory
DuckDB, so querying and catalog introspection work exactly as they do for a
DuckDB file — without a shared volume between the API and the ingestion
service, and without the original spreadsheet having to be parseable again
years later.
"""

from __future__ import annotations

import io
import logging
from urllib.parse import unquote, urlparse

import pandas as pd

from all_ontology.connectors.duckdb import DuckDBDatabase
from all_ontology.utils.sql_identifiers import qualified_name, quoted_identifier

logger = logging.getLogger(__name__)

_SCHEMES = ("fileupload", "file", "dataset")


def _dataset_name(connection_string: str) -> str:
    """Extract the dataset name from ``fileupload://<name>`` or ``dataset://``."""
    parsed = urlparse(connection_string)
    scheme = parsed.scheme.split("+", 1)[0].lower()
    if scheme not in _SCHEMES:
        raise ValueError(f"Invalid file connection string: {connection_string!r}")
    name = unquote(parsed.netloc) or unquote(parsed.path.lstrip("/"))
    if not name:
        raise ValueError("File connection string is missing a dataset name")
    return name


class FileUploadDatabase(DuckDBDatabase):
    """In-memory DuckDB over one uploaded table.

    ``database_name`` is the connection's own name rather than DuckDB's
    ``current_database()`` (which would be ``memory``): that name is the key the
    catalog and text-to-SQL routing use, so it has to match the connection.
    """

    def __init__(self, connection_string: str) -> None:
        dataset_name = _dataset_name(connection_string)
        # Imported here: the DAL reaches into the connectors package elsewhere,
        # so a module-level import would close that cycle at import time.
        from all_ontology.dal.uploads import get_dataset

        dataset = get_dataset(dataset_name)
        if dataset is None:
            raise ValueError(
                f"No uploaded dataset named {dataset_name!r}. Re-create the "
                "connection and upload the file again."
            )

        try:
            frame = pd.read_parquet(io.BytesIO(dataset["content"]))
        except Exception as exc:  # noqa: BLE001 - corrupt stored dataset
            raise ValueError(
                f"Stored data for {dataset_name!r} could not be read: {exc}"
            ) from exc

        # Nullability is computed once from the data: DuckDB reports every
        # column of a materialised table as nullable, which would make the
        # prompt hedge about columns that are never empty.
        self._nullability = {
            str(column): bool(frame[column].isna().any()) for column in frame.columns
        }

        # ``read_only`` cannot be combined with an in-memory database; the
        # connection is private to this process anyway.
        super().__init__(":memory:", read_only=False)
        self._table_name = str(dataset["table_name"])
        self._database_name = str(dataset["name"])

        # The prompt names a table ``database.schema.table``, so the data has to
        # live in a catalog with the connection's name — DuckDB's default
        # in-memory catalog is called ``memory``, and a three-part name against
        # it would not resolve. ATTACH gives this connection that catalog.
        catalog = quoted_identifier(self._database_name, self.dialect)
        table = quoted_identifier(self._table_name, self.dialect)
        self.conn.execute(f"ATTACH ':memory:' AS {catalog}")
        self.conn.register("__upload_frame", frame)
        self.conn.execute(
            f"CREATE TABLE {catalog}.main.{table} AS SELECT * FROM __upload_frame"
        )
        self.conn.unregister("__upload_frame")
        logger.debug(
            "File connection %r registered table %r (%d rows)",
            self._database_name,
            self._table_name,
            len(frame),
        )

    def get_queries(self, hours: int = 24) -> pd.DataFrame:
        """No query history exists for an uploaded file."""
        return pd.DataFrame(columns=["end_time", "query_text"])

    def qualify(self, schema: str | None, table: str) -> str:
        """Three parts: the attached catalog plus ``schema.table``.

        The table lives in a catalog named after the connection, not in DuckDB's
        default ``memory`` catalog, so probes that emitted a bare
        ``schema.table`` would not find it.
        """
        return qualified_name(self._database_name, schema, table, dialect=self.dialect)

    def get_columns(self) -> pd.DataFrame:
        """DuckDB's column inventory, with real nullability for this dataset.

        A registered view reports every column as nullable. The uploaded data
        is fixed, so whether a column actually contains an empty cell is known,
        and it is worth telling the model: "this column is never null" removes
        a whole class of defensive predicates from the generated SQL.
        """
        frame = super().get_columns()
        frame["is_nullable"] = frame["column_name"].map(
            lambda name: self._nullability.get(str(name), True)
        )
        return frame


__all__ = ["FileUploadDatabase"]
