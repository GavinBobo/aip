# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Preview and materialisation for uploaded spreadsheets and data files."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from auto_ontology.utils.tabular_files import (
    TabularFileError,
    build_frame,
    detect_format,
    detect_header_row,
    frame_to_parquet,
    normalize_delimiter,
    preview,
    sanitize_table_name,
)

_WITH_TITLE = (
    "Sales report 2024\n"
    "Customer ID,Name,Amount,Region\n"
    "1,Alice,10.5,North\n"
    "2,Bob,20,South\n"
    "3,Carol,30.25,North\n"
).encode()


def _xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Quarterly report"],
                ["ID", "Region", "Total"],
                [1, "North", 100],
                [2, "South", 200],
            ]
        ).to_excel(writer, sheet_name="Data", header=False, index=False)
        pd.DataFrame({"x": [1], "y": [2]}).to_excel(
            writer, sheet_name="Notes", header=True, index=False
        )
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("a.csv", "csv"),
        ("a.tsv", "csv"),
        ("a.txt", "csv"),
        ("a.xlsx", "excel"),
        ("a.xls", "excel"),
        ("a.parquet", "parquet"),
        ("a.pq", "parquet"),
        # A .pcl export is delimited text whose separator the writer chose.
        ("a.pcl", "csv"),
    ],
)
def test_detect_format(filename: str, expected: str) -> None:
    assert detect_format(filename) == expected


def test_detect_format_rejects_unknown_extensions() -> None:
    with pytest.raises(TabularFileError, match="Unsupported file type"):
        detect_format("notes.docx")


def test_header_row_is_the_widest_row_not_the_title() -> None:
    frame = pd.DataFrame(
        [
            ["Sales report 2024", None, None, None],
            ["Customer ID", "Name", "Amount", "Region"],
            [1, "Alice", 10.5, "North"],
        ]
    )

    assert detect_header_row(frame) == 1


def test_preview_reports_shape_and_detected_header() -> None:
    result = preview("sales.csv", _WITH_TITLE)

    assert result["detected_header_row"] == 1
    # Raw rows are returned verbatim, before the header is applied.
    assert result["rows"][0] == ["Sales report 2024", None, None, None]
    assert result["rows"][1] == ["Customer ID", "Name", "Amount", "Region"]
    assert result["column_count"] == 4
    assert result["row_count"] == 3
    assert result["column_names"] == ["Customer ID", "Name", "Amount", "Region"]
    assert result["supports_header_row"] is True
    assert result["sheets"] == []


def test_build_frame_skips_the_title_and_infers_types() -> None:
    frame = build_frame(
        "sales.csv",
        _WITH_TITLE,
        header_row=1,
        columns=["customer_id", "name", "amount", "region"],
    )

    assert list(frame.columns) == ["customer_id", "name", "amount", "region"]
    assert frame["customer_id"].dtype == "int64"
    assert frame["amount"].dtype == "float64"
    assert frame["name"].tolist() == ["Alice", "Bob", "Carol"]


def test_build_frame_uses_the_header_row_when_no_names_are_given() -> None:
    frame = build_frame("sales.csv", _WITH_TITLE, header_row=1)

    assert list(frame.columns) == ["Customer ID", "Name", "Amount", "Region"]


def test_tab_separated_file_is_detected() -> None:
    frame = build_frame("x.tsv", b"id\tlabel\n1\talpha\n2\tbeta\n")

    assert list(frame.columns) == ["id", "label"]
    assert frame["id"].tolist() == [1, 2]


def test_semicolon_separated_file_is_detected() -> None:
    frame = build_frame("x.csv", "id;name\n1;Alice\n2;Bob\n".encode())

    assert list(frame.columns) == ["id", "name"]
    assert frame["name"].tolist() == ["Alice", "Bob"]


def test_pcl_file_reads_with_the_chosen_delimiter() -> None:
    content = b"Title\nid^name^amount\n1^Alice^10\n2^Bob^20\n"

    assert detect_format("export.pcl") == "csv"
    frame = build_frame("export.pcl", content, header_row=1, delimiter="^")

    assert list(frame.columns) == ["id", "name", "amount"]
    assert frame["name"].tolist() == ["Alice", "Bob"]


