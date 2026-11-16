# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""All Ontology-owned catalog layer — the data catalog's vocabulary and write path.

The public surface is deliberately four entry points:

* :func:`all_ontology.catalog.ingest_catalog` — extract a connector's catalog and write it
* :func:`all_ontology.catalog.sql_parse.parse_query_single` — parse one SQL statement
  against the catalog
* :func:`all_ontology.catalog.store.queries.add_query` — persist a parsed query
* :class:`all_ontology.catalog.model.Schema` / :class:`all_ontology.catalog.model.CatalogNode`

Everything above :mod:`all_ontology.catalog.store` is storage-agnostic — keep SQL and
storage types confined to ``store/``.

``ingest_catalog`` is imported lazily: it pulls in pandas, sqlglot and the store
driver, and several modules import :mod:`all_ontology.catalog.constants` for nothing but
the label vocabulary.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from all_ontology.catalog.ingest import ingest_catalog

__all__ = ["ingest_catalog"]


def __getattr__(name: str) -> Any:
    if name == "ingest_catalog":
        from all_ontology.catalog.ingest import ingest_catalog

        return ingest_catalog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
