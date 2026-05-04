from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


IssueValue = str | int | float | None


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_name: str
    sheet_name: str
    row_number: int
    field_name: str | None = None
    value: IssueValue = None
    severity: Literal["ERROR", "WARNING"]
    rule_type: str
    message: str
    suggested_fix: str | None = None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_name: str
    total_rows: int
    error_count: int
    warning_count: int
    issues: list[ValidationIssue]

    @property
    def status(self) -> Literal["FAILED", "PASSED"]:
        return "FAILED" if self.error_count > 0 else "PASSED"

    @classmethod
    def from_issues(
        cls,
        object_name: str,
        total_rows: int,
        issues: list[ValidationIssue],
    ) -> "ValidationResult":
        return cls(
            object_name=object_name,
            total_rows=total_rows,
            error_count=sum(1 for issue in issues if issue.severity == "ERROR"),
            warning_count=sum(1 for issue in issues if issue.severity == "WARNING"),
            issues=issues,
        )


MappingValue = str | int | float | None


class MappingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_name: str
    sheet_name: str
    row_number: int
    field_name: str
    original_value: MappingValue
    mapped_value: MappingValue
    mapping_name: str
    confidence: float = 1.0
    status: Literal["MAPPED", "UNMAPPED", "AMBIGUOUS", "UNCHANGED"]
    message: str | None = None


class BatchProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str
    object_name: str | None
    status: Literal["SUCCESS", "FAILED", "VALIDATION_FAILED"]
    total_rows: int = 0
    error_count: int = 0
    warning_count: int = 0
    report_path: str | None = None
    cleaned_template_path: str | None = None
    mapping_audit_path: str | None = None
    message: str | None = None
    notification_recipients: list[str] = Field(default_factory=list)
    template_emails_found: list[str] = Field(default_factory=list)
