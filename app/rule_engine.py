from __future__ import annotations

from typing import Any

import pandas as pd

from app.models import ValidationIssue, ValidationResult
from app.rules import ConfigExistenceRule, ExistsInSheetRule, MaxLengthRule, RequiredRule
from app.rules import UniqueCombinationRule
from app.utils import issue_sort_key


def run_validation(
    object_name: str,
    profile: dict[str, Any],
    template_data: dict[str, pd.DataFrame],
    config_data: dict[str, pd.DataFrame],
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    total_rows = _count_expected_rows(profile, template_data)

    required_rule = RequiredRule()
    max_length_rule = MaxLengthRule()
    config_rule = ConfigExistenceRule()

    for sheet_name, sheet_profile in (profile.get("sheets", {}) or {}).items():
        df = template_data.get(sheet_name)
        if df is None:
            issues.append(
                ValidationIssue(
                    object_name=object_name,
                    sheet_name=sheet_name,
                    row_number=0,
                    severity="ERROR",
                    rule_type="TEMPLATE_STRUCTURE",
                    message=f"Required sheet '{sheet_name}' is missing.",
                    suggested_fix=f"Add sheet '{sheet_name}' to the migration template.",
                )
            )
            continue

        fields = sheet_profile.get("fields", {}) or {}
        issues.extend(required_rule.validate(object_name, sheet_name, df, fields))
        issues.extend(max_length_rule.validate(object_name, sheet_name, df, fields))
        issues.extend(config_rule.validate(object_name, sheet_name, df, fields, config_data, profile))

    for rule_spec in profile.get("cross_sheet_rules", []) or []:
        rule_type = rule_spec.get("type")
        if rule_type == "unique_combination":
            issues.extend(UniqueCombinationRule().validate(object_name, rule_spec, template_data))
        elif rule_type == "exists_in_sheet":
            issues.extend(ExistsInSheetRule().validate(object_name, rule_spec, template_data))
        else:
            issues.append(
                ValidationIssue(
                    object_name=object_name,
                    sheet_name=str(rule_spec.get("sheet") or rule_spec.get("source_sheet") or ""),
                    row_number=0,
                    severity="ERROR",
                    rule_type="PROFILE",
                    message=f"Unsupported cross sheet rule type '{rule_type}'.",
                    suggested_fix="Use a supported rule type in the YAML profile.",
                )
            )

    issues = sorted(issues, key=issue_sort_key)
    return ValidationResult.from_issues(object_name=object_name, total_rows=total_rows, issues=issues)


def _count_expected_rows(profile: dict[str, Any], template_data: dict[str, pd.DataFrame]) -> int:
    expected_sheets = (profile.get("sheets", {}) or {}).keys()
    return sum(len(template_data[sheet_name]) for sheet_name in expected_sheets if sheet_name in template_data)

