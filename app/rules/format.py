from __future__ import annotations

from typing import Any

import pandas as pd

from app.models import ValidationIssue
from app.utils import get_excel_row_number, is_missing, normalize_scalar, value_for_issue


class MaxLengthRule:
    rule_type = "MAX_LENGTH"

    def validate(
        self,
        object_name: str,
        sheet_name: str,
        df: pd.DataFrame,
        fields: dict[str, dict[str, Any]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for field_name, field_spec in fields.items():
            max_length = field_spec.get("max_length")
            if max_length is None or field_name not in df.columns:
                continue
            max_length = int(max_length)
            for fallback, (_, row) in enumerate(df.iterrows()):
                value = row.get(field_name)
                if is_missing(value):
                    continue
                text = normalize_scalar(value)
                if len(text) > max_length:
                    issues.append(
                        ValidationIssue(
                            object_name=object_name,
                            sheet_name=sheet_name,
                            row_number=get_excel_row_number(row, fallback),
                            field_name=field_name,
                            value=value_for_issue(value),
                            severity="ERROR",
                            rule_type=self.rule_type,
                            message=(
                                f"{field_name} exceeds max length {max_length} "
                                f"with length {len(text)}."
                            ),
                            suggested_fix=f"Shorten {field_name} to {max_length} characters or fewer.",
                        )
                    )
        return issues

