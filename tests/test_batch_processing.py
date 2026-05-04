from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import pandas as pd

from automation.batch_processor import process_file, resolve_notification_recipients
from automation.notification import send_notification
from automation.watcher import is_file_stable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_is_file_stable(tmp_path: Path) -> None:
    file_path = tmp_path / "stable.xlsx"
    file_path.write_bytes(b"stable")

    assert is_file_stable(file_path, wait_seconds=0)


def test_process_file_success_material_master(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx")

    result = process_file(file_path, settings)

    assert result.status == "SUCCESS"
    assert result.object_name == "MATERIAL_MASTER"
    assert result.error_count > 0
    assert Path(result.report_path or "").exists()
    assert Path(result.cleaned_template_path or "").exists()
    assert Path(result.mapping_audit_path or "").exists()
    assert result.template_emails_found == ["migration.owner@example.com"]
    assert result.notification_recipients == ["migration.owner@example.com"]


def test_process_file_failed_unknown_template(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    file_path = tmp_path / "unknown_template.xlsx"
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        pd.DataFrame([{"Unknown": "value"}]).to_excel(writer, sheet_name="Unknown", index=False)

    result = process_file(file_path, settings)

    assert result.status == "FAILED"
    assert result.object_name is None
    assert result.message == "Could not detect migration object"


def test_missing_config_file_fails(tmp_path: Path) -> None:
    empty_config_dir = tmp_path / "empty_config"
    empty_config_dir.mkdir()
    settings = _settings(tmp_path, config_dir=empty_config_dir)
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx")

    result = process_file(file_path, settings)

    assert result.status == "FAILED"
    assert "Missing config file" in (result.message or "")


def test_missing_mapping_file_does_not_fail(tmp_path: Path, caplog) -> None:
    empty_mappings_dir = tmp_path / "empty_mappings"
    (empty_mappings_dir / "MATERIAL_MASTER").mkdir(parents=True)
    settings = _settings(tmp_path, mappings_dir=empty_mappings_dir)
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx")

    with caplog.at_level(logging.WARNING):
        result = process_file(file_path, settings)

    assert result.status == "SUCCESS"
    assert Path(result.report_path or "").exists()
    assert Path(result.mapping_audit_path or "").exists()
    assert "Missing mapping file" in caplog.text


def test_output_file_naming_contains_timestamp(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx")

    result = process_file(file_path, settings)

    report_name = Path(result.report_path or "").name
    assert re.fullmatch(
        r"material_master_legacy_values_sample__MATERIAL_MASTER__\d{8}_\d{6}__SUCCESS__validation_report\.xlsx",
        report_name,
    )


def test_notification_failure_does_not_fail_processing(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings["notification"]["enabled"] = True
    settings["notification"]["channels"]["email"]["enabled"] = True
    file_path = _copy_sample(tmp_path, "material_master_legacy_values_sample.xlsx")
    result = process_file(file_path, settings)

    def fail_email(*args, **kwargs):
        raise OSError("SMTP unavailable")

    monkeypatch.setattr("automation.notification.send_email_notification", fail_email)

    send_notification(result, settings)
    assert result.status == "SUCCESS"


def test_template_email_preferred_over_default() -> None:
    settings = _settings(Path("unused"))

    recipients = resolve_notification_recipients(["owner@example.com"], settings)

    assert recipients == ["owner@example.com"]


def test_fallback_to_default_recipients() -> None:
    settings = _settings(Path("unused"))

    recipients = resolve_notification_recipients([], settings)

    assert recipients == ["consultant@example.com"]


def test_no_email_does_not_fail_processing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings["notification"]["channels"]["email"]["recipients"] = []
    file_path = _copy_sample(tmp_path, "material_master_sample.xlsx")

    result = process_file(file_path, settings)

    assert result.status == "SUCCESS"
    assert result.template_emails_found == []
    assert result.notification_recipients == []


def test_max_template_recipients_applied() -> None:
    settings = _settings(Path("unused"))
    settings["notification"]["max_template_recipients"] = 2

    recipients = resolve_notification_recipients(
        ["one@example.com", "two@example.com", "three@example.com"],
        settings,
    )

    assert recipients == ["one@example.com", "two@example.com"]


def _copy_sample(tmp_path: Path, name: str) -> Path:
    source = PROJECT_ROOT / "sample_templates" / name
    destination = tmp_path / name
    shutil.copyfile(source, destination)
    return destination


def _settings(
    tmp_path: Path,
    config_dir: Path | None = None,
    mappings_dir: Path | None = None,
) -> dict:
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
        "processing": {
            "apply_mapping": True,
            "generate_cleaned_template": True,
            "use_local_llm": False,
            "local_model_name": "llama3.1:8b",
            "stop_on_errors": False,
        },
        "paths": {
            "profiles_dir": str(PROJECT_ROOT / "profiles"),
            "config_dir": str(config_dir or PROJECT_ROOT / "config_samples"),
            "mappings_dir": str(mappings_dir or PROJECT_ROOT / "mappings"),
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
