# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""SQL DDL export and import for the ER canvas.
Written against the dialects' public syntax, not adapted from another editor:
``CREATE TABLE`` / ``ALTER TABLE ... ADD CONSTRAINT`` are enough to round-trip a
diagram, and a small parser covers the subset a modelling tool produces.
Types are copied verbatim. No attempt is made to translate PostgreSQL's
``jsonb`` into MySQL's ``json``, because a wrong guess is worse than a type the
database rejects loudly.
"""

from __future__ import annotations
import re
import hashlib
from typing import Any

DIALECTS = ("sqlserver", "postgres", "mysql", "mariadb", "oracle", "sqlite")
_CONSTRAINT_KEYWORDS = (
    "NOT",
    "NULL",
    "PRIMARY",
    "DEFAULT",
    "UNIQUE",
    "REFERENCES",
    "CHECK",
    "COLLATE",
    "GENERATED",
    "COMMENT",
)
#: A (possibly schema-qualified) identifier. Each part may be quoted with
#: double quotes, backticks or brackets, which is the only way a table name can
#: contain a space.
_NAME = r'(?:"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\]|[^\s(])+'
_TOKEN_RE = re.compile(r'"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\]|\S+')
_CREATE_RE = re.compile(
    rf"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_NAME})\s*\(",
    re.IGNORECASE,
)
_ALTER_FK_RE = re.compile(
    rf"^\s*ALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>{_NAME})\s+ADD\s+"
    r"(?:CONSTRAINT\s+(?P<constraint>[^\s]+)\s+)?FOREIGN\s+KEY\s*"
    rf"\((?P<cols>[^)]*)\)\s*REFERENCES\s+(?P<target>{_NAME})\s*\((?P<tcols>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_INDEX_RE = re.compile(
    rf"^\s*CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?P<name>{_NAME})\s+ON\s+(?P<table>{_NAME})\s*"
    r"(?:USING\s+\w+\s*)?\((?P<cols>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


def _quote(name: str, dialect: str) -> str:
    if dialect == "sqlserver":
        return "[" + name.replace("]", "]]") + "]"
    if dialect in ("mysql", "mariadb"):
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def _quote_qualified(name: str, dialect: str) -> str:
    return ".".join(_quote(part, dialect) for part in name.split("."))


def _constraint_name(prefix: str, table: str, columns: list[str]) -> str:
    raw = f"{prefix}_{table}_{'_'.join(columns)}"
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
    # Non-ASCII identifiers (Chinese column names are common here) collapse to
    # the same few characters, so two keys on one table would collide. Keep a
    # short digest of the original text whenever sanitising lost information.
    if re.search(r"[^A-Za-z0-9_]", raw):
        clean = f"{clean[:50]}_{hashlib.sha1(raw.encode()).hexdigest()[:6]}"
    return clean.lower()[:60]


def _fk_endpoints(relationship: dict[str, Any]) -> tuple[str, str, bool] | None:
    """(referencing node, referenced node, unique) or None for many-to-many."""
    cardinality = relationship["cardinality"]
    if cardinality == "many-to-one":
        return relationship["source_node_id"], relationship["target_node_id"], False
    if cardinality == "one-to-many":
        return relationship["target_node_id"], relationship["source_node_id"], False
    if cardinality == "one-to-one":
        return relationship["source_node_id"], relationship["target_node_id"], True
    return None


def _sqlserver_table_comment(table: str, note: str) -> str:
    """Emit the extended property SQL Server uses for table descriptions."""
    parts = table.split(".")
    schema = parts[-2] if len(parts) > 1 else "dbo"
    name = parts[-1]
    value = note.replace("'", "''")
    schema_sql = schema.replace("'", "''")
    name_sql = name.replace("'", "''")
    return (
        "EXEC sp_addextendedproperty\n"
        f"    @name = N'MS_Description', @value = N'{value}',\n"
        f"    @level0type = N'SCHEMA', @level0name = N'{schema_sql}',\n"
        f"    @level1type = N'TABLE', @level1name = N'{name_sql}';"
    )


def export_sql(
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    dialect: str = "sqlserver",
) -> str:
    """Render the diagram as ``CREATE TABLE`` statements plus foreign keys."""
    if dialect not in DIALECTS:
        raise ValueError(f"Unknown SQL dialect {dialect!r}")
    by_id = {node["id"]: node for node in nodes}
    lines: list[str] = [
        f"-- exported from All-Ontology ({dialect})",
        "-- Column types are copied as written; check them against the target database.",
        "",
    ]
    # A foreign key belongs to the *many* side, so work out which table owns it
    # before emitting any DDL.
    foreign_keys: list[dict[str, Any]] = []
    index_statements: list[str] = []
    skipped: list[str] = []
    for relationship in relationships:
        endpoints = _fk_endpoints(relationship)
        if endpoints is None:
            source = by_id.get(relationship["source_node_id"], {}).get("name", "?")
            target = by_id.get(relationship["target_node_id"], {}).get("name", "?")
            skipped.append(
                f"-- {source} <-> {target}: many-to-many; a junction table is required"
            )
            continue
        referencing_id, referenced_id, unique = endpoints
        referencing = by_id.get(referencing_id)
        referenced = by_id.get(referenced_id)
        if referencing is None or referenced is None:
            continue
        columns = (
            relationship["source_columns"]
            if referencing_id == relationship["source_node_id"]
            else relationship["target_columns"]
        )
        target_columns = (
            relationship["target_columns"]
            if referencing_id == relationship["source_node_id"]
            else relationship["source_columns"]
        )
        if not columns or not target_columns:
            skipped.append(
                f"-- {referencing['name']} -> {referenced['name']}: "
                "relationship has no columns, so no foreign key is emitted"
            )
            continue
        foreign_keys.append(
            {
                "table": referencing["name"],
                "columns": columns,
                "target": referenced["name"],
                "target_columns": target_columns,
                "unique": unique,
                "label": relationship.get("label"),
            }
        )
    for node in nodes:
        note = (node.get("note") or "").strip()
        if note and dialect == "sqlite":
            # SQLite has no COMMENT statement; a readable comment is the only
            # way to keep the note next to the table it belongs to.
            lines.append(f"-- note: {note.replace(chr(10), ' ')}")
        body: list[str] = []
        primary_key: list[str] = []
        for column in node.get("columns") or []:
            parts = [
                _quote(column["name"], dialect),
                column.get("data_type") or "TEXT",
            ]
            if column.get("is_primary_key"):
                primary_key.append(column["name"])
            if column.get("is_nullable") is False:
                parts.append("NOT NULL")
            if column.get("is_unique"):
                parts.append("UNIQUE")
            body.append("  " + " ".join(parts))
        if len(primary_key) > 0:
            body.append(
                "  PRIMARY KEY ("
                + ", ".join(_quote(c, dialect) for c in primary_key)
                + ")"
            )
        if not node.get("columns"):
            body.append("  -- no columns")
        if dialect == "sqlite":
            # SQLite cannot add a foreign key after the table exists, so the
            # relationship has to be part of CREATE TABLE.
            for fk in foreign_keys:
                if fk["table"] != node["name"]:
                    continue
                clause = (
                    "  FOREIGN KEY ("
                    + ", ".join(_quote(c, dialect) for c in fk["columns"])
                    + ") REFERENCES "
                    + _quote_qualified(fk["target"], dialect)
                    + " ("
                    + ", ".join(_quote(c, dialect) for c in fk["target_columns"])
                    + ")"
                )
                if fk["unique"]:
                    clause += " UNIQUE"
                body.append(clause)
        lines.append(f"CREATE TABLE {_quote_qualified(node['name'], dialect)} (")
        lines.append(",\n".join(body))
        lines.append(");")
        if note and dialect in ("postgres", "oracle"):
            escaped = note.replace("'", "''")
            lines.append(
                f"COMMENT ON TABLE {_quote_qualified(node['name'], dialect)} IS '{escaped}';"
            )
        elif note and dialect in ("mysql", "mariadb"):
            escaped = note.replace("'", "''")
            lines.append(
                f"ALTER TABLE {_quote_qualified(node['name'], dialect)} "
                f"COMMENT = '{escaped}';"
            )
        elif note and dialect == "sqlserver":
            lines.append(_sqlserver_table_comment(node["name"], note))
        lines.append("")

        for index in node.get("indexes") or []:
            name = index.get("name") or _constraint_name(
                "idx", node["name"], index["columns"]
            )
            unique = "UNIQUE " if index.get("unique") else ""
            columns = ", ".join(_quote(column, dialect) for column in index["columns"])
            index_statements.append(
                f"CREATE {unique}INDEX {_quote(name, dialect)} ON "
                f"{_quote_qualified(node['name'], dialect)} ({columns});"
            )

    if index_statements:
        lines.extend(index_statements)
        lines.append("")
    if dialect != "sqlite":
        for fk in foreign_keys:
            name = _constraint_name("fk", fk["table"], fk["columns"])
            lines.append(
                f"ALTER TABLE {_quote_qualified(fk['table'], dialect)} "
                f"ADD CONSTRAINT {_quote(name, dialect)} FOREIGN KEY ("
                + ", ".join(_quote(c, dialect) for c in fk["columns"])
                + f") REFERENCES {_quote_qualified(fk['target'], dialect)} ("
                + ", ".join(_quote(c, dialect) for c in fk["target_columns"])
                + ");"
            )
            if fk["unique"]:
                unique_name = _constraint_name("uq", fk["table"], fk["columns"])
                lines.append(
                    f"ALTER TABLE {_quote_qualified(fk['table'], dialect)} "
                    f"ADD CONSTRAINT {_quote(unique_name, dialect)} UNIQUE ("
                    + ", ".join(_quote(c, dialect) for c in fk["columns"])
                    + ");"
                )
        lines.append("")
    if skipped:
        lines.extend(skipped)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _strip_comments(text: str) -> str:
    out: list[str] = []
    index = 0
    in_quote: str | None = None
    while index < len(text):
        char = text[index]
        if in_quote:
            out.append(char)
            if char == in_quote:
                in_quote = None
            index += 1
            continue
        if char in ("'", '"', "`"):
            in_quote = char
            out.append(char)
            index += 1
            continue
        if char == "[":
            in_quote = "]"
            out.append(char)
            index += 1
            continue
        if text[index : index + 2] == "--":
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
            continue
        if text[index : index + 2] == "/*":
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _split_statements(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
            current.append(char)
            continue
        if char == "[":
            quote = "]"
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char == ";" and depth == 0:
            statements.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return [statement for statement in statements if statement]


def _split_top_level(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
            current.append(char)
            continue
        if char == "[":
            quote = "]"
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        return value
    opening = value[0]
    closing = {'"': '"', "`": "`", "'": "'", "[": "]"}.get(opening)
    if closing is None or value[-1] != closing:
        return value
    inner = value[1:-1]
    if opening == "[":
        return inner.replace("]]", "]")
    if opening in ('"', "`"):
        return inner.replace(opening * 2, opening)
    return inner


def _normalize_name(value: str) -> str:
    return ".".join(_unquote(part) for part in value.split("."))


def _parse_column_list(raw: str) -> list[str]:
    return [_unquote(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_column(part: str) -> dict[str, Any]:
    tokens = _TOKEN_RE.findall(part.strip())
    if len(tokens) < 2:
        raise ValueError(f"column definition {part!r} needs a name and a type")
    name = _unquote(tokens[0])
    type_tokens: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.upper().rstrip("(") in _CONSTRAINT_KEYWORDS:
            break
        type_tokens.append(token)
        index += 1
    if not type_tokens:
        raise ValueError(f"column {name!r} has no type")
    settings = " ".join(tokens[index:]).upper()
    return {
        "name": name,
        "data_type": " ".join(type_tokens),
        "is_primary_key": "PRIMARY KEY" in settings,
        "is_unique": "UNIQUE" in settings,
        "is_nullable": "NOT NULL" not in settings,
        "inline_reference": _inline_reference(" ".join(tokens[index:])),
    }


def _inline_reference(raw: str) -> tuple[str, list[str]] | None:
    match = re.search(
        r"REFERENCES\s+(?P<target>[^\s(]+)\s*\((?P<cols>[^)]*)\)",
        raw,
        re.IGNORECASE,
    )
    if not match:
        return None
    return _normalize_name(match.group("target")), _parse_column_list(
        match.group("cols")
    )


def parse_sql(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Parse CREATE TABLE / ALTER TABLE foreign keys into canvas tables."""
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    warnings: list[str] = []
    pending_indexes: list[dict[str, Any]] = []
    statements = _split_statements(_strip_comments(text))
    for statement in statements:
        create_index = _CREATE_INDEX_RE.match(statement)
        if create_index:
            pending_indexes.append(
                {
                    "name": _unquote(create_index.group("name")),
                    "table": _normalize_name(create_index.group("table")),
                    "columns": _parse_column_list(create_index.group("cols")),
                    "unique": create_index.group("unique") is not None,
                }
            )
            continue
        alter = _ALTER_FK_RE.match(statement)
        if alter:
            relationships.append(
                {
                    "source": _normalize_name(alter.group("table")),
                    "source_columns": _parse_column_list(alter.group("cols")),
                    "target": _normalize_name(alter.group("target")),
                    "target_columns": _parse_column_list(alter.group("tcols")),
                    "cardinality": "many-to-one",
                    "label": None,
                }
            )
            continue
        create = _CREATE_RE.match(statement)
        if not create:
            if re.match(r"^\s*CREATE\s+(UNIQUE\s+)?INDEX", statement, re.IGNORECASE):
                warnings.append("an index definition was skipped")
            continue
        name = _normalize_name(create.group("name"))
        open_index = statement.find("(", create.start("name"))
        if open_index == -1:
            raise ValueError(f"CREATE TABLE {name!r} has no column list")
        depth = 0
        quote: str | None = None
        close_index = -1
        for position in range(open_index, len(statement)):
            char = statement[position]
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"', "`"):
                quote = char
                continue
            if char == "[":
                quote = "]"
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_index = position
                    break
        if close_index == -1:
            raise ValueError(f"CREATE TABLE {name!r} has an unclosed column list")
        body = statement[open_index + 1 : close_index]
        columns: list[dict[str, Any]] = []
        primary_key: list[str] = []
        unique_sets: list[list[str]] = []
        table_fks: list[tuple[list[str], str, list[str]]] = []
        for part in _split_top_level(body):
            upper = part.upper()
            if upper.startswith("PRIMARY KEY"):
                primary_key = _parse_column_list(
                    part[part.find("(") + 1 : part.rfind(")")]
                )
                continue
            if upper.startswith("UNIQUE"):
                unique_sets.append(
                    _parse_column_list(part[part.find("(") + 1 : part.rfind(")")])
                )
                continue
            if "FOREIGN KEY" in upper:
                match = re.search(
                    r"FOREIGN\s+KEY\s*\((?P<cols>[^)]*)\)\s*REFERENCES\s+(?P<target>[^\s(]+)\s*\((?P<tcols>[^)]*)\)",
                    part,
                    re.IGNORECASE,
                )
                if match:
                    table_fks.append(
                        (
                            _parse_column_list(match.group("cols")),
                            _normalize_name(match.group("target")),
                            _parse_column_list(match.group("tcols")),
                        )
                    )
                continue
            if upper.startswith(("CHECK", "CONSTRAINT", "KEY ", "INDEX")):
                continue
            column = _parse_column(part)
            inline = column.pop("inline_reference")
            columns.append(column)
            if inline is not None:
                table_fks.append(([column["name"]], inline[0], inline[1]))
        for column in columns:
            if column["name"] in primary_key:
                column["is_primary_key"] = True
            if any(column["name"] in group for group in unique_sets):
                column["is_unique"] = True
        nodes.append({"name": name, "collapsed": False, "columns": columns})
        for columns_in_fk, target, target_columns in table_fks:
            relationships.append(
                {
                    "source": name,
                    "source_columns": columns_in_fk,
                    "target": target,
                    "target_columns": target_columns,
                    "cardinality": "many-to-one",
                    "label": None,
                }
            )
    by_name = {node["name"]: node for node in nodes}
    for index in pending_indexes:
        node = by_name.get(index["table"])
        if node is None:
            warnings.append(
                f"index {index['name']!r} references a table that is not in the document"
            )
            continue
        node.setdefault("indexes", []).append(
            {
                "name": index["name"],
                "columns": index["columns"],
                "unique": index["unique"],
            }
        )
    return nodes, relationships, warnings
