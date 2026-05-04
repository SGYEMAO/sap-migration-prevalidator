from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from app.utils import prepare_dataframe


ExcelFileInput = str | BinaryIO | Any


def _rewind_if_possible(file: ExcelFileInput) -> None:
    if hasattr(file, "seek"):
        file.seek(0)


def _display_name(file: ExcelFileInput) -> str:
    if isinstance(file, (str, Path)):
        return Path(file).name
    return str(getattr(file, "name", "uploaded template file"))


def load_template_excel(file: ExcelFileInput) -> dict[str, pd.DataFrame]:
    """Read every sheet in an uploaded SAP migration template."""
    _rewind_if_possible(file)
    if _display_name(file).lower().endswith(".csv"):
        return {"Sheet1": prepare_dataframe(pd.read_csv(file, dtype=object), header_row=1)}

    template_data: dict[str, pd.DataFrame] = {}
    with pd.ExcelFile(file) as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=0, dtype=object)
            template_data[sheet_name] = prepare_dataframe(df, header_row=1)
    return template_data


def load_template_excel_with_profile(
    file: ExcelFileInput,
    profile: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    """Read sheets with the header rows declared by the YAML profile."""
    _rewind_if_possible(file)
    if _display_name(file).lower().endswith(".csv"):
        sheet_name = next(iter((profile.get("sheets", {}) or {}).keys()), "Sheet1")
        header_row = int(((profile.get("sheets", {}) or {}).get(sheet_name, {}) or {}).get("header_row", 1))
        return {
            sheet_name: prepare_dataframe(
                pd.read_csv(file, dtype=object, header=header_row - 1),
                header_row=header_row,
            )
        }

    template_data: dict[str, pd.DataFrame] = {}
    sheet_profiles = profile.get("sheets", {}) or {}

    with pd.ExcelFile(file) as workbook:
        for sheet_name in workbook.sheet_names:
            sheet_spec = sheet_profiles.get(sheet_name, {})
            header_row = int(sheet_spec.get("header_row", 1))
            df = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                header=header_row - 1,
                dtype=object,
            )
            template_data[sheet_name] = prepare_dataframe(df, header_row=header_row)
    return template_data
