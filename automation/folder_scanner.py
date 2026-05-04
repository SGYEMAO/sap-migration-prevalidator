from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from time import sleep

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.batch_processor import process_file  # noqa: E402
from automation.notification import send_notification  # noqa: E402
from automation.watcher import configure_logging, is_file_stable, load_settings  # noqa: E402
from app.models import BatchProcessResult  # noqa: E402
from app.profile_loader import list_profile_names  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OBJECT_BATCH_SUBDIRS = ("incoming", "processing", "processed", "failed")
logger = logging.getLogger(__name__)


def scan_once(settings: dict) -> list[BatchProcessResult]:
    scanner_settings = settings.get("folder_scanner", {}) or {}
    base_dir = _settings_path(settings, "folder_scanner", "base_dir", default="input/object_batches")
    profiles_dir = _settings_path(settings, "paths", "profiles_dir", default="profiles")
    known_objects = list_profile_names(profiles_dir)
    ensure_object_batch_folders(base_dir, known_objects)

    results: list[BatchProcessResult] = []
    supported_extensions = _supported_extensions(scanner_settings)
    wait_seconds = _stable_wait_seconds(scanner_settings)

    for object_folder in discover_object_folders(base_dir):
        _ensure_single_object_folder(object_folder)
        incoming_dir = object_folder / "incoming"
        for path in _incoming_files(incoming_dir, supported_extensions):
            logger.info("folder scanner file detected: %s", path)
            if not is_file_stable(path, wait_seconds=wait_seconds):
                logger.info("folder scanner skipped unstable file: %s", path)
                continue
            results.append(_process_object_file(path, object_folder, known_objects, settings))
    return results


def scan_forever(settings: dict) -> None:
    scanner_settings = settings.get("folder_scanner", {}) or {}
    if not bool(scanner_settings.get("enabled", True)):
        logger.info("folder scanner disabled in settings")
        return

    poll_interval = int(scanner_settings.get("poll_interval_seconds", 10) or 10)
    while True:
        scan_once(settings)
        sleep(poll_interval)


def ensure_object_batch_folders(base_dir: Path, object_names: list[str]) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    for object_name in object_names:
        object_folder = base_dir / object_name
        _ensure_single_object_folder(object_folder)


def discover_object_folders(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(path for path in base_dir.iterdir() if path.is_dir())


def get_object_folder_status(base_dir: Path) -> pd.DataFrame:
    rows = []
    for object_folder in discover_object_folders(base_dir):
        rows.append(
            {
                "object_name": object_folder.name,
                "incoming": _count_files(object_folder / "incoming"),
                "processing": _count_files(object_folder / "processing"),
                "processed": _count_files(object_folder / "processed"),
                "failed": _count_files(object_folder / "failed"),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["object_name", "incoming", "processing", "processed", "failed"],
    )


def move_with_timestamp(src: Path, dst_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.stem}__{timestamp}{src.suffix}"
    if dst.exists():
        dst = _unique_path(dst)
    src.rename(dst)
    return dst


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SAP migration object-folder scanner")
    parser.add_argument("--settings", default="automation/settings.yml", help="Path to settings.yml")
    parser.add_argument("--once", action="store_true", help="Scan object folders once and exit")
    args = parser.parse_args(argv)

    settings = load_settings(args.settings)
    configure_logging(settings)
    scanner_settings = settings.get("folder_scanner", {}) or {}
    once = args.once or bool(scanner_settings.get("process_once_default", False))
    if once:
        scan_once(settings)
    else:
        scan_forever(settings)


def _process_object_file(
    path: Path,
    object_folder: Path,
    known_objects: list[str],
    settings: dict,
) -> BatchProcessResult:
    object_name_override = _object_name_override(object_folder.name, known_objects, settings)
    processing_path = _unique_path(object_folder / "processing" / path.name)
    shutil.move(str(path), str(processing_path))
    logger.info("folder scanner moved to processing: %s", processing_path)

    try:
        result = process_file(
            processing_path,
            settings,
            object_name_override=object_name_override,
        )
    except Exception as exc:  # noqa: BLE001 - scanner must keep running.
        logger.exception("folder scanner processing crashed for %s: %s", processing_path.name, exc)
        result = BatchProcessResult(
            file_name=processing_path.name,
            object_name=object_name_override,
            status="FAILED",
            message=f"Unexpected folder scanner processing error: {exc}",
        )

    send_notification(result, settings)

    target_dir = object_folder / ("processed" if result.status == "SUCCESS" else "failed")
    target_path = move_with_timestamp(processing_path, target_dir)
    if result.status == "SUCCESS":
        logger.info("folder scanner file moved to processed: %s", target_path)
    else:
        logger.info("folder scanner file moved to failed: %s", target_path)
    return result


def _object_name_override(folder_name: str, known_objects: list[str], settings: dict) -> str | None:
    scanner_settings = settings.get("folder_scanner", {}) or {}
    if not bool(scanner_settings.get("use_folder_name_as_object", True)):
        return None
    if folder_name in known_objects:
        return folder_name
    if bool(scanner_settings.get("fallback_to_template_detection", True)):
        logger.warning(
            "folder scanner object folder '%s' is not a known profile; falling back to template detection",
            folder_name,
        )
        return None
    return folder_name


def _incoming_files(incoming_dir: Path, supported_extensions: set[str]) -> list[Path]:
    if not incoming_dir.exists():
        return []
    return sorted(
        path
        for path in incoming_dir.iterdir()
        if path.is_file() and path.suffix.lower() in supported_extensions
    )


def _count_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for path in directory.iterdir() if path.is_file() and not path.name.startswith("."))


def _ensure_single_object_folder(object_folder: Path) -> None:
    for subdir in OBJECT_BATCH_SUBDIRS:
        (object_folder / subdir).mkdir(parents=True, exist_ok=True)


def _supported_extensions(scanner_settings: dict) -> set[str]:
    values = scanner_settings.get("supported_extensions", [".xlsx", ".xlsm", ".csv"]) or []
    return {str(value).lower() for value in values}


def _stable_wait_seconds(scanner_settings: dict) -> int:
    value = scanner_settings.get("stable_wait_seconds", 2)
    if value is None:
        return 2
    return int(value)


def _settings_path(settings: dict, section: str, key: str, default: str) -> Path:
    value = ((settings.get(section, {}) or {}).get(key)) or default
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _unique_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}__{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"Could not allocate a unique path for {path}.")


if __name__ == "__main__":
    main()
