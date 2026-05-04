from __future__ import annotations

import pandas as pd

from app.rule_engine import run_validation
from app.utils import prepare_dataframe


def test_config_single_key_validation() -> None:
    profile = {
        "config_sources": {"plant": {"filename": "plant.xlsx", "key_columns": ["Plant"]}},
        "sheets": {
            "Plant Data": {
                "fields": {
                    "Plant": {
                        "required": True,
                        "config_check": "plant",
                        "config_key_mapping": {"Plant": "Plant"},
                    }
                }
            }
        },
    }
    template_data = {
        "Plant Data": prepare_dataframe(pd.DataFrame([{"Plant": "1000"}, {"Plant": "9999"}]))
    }
    config_data = {"plant": prepare_dataframe(pd.DataFrame([{"Plant": "1000"}]))}

    result = run_validation("MATERIAL_MASTER", profile, template_data, config_data)

    assert result.error_count == 1
    assert "9999" in result.issues[0].message


def test_config_composite_key_validation() -> None:
    profile = {
        "config_sources": {
            "storage_location": {
                "filename": "storage_location.xlsx",
                "key_columns": ["Plant", "StorageLocation"],
            }
        },
        "sheets": {
            "Plant Data": {
                "fields": {
                    "Plant": {"required": True},
                    "StorageLocation": {
                        "required": False,
                        "config_check": "storage_location",
                        "config_key_mapping": {
                            "Plant": "Plant",
                            "StorageLocation": "StorageLocation",
                        },
                    },
                }
            }
        },
    }
    template_data = {
        "Plant Data": prepare_dataframe(
            pd.DataFrame(
                [
                    {"Plant": "1000", "StorageLocation": "0001"},
                    {"Plant": "1000", "StorageLocation": "9999"},
                ]
            )
        )
    }
    config_data = {
        "storage_location": prepare_dataframe(
            pd.DataFrame([{"Plant": "1000", "StorageLocation": "0001"}])
        )
    }

    result = run_validation("MATERIAL_MASTER", profile, template_data, config_data)

    assert result.error_count == 1
    assert result.issues[0].field_name == "StorageLocation"
    assert "combination" in result.issues[0].message

