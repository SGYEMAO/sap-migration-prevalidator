from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from time import sleep
from typing import Iterable

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.batch_processor import process_file  # noqa: E402
from automation.notification import send_notification  # noqa: E402
from app.models import BatchProcessResult  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}
logger = logging.getLogger(__name__)


def is_file_stable(path: Path, wait_seconds: int = 2) -> bool:
    size1 = path.stat().st_size
    sleep(wait_seconds)
    size2 = path.stat().st_size
    return size1 == size2


def load_settings(settings_path: str | Path) -> dict:
    path = Path(settings_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def configure_logging(settings: dict | None = None) -> Path:
    log_path = PROJECT_ROOT / "logs" / "automation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")) == log_path
        for handler in root_logger.handlers
    ):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if not any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    return log_path


def scan_once(settings: dict) -> list[BatchProcessResult]:
    _ensure_directories(settings)
    incoming_dir = _settings_path(settings, "watcher", "input_dir", default="input/incoming")
    results: list[BatchProcessResult] = []

    for path in _incoming_files(incoming_dir):
        logger.info("file detected: %s", path)
        wait_seconds = int((settings.get("watcher", {}) or {}).get("stable_wait_seconds", 2) or 2)
        if not is_file_stable(path, wait_seconds=wait_seconds):
            logger.info("file skipped because it is not stable yet: %s", path)
            continue
        results.append(_process_incoming_file(path, settings))
    return results


def run_watcher(settings: dict, once: bool = False) -> None:
    watcher_settings = settings.get("watcher", {}) or {}
    if not bool(watcher_settings.get("enabled", True)):
        logger.info("watcher disabled in settings")
        return

    poll_interval = int(watcher_settings.get("poll_interval_seconds", 10) or 10)
    while True:
        scan_once(settings)
        if once:
            return
        sleep(poll_interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SAP migration semi-automated batch watcher")
    parser.add_argument("--settings", default="automation/settings.yml", help="Path to settings.yml")
    parser.add_argument("--once", action="store_true", help="Scan incoming folder once and exit")
    args = parser.parse_args(argv)

    settings = load_settings(args.settings)
    configure_logging(settings)
    run_watcher(settings, once=args.once)


def _process_incoming_file(path: Path, settings: dict) -> BatchProcessResult:
    processing_dir = _settings_path(settings, "watcher", "processing_dir", default="input/processing")
    processed_dir = _settings_path(settings, "watcher", "processed_dir", default="input/processed")
    failed_dir = _settings_path(settings, "watcher", "failed_dir", default="input/failed")

    processing_path = _unique_path(processing_dir / path.name)
    shutil.move(str(path), str(processing_path))
    logger.info("moved to processing: %s", processing_path)

    try:
        result = process_file(processing_path, settings)
    except Exception as exc:  # noqa: BLE001 - watcher must keep running.
        logger.exception("processing crashed for %s: %s", processing_path.name, exc)
        result = BatchProcessResult(
            file_name=processing_path.name,
            object_name=None,
            status="FAILED",
            message=f"Unexpected watcher processing error: {exc}",
        )

    send_notification(result, settings)

    target_dir = processed_dir if result.status == "SUCCESS" else failed_dir
    target_path = _unique_path(target_dir / processing_path.name)
    shutil.move(str(processing_path), str(target_path))
    if result.status == "SUCCESS":
        logger.info("file moved to processed: %s", target_path)
    else:
        logger.info("file moved to failed: %s", target_path)
    return result


def _incoming_files(incoming_dir: Path) -> Iterable[Path]:
    if not incoming_dir.exists():
        return []
    return sorted(
        path
        for path in incoming_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _ensure_directories(settings: dict) -> None:
    path_specs = [
        ("watcher", "input_dir", "input/incoming"),
        ("watcher", "processing_dir", "input/processing"),
        ("watcher", "processed_dir", "input/processed"),
        ("watcher", "failed_dir", "input/failed"),
        ("paths", "output_reports_dir", "output/reports"),
        ("paths", "output_cleaned_dir", "output/cleaned_templates"),
        ("paths", "output_mapping_audits_dir", "output/mapping_audits"),
        ("paths", "output_logs_dir", "output/logs"),
    ]
    for section, key, default in path_specs:
        _settings_path(settings, section, key, default=default).mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)


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
