from __future__ import annotations

from typing import Any

import pandas as pd

from app.models import ValidationIssue
from app.utils import get_excel_row_number, is_missing, normalize_scalar, value_for_issue


class ConfigExistenceRule:
    rule_type = "CONFIG_CHECK"

    def validate(
        self,
        object_name: str,
        sheet_name: str,
        df: pd.DataFrame,
        fields: dict[str, dict[str, Any]],
        config_data: dict[str, pd.DataFrame],
        profile: dict[str, Any],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        config_sources = profile.get("config_sources", {}) or {}

        for field_name, field_spec in fields.items():
            source_name = field_spec.get("config_check")
            if not source_name:
                continue
            mapping = field_spec.get("config_key_mapping", {}) or {}
            if not mapping:
                issues.append(
                    self._profile_issue(
                        object_name,
                        sheet_name,
                        field_name,
                        f"Field '{field_name}' declares config_check but no config_key_mapping.",
                    )
                )
                continue

            if source_name not in config_data:
                issues.append(
                    self._profile_issue(
                        object_name,
                        sheet_name,
                        field_name,
                        f"Config source '{source_name}' is not loaded.",
                    )
                )
                continue

            template_fields = list(mapping.values())
            missing_template_fields = [
                template_field for template_field in template_fields if template_field not in df.columns
            ]
            if missing_template_fields:
                issues.append(
                    self._profile_issue(
                        object_name,
                        sheet_name,
                        field_name,
                        "Template sheet is missing required config-check field(s): "
                        + ", ".join(missing_template_fields),
                    )
                )
                continue

            config_df = config_data[source_name]
            config_key_columns = list(mapping.keys())
            missing_config_columns = [
                config_column for config_column in config_key_columns if config_column not in config_df.columns
            ]
            if missing_config_columns:
                issues.append(
                    self._profile_issue(
                        object_name,
                        sheet_name,
                        field_name,
                        f"Config source '{source_name}' is missing key column(s): "
                        + ", ".join(missing_config_columns),
                    )
                )
                continue

            reference_keys = {
                tuple(normalize_scalar(config_row.get(config_column)) for config_column in config_key_columns)
                for _, config_row in config_df.iterrows()
            }
            source_filename = str(config_sources.get(source_name, {}).get("filename", source_name))

            for fallback, (_, row) in enumerate(df.iterrows()):
                if field_name in df.columns and is_missing(row.get(field_name)):
                    continue
                key = tuple(normalize_scalar(row.get(template_field)) for template_field in template_fields)
                if any(part == "" for part in key):
                    continue
                if key not in reference_keys:
                    field_value = row.get(field_name) if field_name in df.columns else None
                    issues.append(
                        ValidationIssue(
                            object_name=object_name,
                            sheet_name=sheet_name,
                            row_number=get_excel_row_number(row, fallback),
                            field_name=field_name,
                            value=value_for_issue(field_value),
                            severity="ERROR",
                            rule_type=self.rule_type,
                            message=self._message(
                                field_name=field_name,
                                field_value=field_value,
                                template_fields=template_fields,
                                key=key,
                                source_name=source_name,
                            ),
                            suggested_fix=f"Use a value combination listed in {source_filename}.",
                        )
                    )

        return issues

    def _profile_issue(
        self,
        object_name: str,
        sheet_name: str,
        field_name: str,
        message: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            object_name=object_name,
            sheet_name=sheet_name,
            row_number=0,
            field_name=field_name,
            severity="ERROR",
            rule_type="PROFILE",
            message=message,
            suggested_fix="Fix the YAML profile or config source mapping.",
        )

    def _message(
        self,
        field_name: str,
        field_value: Any,
        template_fields: list[str],
        key: tuple[str, ...],
        source_name: str,
    ) -> str:
        clean_value = normalize_scalar(field_value)
        if len(template_fields) == 1:
            return f"{field_name} '{clean_value}' does not exist in config source '{source_name}'."
        parts = ", ".join(f"{field}='{value}'" for field, value in zip(template_fields, key, strict=True))
        return f"{field_name} '{clean_value}' is invalid for combination {parts}."

