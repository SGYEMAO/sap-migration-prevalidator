from __future__ import annotations

from typing import Any

import pandas as pd

from app.models import ValidationIssue
from app.utils import get_excel_row_number, is_missing, value_for_issue


class RequiredRule:
    rule_type = "REQUIRED"

    def validate(
        self,
        object_name: str,
        sheet_name: str,
        df: pd.DataFrame,
        fields: dict[str, dict[str, Any]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        required_fields = [
            field_name for field_name, spec in fields.items() if bool(spec.get("required", False))
        ]
        for field_name in required_fields:
            if field_name not in df.columns:
                issues.append(
                    ValidationIssue(
                        object_name=object_name,
                        sheet_name=sheet_name,
                        row_number=0,
                        field_name=field_name,
                        severity="ERROR",
                        rule_type=self.rule_type,
                        message=f"Required column '{field_name}' is missing from sheet '{sheet_name}'.",
                        suggested_fix=f"Add the '{field_name}' column to sheet '{sheet_name}'.",
                    )
                )
                continue

            for fallback, (_, row) in enumerate(df.iterrows()):
                value = row.get(field_name)
                if is_missing(value):
                    issues.append(
                        ValidationIssue(
                            object_name=object_name,
                            sheet_name=sheet_name,
                            row_number=get_excel_row_number(row, fallback),
                            field_name=field_name,
                            value=value_for_issue(value),
                            severity="ERROR",
                            rule_type=self.rule_type,
                            message=f"{field_name} is required.",
                            suggested_fix=f"Provide a value for {field_name}.",
                        )
                    )
        return issues

