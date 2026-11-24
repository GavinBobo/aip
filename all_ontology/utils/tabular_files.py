# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read an uploaded spreadsheet or delimited file into a DataFrame.

Backs the "Excel / CSV" connection type: the settings UI uploads a file, the
backend previews the first rows so an operator can pick the header row and
rename columns, and the chosen shape is then written to Parquet and stored on
the catalog database. Parsing lives here rather than in the connector so the
preview and the final load agree on formats, encodings, and header handling.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# Extensions the upload endpoint accepts. Parquet carries its own schema, so it
# has no header row to choose; renames still apply. ``.pcl`` is a delimited
# text export whose separator varies by the tool that wrote it, which is why
# the delimiter is selectable.
CSV_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".pcl"})
EXCEL_SUFFIXES = frozenset({".xlsx", ".xls", ".xlsm"})
PARQUET_SUFFIXES = frozenset({".parquet", ".pq"})
SUPPORTED_SUFFIXES = tuple(sorted(CSV_SUFFIXES | EXCEL_SUFFIXES | PARQUET_SUFFIXES))

# Encodings tried in order for delimited files. GB18030 covers the GBK/GB2312
# exports common in Chinese-language spreadsheets; latin-1 never fails, so it
# is the last resort that renders something instead of refusing the file.
_CSV_ENCODINGS = ("utf-8-sig", "gb18030", "latin-1")

# Candidate separators, in preference order for ties.
_DELIMITERS = (",", "\t", ";", "|")

# Rows shown in the preview. Enough to see the shape and click the header row
# without shipping a whole sheet to the browser.
PREVIEW_ROW_LIMIT = 20


class TabularFileError(ValueError):
    """The uploaded file could not be read as a table."""


def detect_format(filename: str) -> str:
    """Return ``csv``, ``excel`` or ``parquet`` for *filename*."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in CSV_SUFFIXES:
        return "csv"
    if suffix in EXCEL_SUFFIXES:
        return "excel"
    if suffix in PARQUET_SUFFIXES:
        return "parquet"
    raise TabularFileError(
        f"Unsupported file type {suffix or '(none)'}. Upload one of: "
        + ", ".join(SUPPORTED_SUFFIXES)
    )


def normalize_delimiter(value: str | None) -> str | None:
    """Validate a user-chosen separator; ``None`` means "detect it"."""
    if value is None:
        return None
    text = str(value)
    # ``\t`` is what a caller who cannot send a literal tab will write.
    if text in ("\\t", "tab", "TAB"):
        text = "\t"
    if text == "":
        return None
    if len(text) != 1:
        raise TabularFileError("The delimiter must be a single character")
    if text in ("\n", "\r", '"', "'"):
        raise TabularFileError("The delimiter cannot be a newline or a quote character")
    return text


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() in ("", "nan", "NaT", "None")


def _detect_delimiter(text: str) -> str:
    """Pick the separator that most lines agree on.

    ``csv.Sniffer`` scores by the first lines it sees, so a title row like
    ``Sales report 2024`` above the real header makes it choose a space and
    parse the whole file into one column. Counting each candidate across many
    lines, and preferring the one with a stable count, survives that.
    """
    lines = [line for line in text.splitlines()[:50] if line.strip()]
    best_delimiter = ","
    best_score = (0, 0)
    for delimiter in _DELIMITERS:
        counts = [line.count(delimiter) for line in lines]
        positive = [count for count in counts if count > 0]
        if not positive:
            continue
        mode = max(set(positive), key=positive.count)
        consistent = sum(1 for count in counts if count == mode)
        score = (consistent, mode)
        if score > best_score:
            best_delimiter, best_score = delimiter, score
    return best_delimiter


def _read_csv(
    content: bytes,
    *,
    header: int | None,
    dtype: str | None = None,
    delimiter: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Read a delimited file, choosing its encoding and separator."""
    encodings = _CSV_ENCODINGS
    # A BOM is decisive: Excel's "Unicode Text" export is UTF-16 with one.
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        encodings = ("utf-16",) + _CSV_ENCODINGS

    last_error: Exception | None = None
    for encoding in encodings:
        try:
            sample = content[:64000].decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        separator = delimiter or _detect_delimiter(sample)
        width = _max_fields(sample, separator)
        # ``names`` fixes the expected width up front. Without it pandas takes
        # the first row's width as the schema, so a one-cell title row above the
        # real header makes the whole read fail ("Expected 1 fields, saw 3").
        # Naming the columns also makes ``header=N`` skip that row and the ones
        # above it, which is exactly the chosen-header semantics.
        try:
            return pd.read_csv(
                io.BytesIO(content),
                header=header,
                sep=separator,
                encoding=encoding,
                dtype=dtype,
                names=range(width),
                skip_blank_lines=False,
            ), separator
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
            if isinstance(exc, pd.errors.ParserError):
                # A row past the sample may be wider than every sampled line.
                try:
                    whole = content.decode(encoding)
                except UnicodeDecodeError:
                    continue
                wider = _max_fields(whole, separator)
                if wider > width:
                    try:
                        return pd.read_csv(
                            io.BytesIO(content),
                            header=header,
                            sep=separator,
                            encoding=encoding,
                            dtype=dtype,
                            names=range(wider),
                            skip_blank_lines=False,
                        ), separator
                    except (UnicodeDecodeError, pd.errors.ParserError) as retry:
                        last_error = retry
            continue
    raise TabularFileError(f"Could not read the delimited file: {last_error}")


