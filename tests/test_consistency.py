from __future__ import annotations

import pandas as pd

from app.rule_engine import run_validation
from app.utils import prepare_dataframe


def test_unique_combination_validation() -> None:
    profile = {
        "sheets": {
            "Plant Data": {"fields": {"Material": {"required": True}, "Plant": {"required": True}}}
        },
        "cross_sheet_rules": [
            {
                "type": "unique_combination",
                "sheet": "Plant Data",
                "fields": ["Material", "Plant"],
                "message": "Material + Plant must be unique in Plant Data.",
            }
        ],
    }
    template_data = {
        "Plant Data": prepare_dataframe(
            pd.DataFrame(
                [
                    {"Material": "MAT001", "Plant": "1000"},
                    {"Material": "MAT001", "Plant": "1000"},
                ]
            )
        )
    }

    result = run_validation("MATERIAL_MASTER", profile, template_data, {})

    assert result.error_count == 1
    assert result.issues[0].rule_type == "UNIQUE_COMBINATION"
    assert result.issues[0].row_number == 3


def test_exists_in_sheet_validation() -> None:
    profile = {
        "sheets": {
            "Basic Data": {"fields": {"Material": {"required": True}}},
            "Plant Data": {"fields": {"Material": {"required": True}}},
        },
        "cross_sheet_rules": [
            {
                "type": "exists_in_sheet",
                "source_sheet": "Plant Data",
                "source_field": "Material",
                "target_sheet": "Basic Data",
                "target_field": "Material",
                "message": "Material in Plant Data must exist in Basic Data.",
            }
        ],
    }
    template_data = {
        "Basic Data": prepare_dataframe(pd.DataFrame([{"Material": "MAT001"}])),
        "Plant Data": prepare_dataframe(pd.DataFrame([{"Material": "MAT002"}])),
    }

    result = run_validation("MATERIAL_MASTER", profile, template_data, {})

    assert result.error_count == 1
    assert result.issues[0].rule_type == "EXISTS_IN_SHEET"
    assert result.issues[0].value == "MAT002"

