# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A small DBML reader/writer.

DBML is a public, documented text format; this module implements the subset an
entity-relationship diagram needs and nothing else. It is written from the
format description rather than adapted from another project's parser.

Supported:

* ``Table schema.name as alias { ... }`` with column definitions
* column settings ``pk``, ``increment``, ``unique``, ``not null``, ``note: '...'``
* table-level ``Note: '...'``
* ``Ref: a.col < b.col``, ``Ref name: a.col > b.col`` and ``Ref { ... }``

Deliberately not supported, and reported as warnings rather than silently
dropped: ``Enum``, ``Indexes``, ``TableGroup``, ``Project``. Unknown lines are
warnings too, so a document written by another tool still imports the parts we
understand.
"""

from __future__ import annotations

import re
from typing import Any

#: DBML relationship operators, in the order they must be tested (``<>`` before
#: the two one-character operators it contains).
_OPERATORS = ("<>", ">", "<", "-")

_CARDINALITY = {
    ">": "many-to-one",
    "<": "one-to-many",
    "-": "one-to-one",
    "<>": "many-to-many",
}

_BLOCK_KEYWORDS = ("Table", "Ref", "Enum", "TableGroup", "Project", "Indexes")

_UNSUPPORTED_BLOCKS = {"Enum", "TableGroup", "Project"}


class DbmlParseError(ValueError):
    """A document could not be parsed, with the line that caused it."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.reason = message


def _strip_comment(line: str) -> str:
    """Drop a ``//`` comment, ignoring one inside a single-quoted string."""
    in_quote = False
    index = 0
    while index < len(line):
        char = line[index]
        if in_quote and char == "\\":
            # The next character is escaped, so ``\'`` must not close the
            # string (see ``note: 'customer\'s id'``).
            index += 2
            continue
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and char == "/" and line[index : index + 2] == "//":
            return line[:index]
        index += 1
    return line


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("\\'", "'").replace("\\n", "\n").replace("\\\\", "\\")
    return value


def _escape_text(value: str) -> str:
    """Escape free text for a single-quoted DBML string.

    Notes are typed by an operator, so they routinely contain an apostrophe
    ("customer's id") or a line break. Emitted raw, either one ends the string
    early and makes the document unreadable for dbdiagram and the ``dbml`` CLI,
    which is the whole point of the export.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _quote_identifier(value: str) -> str:
    """Quote a name DBML would otherwise split or misread."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return value
    return f'"{value}"'


def _split_qualified(value: str) -> list[str]:
    """Split ``schema.name`` on the dots *outside* double quotes."""
    parts: list[str] = []
    current: list[str] = []
    in_quote: bool = False
    for char in value:
        if char == '"':
            in_quote = not in_quote
            current.append(char)
        elif char == "." and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [_unquote(part) for part in parts]


def _quote_qualified(value: str) -> str:
    """``main.order lines`` -> ``main."order lines"``, not ``"main.order lines"``."""
    return ".".join(_quote_identifier(part) for part in _split_qualified(value))


def _split_alias(value: str) -> tuple[str, str | None]:
    """Split ``name as alias`` on the ``as`` outside quotes."""
    in_quote = False
    for index, char in enumerate(value):
        if char == '"':
            in_quote = not in_quote
        elif not in_quote and value[index : index + 4].lower() == " as ":
            return value[:index].strip(), value[index + 4 :].strip()
    return value.strip(), None


def _split_settings(raw: str) -> list[str]:
    """Split a ``[a, b, note: 'x, y']`` body on commas outside quotes."""
    parts: list[str] = []
    current: list[str] = []
    in_quote: bool = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if in_quote and char == "\\":
            current.append(raw[index : index + 2])
            index += 2
            continue
        if char == "'":
            in_quote = not in_quote
            current.append(char)
        elif char == "," and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _parse_column_settings(raw: str) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "is_primary_key": False,
        "is_unique": False,
        "is_nullable": True,
        "note": None,
    }
    for item in _split_settings(raw):
        lowered = item.lower()
        if lowered in {"pk", "primary key"}:
            settings["is_primary_key"] = True
            settings["is_nullable"] = False
        elif lowered == "unique":
            settings["is_unique"] = True
        elif lowered == "not null":
            settings["is_nullable"] = False
        elif lowered == "null":
            settings["is_nullable"] = True
        elif lowered.startswith("note"):
            _, _, value = item.partition(":")
            settings["note"] = _unquote(value)
        # `increment`, `default:` and anything else carry no diagram meaning.
    return settings


