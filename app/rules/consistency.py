from __future__ import annotations

import pandas as pd

from app.models import ValidationIssue
from app.utils import get_excel_row_number, is_missing, normalize_scalar, value_for_issue


class UniqueCombinationRule:
    rule_type = "UNIQUE_COMBINATION"

    def validate(
        self,
        object_name: str,
        rule_spec: dict,
        template_data: dict[str, pd.DataFrame],
    ) -> list[ValidationIssue]:
        sheet_name = rule_spec.get("sheet")
        fields = list(rule_spec.get("fields", []) or [])
        message = rule_spec.get("message") or f"{' + '.join(fields)} must be unique."
        df = template_data.get(sheet_name)

        if df is None:
            return [
                ValidationIssue(
                    object_name=object_name,
                    sheet_name=str(sheet_name),
                    row_number=0,
                    severity="ERROR",
                    rule_type="PROFILE",
                    message=f"Rule references missing sheet '{sheet_name}'.",
                    suggested_fix="Fix the YAML profile or provide the missing sheet.",
                )
            ]

        missing_fields = [field for field in fields if field not in df.columns]
        if missing_fields:
            return [
                ValidationIssue(
                    object_name=object_name,
                    sheet_name=str(sheet_name),
                    row_number=0,
                    field_name=", ".join(missing_fields),
                    severity="ERROR",
                    rule_type="PROFILE",
                    message="Unique combination rule references missing field(s): "
                    + ", ".join(missing_fields),
                    suggested_fix="Fix the YAML profile or template columns.",
                )
            ]

        issues: list[ValidationIssue] = []
        seen: dict[tuple[str, ...], int] = {}
        for fallback, (_, row) in enumerate(df.iterrows()):
            key = tuple(normalize_scalar(row.get(field)) for field in fields)
            if any(part == "" for part in key):
                continue
            if key in seen:
                issues.append(
                    ValidationIssue(
                        object_name=object_name,
                        sheet_name=str(sheet_name),
                        row_number=get_excel_row_number(row, fallback),
                        field_name=", ".join(fields),
                        value=" | ".join(key),
                        severity="ERROR",
                        rule_type=self.rule_type,
                        message=message,
                        suggested_fix=f"Make {' + '.join(fields)} unique or remove the duplicate row.",
                    )
                )
            else:
                seen[key] = get_excel_row_number(row, fallback)
        return issues


class ExistsInSheetRule:
    rule_type = "EXISTS_IN_SHEET"

    def validate(
        self,
        object_name: str,
        rule_spec: dict,
        template_data: dict[str, pd.DataFrame],
    ) -> list[ValidationIssue]:
        source_sheet = rule_spec.get("source_sheet")
        source_field = rule_spec.get("source_field")
        target_sheet = rule_spec.get("target_sheet")
        target_field = rule_spec.get("target_field")
        message = rule_spec.get("message") or (
            f"{source_field} in {source_sheet} must exist in {target_sheet}."
        )

        source_df = template_data.get(source_sheet)
        target_df = template_data.get(target_sheet)
        profile_issues = self._validate_shape(
            object_name,
            source_sheet,
            source_field,
            target_sheet,
            target_field,
            source_df,
            target_df,
        )
        if profile_issues:
            return profile_issues

        assert source_df is not None
        assert target_df is not None
        target_values = {
            normalize_scalar(value)
            for value in target_df[target_field]
            if not is_missing(value)
        }

        issues: list[ValidationIssue] = []
        for fallback, (_, row) in enumerate(source_df.iterrows()):
            value = row.get(source_field)
            if is_missing(value):
                continue
            clean_value = normalize_scalar(value)
            if clean_value not in target_values:
                issues.append(
                    ValidationIssue(
                        object_name=object_name,
                        sheet_name=str(source_sheet),
                        row_number=get_excel_row_number(row, fallback),
                        field_name=str(source_field),
                        value=value_for_issue(value),
                        severity="ERROR",
                        rule_type=self.rule_type,
                        message=message,
                        suggested_fix=f"Create matching {target_field} in {target_sheet} or correct the value.",
                    )
                )
        return issues

    def _validate_shape(
        self,
        object_name: str,
        source_sheet: str,
        source_field: str,
        target_sheet: str,
        target_field: str,
        source_df: pd.DataFrame | None,
        target_df: pd.DataFrame | None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if source_df is None:
            issues.append(self._profile_issue(object_name, str(source_sheet), f"Missing sheet '{source_sheet}'."))
        elif source_field not in source_df.columns:
            issues.append(
                self._profile_issue(
                    object_name,
                    str(source_sheet),
                    f"Missing field '{source_field}' in source sheet.",
                    str(source_field),
                )
            )
        if target_df is None:
            issues.append(self._profile_issue(object_name, str(target_sheet), f"Missing sheet '{target_sheet}'."))
        elif target_field not in target_df.columns:
            issues.append(
                self._profile_issue(
                    object_name,
                    str(target_sheet),
                    f"Missing field '{target_field}' in target sheet.",
                    str(target_field),
                )
            )
        return issues

    def _profile_issue(
        self,
        object_name: str,
        sheet_name: str,
        message: str,
        field_name: str | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            object_name=object_name,
            sheet_name=sheet_name,
            row_number=0,
            field_name=field_name,
            severity="ERROR",
            rule_type="PROFILE",
            message=message,
            suggested_fix="Fix the YAML profile or uploaded template.",
        )