def test_an_explicit_delimiter_overrides_detection() -> None:
    # Detection would pick "," here; the user says "^".
    content = b"id,name^amount\n1,Alice^10\n"

    frame = build_frame("x.csv", content, delimiter="^")

    assert list(frame.columns) == ["id,name", "amount"]
    assert frame["amount"].tolist() == [10]


def test_preview_reports_the_delimiter_it_used() -> None:
    pipe = preview("x.pcl", b"id|name\n1|Alice\n")
    assert pipe["delimiter"] == "|"

    comma = preview("x.csv", b"id,name\n1,Alice\n")
    assert comma["delimiter"] == ","

    xlsx = preview("report.xlsx", _xlsx_bytes())
    assert xlsx["delimiter"] is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (";", ";"),
        ("\\t", "\t"),
        ("tab", "\t"),
    ],
)
def test_normalize_delimiter_accepts_known_forms(
    raw: str | None, expected: str | None
) -> None:
    assert normalize_delimiter(raw) == expected


@pytest.mark.parametrize("raw", [";;", "\n", '"'])
def test_normalize_delimiter_rejects_unusable_values(raw: str) -> None:
    with pytest.raises(TabularFileError):
        normalize_delimiter(raw)


def test_gbk_encoded_csv_is_decoded() -> None:
    frame = build_frame("gbk.csv", "编号,名称\n1,张三\n2,李四\n".encode("gbk"))

    assert list(frame.columns) == ["编号", "名称"]
    assert frame["名称"].tolist() == ["张三", "李四"]


def test_excel_preview_lists_sheets_and_follows_the_selection() -> None:
    content = _xlsx_bytes()

    first = preview("report.xlsx", content)
    assert first["sheets"] == ["Data", "Notes"]
    assert first["sheet"] == "Data"
    assert first["detected_header_row"] == 1

    notes = preview("report.xlsx", content, sheet="Notes")
    assert notes["sheet"] == "Notes"
    assert notes["column_names"] == ["x", "y"]


def test_excel_build_uses_the_selected_sheet() -> None:
    frame = build_frame("report.xlsx", _xlsx_bytes(), sheet="Data", header_row=1)

    assert list(frame.columns) == ["ID", "Region", "Total"]
    assert frame.iloc[0].tolist() == [1, "North", 100]


def test_parquet_needs_no_header_row_but_accepts_renames() -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    content = frame_to_parquet(frame)

    result = preview("data.parquet", content)
    assert result["supports_header_row"] is False
    assert result["column_names"] == ["a", "b"]

    rebuilt = build_frame("data.parquet", content, columns=["id", "label"])
    assert list(rebuilt.columns) == ["id", "label"]


def test_duplicate_names_are_made_distinct_case_insensitively() -> None:
    frame = build_frame(
        "x.csv",
        b"a,b,c\n1,2,3\n",
        columns=["Name", "name", "NAME"],
    )

    assert list(frame.columns) == ["Name", "name_2", "NAME_3"]


def test_blank_names_fall_back_to_positional_names() -> None:
    frame = build_frame("x.csv", b"a,b,c\n1,2,3\n", columns=["id", "", "  "])

    assert list(frame.columns) == ["id", "Column 2", "Column 3"]


def test_a_header_row_with_no_data_left_is_rejected() -> None:
    with pytest.raises(TabularFileError, match="no data rows"):
        build_frame("x.csv", b"a,b\n", header_row=0)


def test_header_row_past_the_end_is_rejected() -> None:
    with pytest.raises(TabularFileError, match="past the end"):
        build_frame("x.csv", b"a,b\n1,2\n", header_row=10)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Sales Data", "sales_data"),
        ("2024 sales", "t_2024_sales"),
        ("café", "caf"),
        ("", "data"),
        ("...", "data"),
    ],
)
def test_sanitize_table_name(name: str, expected: str) -> None:
    assert sanitize_table_name(name) == expected


def test_parquet_round_trips_mixed_types_by_falling_back_to_text() -> None:
    frame = pd.DataFrame({"mixed": [1, "two", None]})

    rebuilt = pd.read_parquet(io.BytesIO(frame_to_parquet(frame)))
    values = rebuilt["mixed"].tolist()

    assert values[0] == "1"
    assert values[1] == "two"
    assert pd.isna(values[2])
