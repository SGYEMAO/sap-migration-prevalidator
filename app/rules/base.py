from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from app.models import ValidationIssue


@dataclass(frozen=True)
class RuleContext:
    object_name: str
    profile: dict[str, Any]
    template_data: dict[str, pd.DataFrame]
    config_data: dict[str, pd.DataFrame]


class ValidationRule(Protocol):
    rule_type: str

    def validate(self, context: RuleContext) -> list[ValidationIssue]:
        ...

