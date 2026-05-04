from __future__ import annotations

import re
import shutil
from pathlib import Path

import pandas as pd

from automation.batch_processor import process_file
from automation.folder_scanner import (
    discover_object_folders,
    ensure_object_batch_folders,
    get_object_folder_status,
    move_with_timestamp,
    scan_once,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_folder_scanner_discovers_object_folders(tmp_path: Path) -> None:
    base_dir = tmp_path / "object_batches"
    ensure_object_batch_folders(base_dir, ["MATERIAL_MASTER", "BP_CUSTOMER"])

    folders = discover_object_folders(base_dir)

    assert [folder.name for folder in folders] == ["BP_CUSTOMER", "MATERIAL_MASTER"]
    assert (base_dir / "MATERIAL_MASTER" / "incoming").exists()
    assert (base_dir / "MATERIAL_MASTER" / "processing").exists()
    assert (base_dir / "MATERIAL_MASTER" / "processed").exists()
    assert (base_dir / "MATERIAL_MASTER" / "failed").exists()


def test_folder_scanner_uses_folder_name_as_object(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    incoming = tmp_path / "input" / "object_batches" / "MATERIAL_MASTER" / "incoming"
    incoming.mkdir(parents=True)
    _copy_sample(incoming, "material_master_legacy_values_sample.xlsx", "material_load_001.xlsx")

    results = scan_once(settings)

    assert len(results) == 1
    assert results[0].status == "SUCCESS"
    assert results[0].object_name == "MATERIAL_MASTER"
    assert len(list((incoming.parent / "processed").glob("material_load_001__*.xlsx"))) == 1
    assert not (incoming / "material_load_001.xlsx").exists()


def test_folder_scanner_fallback_to_template_detector(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    incoming = tmp_path / "input" / "object_batches" / "UNKNOWN_OBJECT" / "incoming"
    incoming.mkdir(parents=True)
    _copy_sample(incoming, "material_master_legacy_values_sample.xlsx", "fallback_load.xlsx")

    results = scan_once(settings)

    assert len(results) == 1
    assert results[0].status == "SUCCESS"
    assert results[0].object_name == "MATERIAL_MASTER"
    assert len(list((incoming.parent / "processed").glob("fallback_load__*.xlsx"))) == 1


def test_folder_scanner_moves_success_to_processed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    incoming = tmp_path / "input" / "object_batches" / "MATERIAL_MASTER" / "incoming"
    incoming.mkdir(parents=True)
    _copy_sample(incoming, "material_master_legacy_values_sample.xlsx", "success_load.xlsx")

    result = scan_once(settings)[0]

    assert result.status == "SUCCESS"
    assert len(list((incoming.parent / "processed").glob("success_load__*.xlsx"))) == 1
    assert len(list((incoming.parent / "processing").glob("*.xlsx"))) == 0


def test_folder_scanner_moves_failed_to_failed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    incoming = tmp_path / "input" / "object_batches" / "UNKNOWN_OBJECT" / "incoming"
    incoming.mkdir(parents=True)
    unknown_file = incoming / "unknown_load.xlsx"
    with pd.ExcelWriter(unknown_file, engine="openpyxl") as writer:
        pd.DataFrame([{"Unknown": "value"}]).to_excel(writer, sheet_name="Unknown", index=False)

    result = scan_once(settings)[0]

    assert result.status == "FAILED"
    assert result.message == "Could not detect migration object"
    assert len(list((incoming.parent / "failed").glob("unknown_load__*.xlsx"))) == 1
    assert len(list((incoming.parent / "processing").glob("*.xlsx"))) == 0


def test_folder_scanner_process_once_returns_results(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    incoming = tmp_path / "input" / "object_batches" / "MATERIAL_MASTER" / "incoming"
    incoming.mkdir(parents=True)
    _copy_sample(incoming, "material_master_legacy_values_sample.xlsx", "result_load.xlsx")

    results = scan_once(settings)

    assert len(results) == 1
    assert results[0].file_name == "result_load.xlsx"
    assert re.search(r"__MATERIAL_MASTER__\d{8}_\d{6}__SUCCESS__", results[0].report_path or "")


def test_process_file_with_object_name_override(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx", "override_load.xlsx")

    result = process_file(file_path, settings, object_name_override="MATERIAL_MASTER")

    assert result.status == "SUCCESS"
    assert result.object_name == "MATERIAL_MASTER"
    assert Path(result.report_path or "").exists()


def test_get_object_folder_status_counts_files(tmp_path: Path) -> None:
    base_dir = tmp_path / "object_batches"
    ensure_object_batch_folders(base_dir, ["MATERIAL_MASTER"])
    (base_dir / "MATERIAL_MASTER" / "incoming" / "one.xlsx").write_bytes(b"1")
    (base_dir / "MATERIAL_MASTER" / "processed" / "two.xlsx").write_bytes(b"2")

    status = get_object_folder_status(base_dir)

    assert status.to_dict("records") == [
        {
            "object_name": "MATERIAL_MASTER",
            "incoming": 1,
            "processing": 0,
            "processed": 1,
            "failed": 0,
        }
    ]


def test_move_with_timestamp_avoids_processed_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "processing" / "load.xlsx"
    dst_dir = tmp_path / "processed"
    src.parent.mkdir()
    src.write_bytes(b"data")

    dst = move_with_timestamp(src, dst_dir)

    assert not src.exists()
    assert dst.exists()
    assert re.fullmatch(r"load__\d{8}_\d{6}\.xlsx", dst.name)


def _copy_sample(destination_dir: Path, source_name: str, destination_name: str) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    source = PROJECT_ROOT / "sample_templates" / source_name
    destination = destination_dir / destination_name
    shutil.copyfile(source, destination)
    return destination


def _settings(tmp_path: Path) -> dict:
    return {
        "watcher": {
            "enabled": True,
            "poll_interval_seconds": 1,
            "stable_wait_seconds": 0,
            "input_dir": str(tmp_path / "input" / "incoming"),
            "processing_dir": str(tmp_path / "input" / "processing"),
            "processed_dir": str(tmp_path / "input" / "processed"),
            "failed_dir": str(tmp_path / "input" / "failed"),
        },
        "folder_scanner": {
            "enabled": True,
            "mode": "object_folder",
            "poll_interval_seconds": 1,
            "stable_wait_seconds": 0,
            "base_dir": str(tmp_path / "input" / "object_batches"),
            "supported_extensions": [".xlsx", ".xlsm", ".csv"],
            "use_folder_name_as_object": True,
            "fallback_to_template_detection": True,
            "process_once_default": False,
        },
        "processing": {
            "apply_mapping": True,
            "generate_cleaned_template": True,
            "use_local_llm": False,
            "local_model_name": "llama3.1:8b",
            "stop_on_errors": False,
        },
        "paths": {
            "profiles_dir": str(PROJECT_ROOT / "profiles"),
            "config_dir": str(PROJECT_ROOT / "config_samples"),
            "mappings_dir": str(PROJECT_ROOT / "mappings"),
            "output_reports_dir": str(tmp_path / "output" / "reports"),
            "output_cleaned_dir": str(tmp_path / "output" / "cleaned_templates"),
            "output_mapping_audits_dir": str(tmp_path / "output" / "mapping_audits"),
            "output_logs_dir": str(tmp_path / "output" / "logs"),
        },
        "notification": {
            "enabled": False,
            "prefer_template_emails": True,
            "fallback_to_default_recipients": True,
            "max_template_recipients": 5,
            "channels": {
                "email": {
                    "enabled": False,
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 587,
                    "smtp_user": "",
                    "smtp_password_env": "SMTP_PASSWORD",
                    "sender": "sap-agent@example.com",
                    "recipients": ["consultant@example.com"],
                },
                "teams": {
                    "enabled": False,
                    "webhook_url_env": "TEAMS_WEBHOOK_URL",
                },
            },
        },
    }