def _split_column(line: str) -> tuple[str, str, str]:
    """``name type [settings]`` -> its three parts.

    The settings are split off from the end first, so a type containing spaces
    (``double precision``) or parentheses (``decimal(10,2)``) survives intact.
    """
    settings = ""
    body = line.strip()
    if body.endswith("]"):
        start = body.rfind("[")
        if start == -1:
            raise ValueError("unbalanced column settings")
        settings = body[start + 1 : -1]
        body = body[:start].rstrip()

    if body.startswith('"'):
        end = body.find('"', 1)
        if end == -1:
            raise ValueError("unbalanced quoted column name")
        name = body[1:end]
        remainder = body[end + 1 :].strip()
    else:
        name, _, remainder = body.partition(" ")
        remainder = remainder.strip()

    if not name or not remainder:
        raise ValueError("a column needs a name and a type")
    return name, remainder, settings


def _split_endpoint(value: str) -> tuple[str, str]:
    """``schema.table.column`` -> (``schema.table``, ``column``)."""
    stripped = value.strip()
    index = -1
    in_quote = False
    for position, char in enumerate(stripped):
        if char == '"':
            in_quote = not in_quote
        elif char == "." and not in_quote:
            index = position
    if index <= 0 or index == len(stripped) - 1:
        raise ValueError(f"expected table.column, got {value!r}")
    return (
        ".".join(_split_qualified(stripped[:index])),
        _unquote(stripped[index + 1 :]),
    )


def _parse_ref_body(body: str) -> dict[str, Any]:
    for operator in _OPERATORS:
        if operator not in body:
            continue
        left, _, right = body.partition(operator)
        source_table, source_column = _split_endpoint(left)
        target_table, target_column = _split_endpoint(right)
        return {
            "source": source_table,
            "source_columns": [source_column],
            "target": target_table,
            "target_columns": [target_column],
            "cardinality": _CARDINALITY[operator],
            "label": None,
        }
    raise ValueError("a Ref needs one of '<', '>', '-' or '<>'")


def _parse_index_line(line: str) -> dict[str, Any] | None:
    """``(a, b) [unique, name: 'idx']`` or ``a [unique]``."""
    body = line.strip()
    settings = ""
    if body.endswith("]"):
        start = body.rfind("[")
        if start == -1:
            raise ValueError("unbalanced index settings")
        settings = body[start + 1 : -1]
        body = body[:start].strip()

    if body.startswith("("):
        end = body.rfind(")")
        if end == -1:
            raise ValueError("unbalanced index column list")
        columns = [
            _unquote(part.strip()) for part in body[1:end].split(",") if part.strip()
        ]
    else:
        columns = [_unquote(body)] if body else []
    if not columns:
        return None

    name: str | None = None
    unique = False
    for item in _split_settings(settings):
        lowered = item.lower()
        if lowered == "unique":
            unique = True
        elif lowered.startswith("name"):
            _, _, value = item.partition(":")
            name = _unquote(value)
    return {"name": name, "columns": columns, "unique": unique}


