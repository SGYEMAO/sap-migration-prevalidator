from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd


EXCEL_ROW_COLUMN = "__excel_row_number"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_column_name(column: Any) -> str:
    if pd.isna(column):
        return ""
    name = str(column).strip()
    return "" if name.startswith("Unnamed:") else name


def trim_cell(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return isinstance(value, str) and value.strip() == ""


def normalize_scalar(value: Any) -> str:
    if is_missing(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def value_for_issue(value: Any) -> str | int | float | None:
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (str, int, float)):
        return trim_cell(value)
    return str(value)


def trim_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned.columns = [normalize_column_name(column) for column in cleaned.columns]

    keep_positions: list[int] = []
    keep_columns: list[str] = []
    for position, column in enumerate(cleaned.columns):
        series = cleaned.iloc[:, position]
        if column or not series.map(is_missing).all():
            keep_positions.append(position)
            keep_columns.append(column)

    cleaned = cleaned.iloc[:, keep_positions] if keep_positions else pd.DataFrame()
    cleaned.columns = keep_columns

    for column in cleaned.columns:
        if column != EXCEL_ROW_COLUMN:
            cleaned[column] = cleaned[column].map(trim_cell)
    return cleaned


def drop_empty_rows(
    df: pd.DataFrame,
    protected_columns: Iterable[str] = (EXCEL_ROW_COLUMN,),
) -> pd.DataFrame:
    protected = set(protected_columns)
    content_columns = [column for column in df.columns if column not in protected]
    if not content_columns:
        return df.iloc[0:0].copy()
    empty_mask = df[content_columns].apply(lambda row: all(is_missing(value) for value in row), axis=1)
    return df.loc[~empty_mask].copy()


def prepare_dataframe(df: pd.DataFrame, header_row: int = 1) -> pd.DataFrame:
    cleaned = df.copy()
    if EXCEL_ROW_COLUMN not in cleaned.columns:
        cleaned.insert(0, EXCEL_ROW_COLUMN, [index + header_row + 1 for index in range(len(cleaned))])
    cleaned = trim_dataframe(cleaned)
    cleaned = drop_empty_rows(cleaned)
    return cleaned.reset_index(drop=True)


def get_excel_row_number(row: pd.Series, fallback: int = 0) -> int:
    value = row.get(EXCEL_ROW_COLUMN)
    if not is_missing(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            pass
    return fallback + 2


def issue_sort_key(issue: Any) -> tuple[str, int, str]:
    return (issue.sheet_name, issue.row_number, issue.field_name or "")