def _max_fields(text: str, delimiter: str) -> int:
    """Widest row in *text*, used to fix the delimited file's column count."""
    lines = [line for line in text.splitlines()[:2000] if line.strip()]
    return max((line.count(delimiter) + 1 for line in lines), default=1)


def _read_raw(
    filename: str,
    content: bytes,
    sheet: str | None,
    *,
    dtype: str | None = None,
    delimiter: str | None = None,
) -> tuple[pd.DataFrame, list[str], str | None, str | None]:
    """Read *content* without a header.

    Returns ``(frame, sheets, sheet, delimiter)``; ``delimiter`` is the one
    actually used, or ``None`` for a workbook or Parquet file.
    """
    file_format = detect_format(filename)
    if file_format == "excel":
        try:
            with pd.ExcelFile(io.BytesIO(content)) as workbook:
                sheets = [str(name) for name in workbook.sheet_names]
                if not sheets:
                    raise TabularFileError("The workbook has no sheets")
                target = sheet if sheet in sheets else sheets[0]
                frame = pd.read_excel(
                    workbook, sheet_name=target, header=None, dtype=dtype
                )
            return frame, sheets, target, None
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422
            raise TabularFileError(f"Could not read the workbook: {exc}") from exc

    frame, used = _read_csv(content, header=None, dtype=dtype, delimiter=delimiter)
    return frame, [], None, used


def _display_rows(frame: pd.DataFrame, limit: int) -> list[list[str | None]]:
    """First *limit* rows as display strings; blank cells become ``None``."""
    rows: list[list[str | None]] = []
    for _, row in frame.head(limit).iterrows():
        rows.append([None if _is_blank(value) else str(value) for value in row])
    width = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend([None] * (width - len(row)))
    return rows


def detect_header_row(frame: pd.DataFrame, scan: int = 10) -> int:
    """Best guess at the header row: the widest text row near the top.

    Title rows ("Q3 sales report") above a real header are common; the header
    is the row that fills in the most columns. Ties keep the earliest row.
    """
    best_index = 0
    best_score = -1
    for index in range(min(scan, len(frame))):
        values = list(frame.iloc[index])
        non_empty = sum(1 for value in values if not _is_blank(value))
        if non_empty < 2:
            continue
        if non_empty > best_score:
            best_index, best_score = index, non_empty
    return best_index


def preview(
    filename: str,
    content: bytes,
    *,
    sheet: str | None = None,
    delimiter: str | None = None,
    row_limit: int = PREVIEW_ROW_LIMIT,
) -> dict[str, Any]:
    """Describe *content* for the header/rename step of the connection wizard."""
    delimiter = normalize_delimiter(delimiter)
    file_format = detect_format(filename)

    if file_format == "parquet":
        try:
            frame = pd.read_parquet(io.BytesIO(content))
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422
            raise TabularFileError(f"Could not read the Parquet file: {exc}") from exc
        return {
            "filename": filename,
            "format": file_format,
            "sheets": [],
            "sheet": None,
            "delimiter": None,
            "rows": _display_rows(frame, row_limit),
            "row_count": int(len(frame)),
            "column_count": int(len(frame.columns)),
            "column_names": _clean_columns(
                [str(name) for name in frame.columns], frame.shape[1]
            ),
            "detected_header_row": 0,
            "supports_header_row": False,
        }

    frame, sheets, selected, used = _read_raw(
        filename, content, sheet, dtype=str, delimiter=delimiter
    )
    header_row = detect_header_row(frame)
    header_values = [
        None if _is_blank(value) else str(value).strip()
        for value in frame.iloc[header_row].tolist()
    ]
    return {
        "filename": filename,
        "format": file_format,
        "sheets": sheets,
        "sheet": selected,
        "delimiter": used,
        "rows": _display_rows(frame, max(row_limit, header_row + 1)),
        "row_count": int(max(0, len(frame) - header_row - 1)),
        "column_count": int(frame.shape[1]),
        "column_names": _clean_columns(header_values, frame.shape[1]),
        "detected_header_row": header_row,
        "supports_header_row": True,
    }


def _clean_columns(requested: Sequence[str] | None, width: int) -> list[str]:
    """Apply the operator's names, filling blanks and removing duplicates.

    DuckDB resolves identifiers case-insensitively, so ``Name`` and ``name``
    would be the same column; the suffix makes them distinct rather than
    letting one silently shadow the other.
    """
    names: list[str] = []
    seen: set[str] = set()
    for index in range(width):
        candidate = ""
        if requested is not None and index < len(requested):
            candidate = str(requested[index] or "").strip()
        if not candidate:
            candidate = f"Column {index + 1}"

        unique = candidate
        suffix = 2
        while unique.casefold() in seen:
            unique = f"{candidate}_{suffix}"
            suffix += 1
        seen.add(unique.casefold())
        names.append(unique)
    return names


