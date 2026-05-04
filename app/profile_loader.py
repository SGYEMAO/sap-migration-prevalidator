from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProfileLoaderError(ValueError):
    pass


def load_profile(object_name: str, profiles_dir: str | Path) -> dict[str, Any]:
    profiles_path = Path(profiles_dir)
    profile_path = profiles_path / f"{object_name}.yml"
    if not profile_path.exists():
        raise ProfileLoaderError(f"Profile '{object_name}' was not found in {profiles_path}.")
    with profile_path.open("r", encoding="utf-8") as handle:
        profile = yaml.safe_load(handle) or {}
    if profile.get("object") != object_name:
        raise ProfileLoaderError(
            f"Profile file {profile_path.name} declares object '{profile.get('object')}'."
        )
    return profile


def load_profiles(profiles_dir: str | Path) -> dict[str, dict[str, Any]]:
    profiles_path = Path(profiles_dir)
    profiles: dict[str, dict[str, Any]] = {}
    for profile_path in sorted(profiles_path.glob("*.yml")):
        with profile_path.open("r", encoding="utf-8") as handle:
            profile = yaml.safe_load(handle) or {}
        object_name = profile.get("object") or profile_path.stem
        profiles[object_name] = profile
    return profiles


def list_profile_names(profiles_dir: str | Path) -> list[str]:
    return sorted(load_profiles(profiles_dir).keys())


def required_config_filenames(profile: dict[str, Any]) -> dict[str, str]:
    sources = profile.get("config_sources", {}) or {}
    return {
        source_name: str(source_spec.get("filename", ""))
        for source_name, source_spec in sources.items()
        if source_spec.get("filename")
    }


def required_mapping_filenames(profile: dict[str, Any]) -> dict[str, str]:
    mappings = profile.get("mappings", {}) or {}
    return {
        mapping_name: str(mapping_spec.get("filename", ""))
        for mapping_name, mapping_spec in mappings.items()
        if mapping_spec.get("filename")
    }
