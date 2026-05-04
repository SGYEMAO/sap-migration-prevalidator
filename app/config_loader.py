from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from app.utils import prepare_dataframe, trim_dataframe


class ConfigLoaderError(ValueError):
    pass


UploadedConfig = str | Path | BinaryIO | Any


def _rewind_if_possible(file: UploadedConfig) -> None:
    if hasattr(file, "seek"):
        file.seek(0)


def _display_name(file: UploadedConfig) -> str:
    if isinstance(file, (str, Path)):
        return Path(file).name
    return str(getattr(file, "name", "uploaded config file"))


def _load_tabular_file(file: UploadedConfig, sheet_name: str | None = None) -> pd.DataFrame:
    name = _display_name(file).lower()
    _rewind_if_possible(file)
    if name.endswith(".csv"):
        df = pd.read_csv(file, dtype=object)
        return trim_dataframe(df)
    if name.endswith(".xlsx") or name.endswith(".xlsm") or name.endswith(".xls"):
        df = pd.read_excel(file, sheet_name=sheet_name or 0, dtype=object)
        return trim_dataframe(df)
    raise ConfigLoaderError(f"Unsupported config file type for '{_display_name(file)}'.")


def _lookup_uploaded_file(
    uploaded_files: dict[str, UploadedConfig],
    source_name: str,
    filename: str,
) -> UploadedConfig | None:
    if source_name in uploaded_files:
        return uploaded_files[source_name]
    if filename in uploaded_files:
        return uploaded_files[filename]
    lower_filename = filename.lower()
    for key, value in uploaded_files.items():
        if key.lower() == lower_filename:
            return value
        value_name = getattr(value, "name", "")
        if value_name and Path(value_name).name.lower() == lower_filename:
            return value
    return None


def load_config_files(
    profile: dict[str, Any],
    uploaded_files: dict[str, UploadedConfig] | None = None,
    fallback_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load every config source declared by a profile.

    Uploaded files can be keyed either by logical source name, for example
    ``plant``, or by the expected filename, for example ``plant.xlsx``.
    """
    uploaded_files = uploaded_files or {}
    config_data: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for source_name, source_spec in (profile.get("config_sources", {}) or {}).items():
        filename = str(source_spec.get("filename", "")).strip()
        if not filename:
            raise ConfigLoaderError(f"Config source '{source_name}' is missing a filename.")

        file = _lookup_uploaded_file(uploaded_files, source_name, filename)
        if file is None and fallback_dir is not None:
            candidate = Path(fallback_dir) / filename
            if candidate.exists():
                file = candidate
        if file is None:
            missing.append(filename)
            continue

        df = _load_tabular_file(file, source_spec.get("sheet"))
        key_columns = [str(column).strip() for column in source_spec.get("key_columns", [])]
        missing_columns = [column for column in key_columns if column not in df.columns]
        if missing_columns:
            raise ConfigLoaderError(
                f"Config file '{filename}' is missing required column(s): "
                + ", ".join(missing_columns)
            )
        config_data[source_name] = prepare_dataframe(df, header_row=1)

    if missing:
        raise ConfigLoaderError("Missing config file(s): " + ", ".join(sorted(missing)))
    return config_data


def load_config_files_from_dir(
    profile: dict[str, Any],
    config_dir: Path,
) -> dict[str, pd.DataFrame]:
    """Load required config files from a configured directory."""
    return load_config_files(profile, uploaded_files={}, fallback_dir=config_dir)
