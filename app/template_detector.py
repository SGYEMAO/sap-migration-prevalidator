from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.profile_loader import load_profiles


def detect_template(template_data: dict[str, pd.DataFrame], profiles_dir: str | Path) -> str | None:
    profiles = load_profiles(profiles_dir)
    available_sheets = set(template_data.keys())
    all_columns = {
        str(column)
        for df in template_data.values()
        for column in df.columns
        if not str(column).startswith("__")
    }

    best_object: str | None = None
    best_score = 0
    for object_name, profile in profiles.items():
        detection = profile.get("template_detection", {}) or {}
        expected_sheets = set(detection.get("expected_sheets", []) or [])
        keywords = set(detection.get("keywords", []) or [])

        sheet_score = len(expected_sheets & available_sheets) * 3
        keyword_score = len(keywords & all_columns)
        score = sheet_score + keyword_score
        if expected_sheets and not expected_sheets <= available_sheets:
            score -= 2

        if score > best_score:
            best_score = score
            best_object = object_name

    return best_object if best_score > 0 else None

