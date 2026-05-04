from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from app.models import MappingAction
from app.utils import get_excel_row_number, is_missing, normalize_scalar, trim_dataframe, value_for_issue


class MappingLoaderError(ValueError):
    pass


UploadedMapping = str | Path | BinaryIO | Any
SUPPORTED_STRATEGIES = {"exact", "case_insensitive", "trim_upper"}
logger = logging.getLogger(__name__)


def load_mapping_files(
    profile: dict[str, Any],
    mapping_files: dict[str, UploadedMapping],
) -> dict:
    """Load and normalize all mapping files declared by a profile."""
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for mapping_name, mapping_spec in (profile.get("mappings", {}) or {}).items():
        filename = str(mapping_spec.get("filename", "")).strip()
        if not filename:
            errors.append(f"Mapping '{mapping_name}' is missing a filename.")
            continue

        strategy = str(mapping_spec.get("strategy", "exact")).strip()
        if strategy not in SUPPORTED_STRATEGIES:
            errors.append(
                f"Mapping '{mapping_name}' uses unsupported strategy '{strategy}'. "
                f"Supported strategies: {', '.join(sorted(SUPPORTED_STRATEGIES))}."
            )
            continue

        file = _lookup_mapping_file(mapping_files, mapping_name, filename)
        if file is None:
            errors.append(f"Missing mapping file: {filename}")
            continue

        try:
            df = _load_mapping_dataframe(file, mapping_spec.get("sheet"))
            loaded[mapping_name] = _build_mapping_lookup(mapping_name, mapping_spec, df)
        except MappingLoaderError as exc:
            errors.append(str(exc))

    if errors:
        raise MappingLoaderError("; ".join(errors))
    return loaded


def load_mapping_files_from_dir(profile: dict[str, Any], mapping_dir: Path) -> dict:
    """Load available mapping files from a directory without failing on missing files."""
    loaded: dict = {}
    for mapping_name, mapping_spec in (profile.get("mappings", {}) or {}).items():
        filename = str(mapping_spec.get("filename", "")).strip()
        if not filename:
            logger.warning("Mapping '%s' is missing a filename; mapping skipped.", mapping_name)
            continue

        candidate = Path(mapping_dir) / filename
        if not candidate.exists():
            logger.warning("Missing mapping file %s; mapping '%s' skipped.", candidate, mapping_name)
            continue

        partial_profile = {**profile, "mappings": {mapping_name: mapping_spec}}
        try:
            loaded.update(load_mapping_files(partial_profile, {mapping_name: candidate, filename: candidate}))
        except MappingLoaderError as exc:
            logger.warning("Mapping '%s' could not be loaded and was skipped: %s", mapping_name, exc)
    return loaded


def apply_mappings(
    object_name: str,
    profile: dict,
    template_data: dict[str, pd.DataFrame],
    mappings: dict,
) -> tuple[dict[str, pd.DataFrame], list[MappingAction]]:
    """Apply deterministic mappings to template data and return audit actions."""
    mapped_template_data = {sheet_name: df.copy(deep=True) for sheet_name, df in template_data.items()}
    actions: list[MappingAction] = []

    for mapping_name, mapping in mappings.items():
        spec = mapping.get("spec", {}) or {}
        target_field = spec.get("target_field", {}) or {}
        sheet_name = str(target_field.get("sheet", "")).strip()
        field_name = str(target_field.get("field", "")).strip()
        if not sheet_name or not field_name:
            actions.append(
                _mapping_action(
                    object_name=object_name,
                    sheet_name=sheet_name,
                    row_number=0,
                    field_name=field_name or mapping_name,
                    original_value=None,
                    mapped_value=None,
                    mapping_name=mapping_name,
                    status="UNMAPPED",
                    message="Mapping profile is missing target_field.sheet or target_field.field.",
                )
            )
            continue

        df = mapped_template_data.get(sheet_name)
        if df is None:
            actions.append(
                _mapping_action(
                    object_name=object_name,
                    sheet_name=sheet_name,
                    row_number=0,
                    field_name=field_name,
                    original_value=None,
                    mapped_value=None,
                    mapping_name=mapping_name,
                    status="UNMAPPED",
                    message=f"Target sheet '{sheet_name}' is missing.",
                )
            )
            continue
        if field_name not in df.columns:
            actions.append(
                _mapping_action(
                    object_name=object_name,
                    sheet_name=sheet_name,
                    row_number=0,
                    field_name=field_name,
                    original_value=None,
                    mapped_value=None,
                    mapping_name=mapping_name,
                    status="UNMAPPED",
                    message=f"Target field '{field_name}' is missing from sheet '{sheet_name}'.",
                )
            )
            continue

        lookup = mapping.get("lookup", {}) or {}
        duplicate_keys = mapping.get("duplicate_keys", set()) or set()
        strategy = str(mapping.get("strategy", "exact"))
        on_missing = str(spec.get("on_missing", "keep_original"))
        severity_on_missing = str(spec.get("severity_on_missing", "WARNING"))

        for fallback, (index, row) in enumerate(df.iterrows()):
            original_value = row.get(field_name)
            if is_missing(original_value):
                continue

            lookup_key = _strategy_key(original_value, strategy)
            row_number = get_excel_row_number(row, fallback)
            if lookup_key in duplicate_keys:
                actions.append(
                    _mapping_action(
                        object_name=object_name,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        field_name=field_name,
                        original_value=original_value,
                        mapped_value=None,
                        mapping_name=mapping_name,
                        status="AMBIGUOUS",
                        message="Duplicate legacy value in mapping file; value was not changed.",
                    )
                )
                continue

            mapping_entry = lookup.get(lookup_key)
            if mapping_entry is None:
                actions.append(
                    _mapping_action(
                        object_name=object_name,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        field_name=field_name,
                        original_value=original_value,
                        mapped_value=None,
                        mapping_name=mapping_name,
                        status="UNMAPPED",
                        message=(
                            f"No active mapping found; on_missing={on_missing}, "
                            f"severity_on_missing={severity_on_missing}."
                        ),
                    )
                )
                continue

            mapped_value = mapping_entry["mapped_value"]
            if _same_business_value(original_value, mapped_value):
                status = "UNCHANGED"
                message = "Value already matches the configured SAP value."
            else:
                df.at[index, field_name] = mapped_value
                status = "MAPPED"
                message = "Legacy value replaced with configured SAP value."

            actions.append(
                _mapping_action(
                    object_name=object_name,
                    sheet_name=sheet_name,
                    row_number=row_number,
                    field_name=field_name,
                    original_value=original_value,
                    mapped_value=mapped_value,
                    mapping_name=mapping_name,
                    status=status,
                    message=message,
                )
            )

    return mapped_template_data, actions


