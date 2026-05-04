from __future__ import annotations

import pandas as pd

from app.email_extractor import extract_emails_from_template


def test_extract_email_from_named_column() -> None:
    template_data = {
        "Contact": pd.DataFrame(
            [{"OwnerEmail": "migration.owner@example.com", "Name": "Data Owner"}]
        )
    }

    assert extract_emails_from_template(template_data) == ["migration.owner@example.com"]


def test_extract_email_from_any_cell() -> None:
    template_data = {
        "Notes": pd.DataFrame(
            [{"Comment": "Please notify support.owner@example.com after validation."}]
        )
    }

    assert extract_emails_from_template(template_data) == ["support.owner@example.com"]


def test_email_deduplication() -> None:
    template_data = {
        "Contact": pd.DataFrame(
            [
                {
                    "OwnerEmail": "migration.owner@example.com",
                    "Comment": "Backup MIGRATION.OWNER@example.com",
                }
            ]
        )
    }

    assert extract_emails_from_template(template_data) == ["migration.owner@example.com"]
