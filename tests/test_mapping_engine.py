from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.mapping_engine import apply_mappings, load_mapping_files
from app.utils import prepare_dataframe


def test_mapping_exact(tmp_path: Path) -> None:
    mapping_path = tmp_path / "uom_mapping.xlsx"
    _write_mapping(
        mapping_path,
        [
            {"LegacyUoM": "Each", "SAPUoM": "EA", "Active": "Y", "Comment": "unit"},
            {"LegacyUoM": "KG", "SAPUoM": "KG", "Active": "Y", "Comment": "same"},
        ],
    )
    profile = _profile(strategy="exact")
    template_data = {
        "Basic Data": prepare_dataframe(pd.DataFrame([{"BaseUoM": "Each"}, {"BaseUoM": "KG"}]))
    }

    mappings = load_mapping_files(profile, {"uom_mapping.xlsx": mapping_path})
    mapped_data, actions = apply_mappings("MATERIAL_MASTER", profile, template_data, mappings)

    assert mapped_data["Basic Data"]["BaseUoM"].tolist() == ["EA", "KG"]
    assert [action.status for action in actions] == ["MAPPED", "UNCHANGED"]


def test_mapping_case_insensitive(tmp_path: Path) -> None:
    mapping_path = tmp_path / "uom_mapping.xlsx"
    _write_mapping(
        mapping_path,
        [{"LegacyUoM": "each", "SAPUoM": "EA", "Active": "Y", "Comment": "unit"}],
    )
    profile = _profile(strategy="case_insensitive")
    template_data = {
        "Basic Data": prepare_dataframe(pd.DataFrame([{"BaseUoM": "EACH"}]))
    }

    mappings = load_mapping_files(profile, {"uom_mapping.xlsx": mapping_path})
    mapped_data, actions = apply_mappings("MATERIAL_MASTER", profile, template_data, mappings)

    assert mapped_data["Basic Data"].loc[0, "BaseUoM"] == "EA"
    assert actions[0].status == "MAPPED"


def test_mapping_duplicate_legacy_value_ambiguous(tmp_path: Path) -> None:
    mapping_path = tmp_path / "uom_mapping.xlsx"
    _write_mapping(
        mapping_path,
        [
            {"LegacyUoM": "Each", "SAPUoM": "EA", "Active": "Y", "Comment": "first"},
            {"LegacyUoM": "Each", "SAPUoM": "PC", "Active": "Y", "Comment": "duplicate"},
        ],
    )
    profile = _profile(strategy="exact")
    template_data = {
        "Basic Data": prepare_dataframe(pd.DataFrame([{"BaseUoM": "Each"}]))
    }

    mappings = load_mapping_files(profile, {"uom_mapping.xlsx": mapping_path})
    mapped_data, actions = apply_mappings("MATERIAL_MASTER", profile, template_data, mappings)

    assert mapped_data["Basic Data"].loc[0, "BaseUoM"] == "Each"
    assert actions[0].status == "AMBIGUOUS"


def test_mapping_inactive_row_ignored(tmp_path: Path) -> None:
    mapping_path = tmp_path / "uom_mapping.xlsx"
    _write_mapping(
        mapping_path,
        [{"LegacyUoM": "Each", "SAPUoM": "EA", "Active": "N", "Comment": "inactive"}],
    )
    profile = _profile(strategy="exact")
    template_data = {
        "Basic Data": prepare_dataframe(pd.DataFrame([{"BaseUoM": "Each"}]))
    }

    mappings = load_mapping_files(profile, {"uom_mapping.xlsx": mapping_path})
    mapped_data, actions = apply_mappings("MATERIAL_MASTER", profile, template_data, mappings)

    assert mapped_data["Basic Data"].loc[0, "BaseUoM"] == "Each"
    assert actions[0].status == "UNMAPPED"


def _profile(strategy: str) -> dict:
    return {
        "mappings": {
            "base_uom": {
                "filename": "uom_mapping.xlsx",
                "sheet": "Sheet1",
                "source_column": "LegacyUoM",
                "target_column": "SAPUoM",
                "target_field": {"sheet": "Basic Data", "field": "BaseUoM"},
                "strategy": strategy,
                "on_missing": "keep_original",
                "severity_on_missing": "WARNING",
            }
        }
    }


def _write_mapping(path: Path, rows: list[dict]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Sheet1", index=False)