def _build_mapping_lookup(
    mapping_name: str,
    mapping_spec: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    source_column = str(mapping_spec.get("source_column") or "LegacyValue").strip()
    target_column = str(mapping_spec.get("target_column") or "SAPValue").strip()
    strategy = str(mapping_spec.get("strategy", "exact")).strip()
    required_columns = [source_column, target_column, "Active"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise MappingLoaderError(
            f"Mapping '{mapping_name}' is missing required column(s): "
            + ", ".join(missing_columns)
        )

    entries_by_key: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for index, row in df.iterrows():
        active = normalize_scalar(row.get("Active")).upper()
        if active != "Y":
            continue

        legacy_value = row.get(source_column)
        if is_missing(legacy_value):
            continue

        sap_value = row.get(target_column)
        if is_missing(sap_value):
            errors.append(
                f"Mapping '{mapping_name}' row {index + 2} has blank SAP value "
                f"for legacy value '{normalize_scalar(legacy_value)}'."
            )
            continue

        lookup_key = _strategy_key(legacy_value, strategy)
        entries_by_key.setdefault(lookup_key, []).append(
            {
                "legacy_value": value_for_issue(legacy_value),
                "mapped_value": value_for_issue(sap_value),
                "mapping_row": index + 2,
                "comment": value_for_issue(row.get("Comment")),
            }
        )

    if errors:
        raise MappingLoaderError("; ".join(errors))

    duplicate_keys = {key for key, entries in entries_by_key.items() if len(entries) > 1}
    lookup = {
        key: entries[0]
        for key, entries in entries_by_key.items()
        if key not in duplicate_keys
    }
    return {
        "spec": dict(mapping_spec),
        "source_column": source_column,
        "target_column": target_column,
        "strategy": strategy,
        "lookup": lookup,
        "duplicate_keys": duplicate_keys,
    }


def _load_mapping_dataframe(file: UploadedMapping, sheet_name: str | None = None) -> pd.DataFrame:
    name = _display_name(file).lower()
    _rewind_if_possible(file)
    if name.endswith(".xlsx") or name.endswith(".xlsm") or name.endswith(".xls"):
        df = pd.read_excel(file, sheet_name=sheet_name or 0, dtype=object)
        return trim_dataframe(df)
    if name.endswith(".csv"):
        df = pd.read_csv(file, dtype=object)
        return trim_dataframe(df)
    raise MappingLoaderError(f"Unsupported mapping file type for '{_display_name(file)}'.")


def _lookup_mapping_file(
    mapping_files: dict[str, UploadedMapping],
    mapping_name: str,
    filename: str,
) -> UploadedMapping | None:
    if mapping_name in mapping_files:
        return mapping_files[mapping_name]
    if filename in mapping_files:
        return mapping_files[filename]
    lower_filename = filename.lower()
    for key, value in mapping_files.items():
        if key.lower() == lower_filename:
            return value
        value_name = getattr(value, "name", "")
        if value_name and Path(value_name).name.lower() == lower_filename:
            return value
    return None


def _display_name(file: UploadedMapping) -> str:
    if isinstance(file, (str, Path)):
        return Path(file).name
    return str(getattr(file, "name", "uploaded mapping file"))


def _rewind_if_possible(file: UploadedMapping) -> None:
    if hasattr(file, "seek"):
        file.seek(0)


def _strategy_key(value: Any, strategy: str) -> str:
    normalized = normalize_scalar(value)
    if strategy == "case_insensitive":
        return normalized.casefold()
    if strategy == "trim_upper":
        return normalized.upper()
    return normalized


def _same_business_value(left: Any, right: Any) -> bool:
    return normalize_scalar(left) == normalize_scalar(right)


def _mapping_action(
    object_name: str,
    sheet_name: str,
    row_number: int,
    field_name: str,
    original_value: Any,
    mapped_value: Any,
    mapping_name: str,
    status: str,
    message: str | None = None,
) -> MappingAction:
    return MappingAction(
        object_name=object_name,
        sheet_name=sheet_name,
        row_number=row_number,
        field_name=field_name,
        original_value=value_for_issue(original_value),
        mapped_value=value_for_issue(mapped_value),
        mapping_name=mapping_name,
        status=status,
        message=message,
    )
