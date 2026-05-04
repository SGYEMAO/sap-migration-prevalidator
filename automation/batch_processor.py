from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.audit_logger import generate_mapping_audit_report
from app.autofix_engine import generate_cleaned_template
from app.config_loader import ConfigLoaderError, load_config_files_from_dir
from app.data_parser import load_template_excel, load_template_excel_with_profile
from app.email_extractor import extract_emails_from_template
from app.local_llm import DEFAULT_LOCAL_MODEL, explain_issue_with_local_llm
from app.mapping_engine import apply_mappings, load_mapping_files_from_dir
from app.models import BatchProcessResult, MappingAction
from app.profile_loader import ProfileLoaderError, load_profile
from app.report_generator import generate_excel_report
from app.rule_engine import run_validation
from app.template_detector import detect_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def process_file(file_path: Path, settings: dict) -> BatchProcessResult:
    file_path = Path(file_path)
    template_emails: list[str] = []
    notification_recipients: list[str] = []
    object_name: str | None = None

    try:
        template_data_for_detection = load_template_excel(file_path)
        template_emails = extract_emails_from_template(template_data_for_detection)
        notification_recipients = resolve_notification_recipients(template_emails, settings)

        profiles_dir = _settings_path(settings, "paths", "profiles_dir", default="profiles")
        object_name = detect_template(template_data_for_detection, profiles_dir)
        if object_name is None:
            logger.error("object detected failed for %s", file_path.name)
            return _failed_result(
                file_path=file_path,
                object_name=None,
                message="Could not detect migration object",
                template_emails=template_emails,
                notification_recipients=notification_recipients,
            )

        logger.info("object detected: %s for %s", object_name, file_path.name)
        profile = load_profile(object_name, profiles_dir)
        template_data = load_template_excel_with_profile(file_path, profile)

        config_dir = _settings_path(settings, "paths", "config_dir", default="config_samples")
        config_data = load_config_files_from_dir(profile, config_dir)
        logger.info("config loaded for %s", file_path.name)

        processing_settings = settings.get("processing", {}) or {}
        mapped_template_data = template_data
        mapping_actions: list[MappingAction] = []
        if bool(processing_settings.get("apply_mapping", True)):
            mappings_dir = _settings_path(settings, "paths", "mappings_dir", default="mappings")
            mappings = load_mapping_files_from_dir(profile, mappings_dir / object_name)
            mapped_template_data, mapping_actions = apply_mappings(
                object_name,
                profile,
                template_data,
                mappings,
            )
            logger.info("mapping applied for %s with %s action(s)", file_path.name, len(mapping_actions))
        else:
            logger.info("mapping skipped for %s", file_path.name)

        validation_result = run_validation(object_name, profile, mapped_template_data, config_data)
        logger.info(
            "validation completed for %s with %s error(s), %s warning(s)",
            file_path.name,
            validation_result.error_count,
            validation_result.warning_count,
        )

        llm_explanations = None
        if bool(processing_settings.get("use_local_llm", False)) and validation_result.issues:
            model_name = str(processing_settings.get("local_model_name") or DEFAULT_LOCAL_MODEL)
            llm_explanations = [
                explain_issue_with_local_llm(issue, context={}, model_name=model_name)
                for issue in validation_result.issues
            ]

        stop_on_errors = bool(processing_settings.get("stop_on_errors", False))
        status = "VALIDATION_FAILED" if validation_result.error_count > 0 and stop_on_errors else "SUCCESS"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = _output_base(file_path.stem, object_name, timestamp, status)

        report_path = _unique_path(
            _settings_path(settings, "paths", "output_reports_dir", default="output/reports")
            / f"{output_base}__validation_report.xlsx"
        )
        generate_excel_report(validation_result, report_path, llm_explanations=llm_explanations)
        logger.info("report generated: %s", report_path)

        mapping_audit_path = None
        if bool(processing_settings.get("apply_mapping", True)):
            mapping_audit_path = _unique_path(
                _settings_path(
                    settings,
                    "paths",
                    "output_mapping_audits_dir",
                    default="output/mapping_audits",
                )
                / f"{output_base}__mapping_audit.xlsx"
            )
            generate_mapping_audit_report(mapping_actions, mapping_audit_path)
            logger.info("mapping audit generated: %s", mapping_audit_path)

        cleaned_template_path = None
        if bool(processing_settings.get("generate_cleaned_template", True)):
            cleaned_template_path = _unique_path(
                _settings_path(
                    settings,
                    "paths",
                    "output_cleaned_dir",
                    default="output/cleaned_templates",
                )
                / f"{output_base}__cleaned_template.xlsx"
            )
            generate_cleaned_template(
                str(file_path),
                mapped_template_data,
                mapping_actions,
                validation_result,
                str(cleaned_template_path),
            )
            logger.info("cleaned template generated: %s", cleaned_template_path)

        return BatchProcessResult(
            file_name=file_path.name,
            object_name=object_name,
            status=status,
            total_rows=validation_result.total_rows,
            error_count=validation_result.error_count,
            warning_count=validation_result.warning_count,
            report_path=str(report_path),
            cleaned_template_path=str(cleaned_template_path) if cleaned_template_path else None,
            mapping_audit_path=str(mapping_audit_path) if mapping_audit_path else None,
            message="Processing completed.",
            notification_recipients=notification_recipients,
            template_emails_found=template_emails,
        )
    except (ConfigLoaderError, ProfileLoaderError, ValueError) as exc:
        logger.exception("processing failed for %s: %s", file_path.name, exc)
        return _failed_result(
            file_path=file_path,
            object_name=object_name,
            message=str(exc),
            template_emails=template_emails,
            notification_recipients=notification_recipients,
        )
    except Exception as exc:  # noqa: BLE001 - batch mode must keep the watcher alive.
        logger.exception("processing failed for %s: %s", file_path.name, exc)
        return _failed_result(
            file_path=file_path,
            object_name=object_name,
            message=f"Unexpected processing error: {exc}",
            template_emails=template_emails,
            notification_recipients=notification_recipients,
        )


def resolve_notification_recipients(template_emails: list[str], settings: dict) -> list[str]:
    notification_settings = settings.get("notification", {}) or {}
    max_template_recipients = int(notification_settings.get("max_template_recipients", 5) or 5)
    if bool(notification_settings.get("prefer_template_emails", True)) and template_emails:
        return template_emails[:max_template_recipients]

    if not bool(notification_settings.get("fallback_to_default_recipients", True)):
        return []

    email_settings = ((notification_settings.get("channels", {}) or {}).get("email", {}) or {})
    recipients = email_settings.get("recipients", []) or []
    if isinstance(recipients, str):
        return [recipients]
    return [str(recipient) for recipient in recipients if str(recipient).strip()]


def _failed_result(
    file_path: Path,
    object_name: str | None,
    message: str,
    template_emails: list[str],
    notification_recipients: list[str],
) -> BatchProcessResult:
    return BatchProcessResult(
        file_name=file_path.name,
        object_name=object_name,
        status="FAILED",
        message=message,
        notification_recipients=notification_recipients,
        template_emails_found=template_emails,
    )


def _settings_path(settings: dict, section: str, key: str, default: str) -> Path:
    value = ((settings.get(section, {}) or {}).get(key)) or default
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _output_base(file_stem: str, object_name: str, timestamp: str, status: str) -> str:
    clean_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", file_stem).strip("_") or "template"
    return f"{clean_stem}__{object_name}__{timestamp}__{status}"


def _unique_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}__{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"Could not allocate a unique output path for {path}.")
