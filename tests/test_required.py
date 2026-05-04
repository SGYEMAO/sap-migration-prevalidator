from __future__ import annotations

import pandas as pd

from app.rule_engine import run_validation
from app.utils import prepare_dataframe


def test_required_field_validation() -> None:
    profile = {
        "sheets": {
            "Basic Data": {
                "fields": {
                    "Material": {"required": True},
                    "MaterialType": {"required": True},
                }
            }
        }
    }
    template_data = {
        "Basic Data": prepare_dataframe(
            pd.DataFrame(
                [
                    {"Material": "MAT001", "MaterialType": "FERT"},
                    {"Material": "MAT002", "MaterialType": ""},
                ]
            )
        )
    }

    result = run_validation("MATERIAL_MASTER", profile, template_data, {})

    assert result.error_count == 1
    assert result.issues[0].field_name == "MaterialType"
    assert result.issues[0].row_number == 3