def parse_dbml(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Parse *text* into ``(nodes, relationships, warnings)``.

    Raises :class:`DbmlParseError` on a malformed line that a human has to fix;
    syntax the canvas does not model is reported in *warnings* instead.
    """
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    warnings: list[str] = []

    current: dict[str, Any] | None = None
    ref_block: bool = False
    index_block: int = 0
    skipping_depth: int = 0
    depth: int = 0

    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        if skipping_depth:
            # Its braces belong to the skipped block, not to the table we are
            # inside — counting them here drove `depth` negative and made the
            # next `Table` line look like a one-line table.
            skipping_depth = max(skipping_depth + line.count("{") - line.count("}"), 0)
            if skipping_depth == 0:
                current = None
            continue

        if index_block:
            if line.startswith("}"):
                index_block -= 1
                continue
            if current is not None:
                try:
                    parsed_index = _parse_index_line(line)
                except ValueError as exc:
                    raise DbmlParseError(str(exc), number) from exc
                if parsed_index is not None:
                    current.setdefault("indexes", []).append(parsed_index)
            continue

        if line.startswith("}"):
            depth = max(depth - 1, 0)
            current = None
            ref_block = False
            continue

        keyword = line.split(None, 1)[0].rstrip(":")

        if keyword in _UNSUPPORTED_BLOCKS:
            # `Indexes` inside a table is a nested block; the others are
            # top-level statements. Both are skipped without failing the import.
            warnings.append(
                f"line {number}: '{keyword}' is not supported and was skipped"
            )
            if "{" in line:
                skipping_depth = line.count("{") - line.count("}")
                if skipping_depth <= 0:
                    skipping_depth = 1
            current = None
            continue

        if keyword == "Table":
            # Net the braces: `Table a { x int }` on one line opens and closes
            # the block without ever reaching the `}` branch below.
            depth += line.count("{") - line.count("}")
            ref_block = False
            rest = line[len("Table") :].strip()
            if rest.endswith("{"):
                rest = rest[:-1].strip()
            name_text, alias_text = _split_alias(rest)
            if not name_text:
                raise DbmlParseError("expected 'Table name {'", number)
            name = ".".join(_split_qualified(name_text))
            current = {
                "name": name,
                "alias": ".".join(_split_qualified(alias_text)) if alias_text else name,
                "columns": [],
                "note": None,
            }
            nodes.append(current)
            if depth == 0:
                current = None
            continue

        if keyword == "Ref":
            rest = line[len("Ref") :].strip()
            if rest.startswith("{") or rest == "":
                ref_block = True
                depth += 1
                current = None
                continue
            # `Ref name: a.b > c.d` — the optional name is not part of the model.
            if ":" in rest:
                rest = rest.split(":", 1)[1].strip()
            try:
                relationships.append(_parse_ref_body(rest))
            except ValueError as exc:
                raise DbmlParseError(str(exc), number) from exc
            continue

        if ref_block:
            try:
                relationships.append(_parse_ref_body(line))
            except ValueError as exc:
                raise DbmlParseError(str(exc), number) from exc
            continue

        if current is None:
            if keyword.lower().startswith("note"):
                continue
            warnings.append(f"line {number}: unrecognised statement skipped")
            continue

        if line.lower().startswith("indexes"):
            index_block = 1
            current.setdefault("indexes", [])
            continue

        if line.lower().startswith("note"):
            _, _, value = line.partition(":")
            current["note"] = _unquote(value)
            continue

        try:
            name, data_type, settings = _split_column(line)
        except ValueError as exc:
            raise DbmlParseError(str(exc), number) from exc

        parsed = _parse_column_settings(settings)
        current["columns"].append(
            {
                "name": name,
                "data_type": data_type,
                "is_primary_key": parsed["is_primary_key"],
                "is_unique": parsed["is_unique"],
                "is_nullable": parsed["is_nullable"],
                "note": parsed["note"],
            }
        )

    if depth > 0 or ref_block:
        raise DbmlParseError(
            "unclosed block at end of document", len(text.splitlines())
        )

    return nodes, relationships, warnings


def export_dbml(
    nodes: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> str:
    """Serialise nodes and relationships as a DBML document."""
    lines: list[str] = ["// exported from Auto-Ontology", ""]

    names = {node["name"] for node in nodes}
    for node in nodes:
        lines.append(f"Table {_quote_qualified(node['name'])} {{")
        for column in node.get("columns") or []:
            settings: list[str] = []
            if column.get("is_primary_key"):
                settings.append("pk")
            if column.get("is_unique"):
                settings.append("unique")
            if column.get("is_nullable") is False:
                settings.append("not null")
            if column.get("note"):
                settings.append(f"note: '{_escape_text(column['note'])}'")
            suffix = f" [{', '.join(settings)}]" if settings else ""
            lines.append(
                f"  {_quote_identifier(column['name'])} "
                f"{column.get('data_type') or 'text'}{suffix}"
            )
        indexes = node.get("indexes") or []
        if indexes:
            lines.append("  Indexes {")
            for index in indexes:
                settings: list[str] = []
                if index.get("unique"):
                    settings.append("unique")
                if index.get("name"):
                    settings.append(f"name: '{_escape_text(index['name'])}'")
                columns = ", ".join(
                    _quote_identifier(column) for column in index["columns"]
                )
                suffix = f" [{', '.join(settings)}]" if settings else ""
                lines.append(f"    ({columns}){suffix}")
            lines.append("  }")
        if node.get("note"):
            lines.append(f"  Note: '{_escape_text(node['note'])}'")
        lines.append("}")
        lines.append("")

    for rel in relationships:
        if rel["source"] not in names or rel["target"] not in names:
            continue
        source_column = (rel.get("source_columns") or [None])[0]
        target_column = (rel.get("target_columns") or [None])[0]
        if source_column is None or target_column is None:
            # DBML has no table-level Ref; a relationship without columns can
            # only be expressed by pointing at a column that exists on both.
            continue
        operator = {
            "many-to-one": ">",
            "one-to-many": "<",
            "one-to-one": "-",
            "many-to-many": "<>",
        }[rel["cardinality"]]
        lines.append(
            f"Ref: {_quote_qualified(rel['source'])}.{_quote_identifier(source_column)} "
            f"{operator} "
            f"{_quote_qualified(rel['target'])}.{_quote_identifier(target_column)}"
        )

    if lines and lines[-1] != "":
        lines.append("")
    return "\n".join(lines)