def _kept_indices(requested: Sequence[int], width: int) -> list[int]:
    """Validate and order the operator's column selection."""
    try:
        kept = sorted({int(index) for index in requested})
    except (TypeError, ValueError) as exc:
        raise TabularFileError(
            "Column selection must be a list of column indexes"
        ) from exc
    if not kept:
        raise TabularFileError("Select at least one column")
    if kept[0] < 0 or kept[-1] >= width:
        raise TabularFileError("A selected column is outside the file")
    return kept


def build_frame(
    filename: str,
    content: bytes,
    *,
    sheet: str | None = None,
    header_row: int = 0,
    columns: Sequence[str] | None = None,
    delimiter: str | None = None,
    keep_columns: Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return the table the uploaded file describes.

    *header_row* is a zero-based row number inside the file; every row above it
    is skipped and that row becomes the column names. *columns* overrides those
    names positionally. *keep_columns* is a set of zero-based positions to keep:
    anything else is dropped before the names are applied, so the stored table
    only carries the columns the operator selected.
    """
    delimiter = normalize_delimiter(delimiter)
    file_format = detect_format(filename)
    if file_format == "parquet":
        try:
            frame = pd.read_parquet(io.BytesIO(content))
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422
            raise TabularFileError(f"Could not read the Parquet file: {exc}") from exc
        names = (
            [str(name) for name in columns]
            if columns is not None
            else [str(name) for name in frame.columns]
        )
        if keep_columns is not None:
            kept = _kept_indices(keep_columns, frame.shape[1])
            frame = frame.iloc[:, kept]
            names = [names[index] for index in kept]
        frame.columns = _clean_columns(
            names,
            frame.shape[1],
        )
    else:
        header = max(0, int(header_row))
        if header > 20_000:
            raise TabularFileError("Header row is too far into the file")
        if columns is None:
            # The caller (the wizard) always sends names, but the API accepts
            # their absence — then the header row itself supplies them.
            raw, _, _, _ = _read_raw(
                filename, content, sheet, dtype=str, delimiter=delimiter
            )
            if header >= len(raw):
                raise TabularFileError(
                    "The selected header row is past the end of the file"
                )
            columns = [str(value) for value in raw.iloc[header].tolist()]
        if file_format == "excel":
            try:
                with pd.ExcelFile(io.BytesIO(content)) as workbook:
                    sheets = [str(name) for name in workbook.sheet_names]
                    if not sheets:
                        raise TabularFileError("The workbook has no sheets")
                    target = sheet if sheet in sheets else sheets[0]
                    frame = pd.read_excel(workbook, sheet_name=target, header=header)
            except Exception as exc:  # noqa: BLE001 - surfaced as a 422
                raise TabularFileError(f"Could not read the workbook: {exc}") from exc
        else:
            frame, _ = _read_csv(content, header=header, delimiter=delimiter)
        if keep_columns is not None:
            kept = _kept_indices(keep_columns, frame.shape[1])
            frame = frame.iloc[:, kept]
            columns = [columns[index] for index in kept]
        frame.columns = _clean_columns(columns, frame.shape[1])

    # Excel files routinely carry trailing blank rows from formatting; they
    # would otherwise become real (empty) rows in the catalog's row counts.
    frame = frame.dropna(how="all").reset_index(drop=True)
    if frame.empty:
        raise TabularFileError(
            "The selected header row left no data rows. Choose an earlier row."
        )
    return frame


def frame_to_parquet(frame: pd.DataFrame) -> bytes:
    """Serialise *frame* for storage on the catalog database."""
    buffer = io.BytesIO()
    try:
        frame.to_parquet(buffer, index=False)
    except Exception:
        # A column mixing numbers and text (common in hand-built spreadsheets)
        # cannot be encoded as one Arrow type. Rendering those columns as text
        # keeps the data rather than rejecting the upload.
        logger.info("Parquet encode failed; casting mixed-type columns to text")
        converted = frame.copy()
        for column in converted.columns:
            if converted[column].dtype == object:
                converted[column] = converted[column].astype("string")
        buffer = io.BytesIO()
        try:
            converted.to_parquet(buffer, index=False)
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422
            raise TabularFileError(f"Could not prepare the data for storage: {exc}")
    return buffer.getvalue()


def sanitize_table_name(name: str) -> str:
    """A quote-free DuckDB table name derived from the connection name."""
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", str(name or "")).strip("_").lower()
    if not cleaned:
        cleaned = "data"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:60]


__all__ = [
    "PREVIEW_ROW_LIMIT",
    "SUPPORTED_SUFFIXES",
    "TabularFileError",
    "build_frame",
    "detect_format",
    "detect_header_row",
    "frame_to_parquet",
    "normalize_delimiter",
    "preview",
    "sanitize_table_name",
]
