from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.request
from email.message import EmailMessage

from app.models import BatchProcessResult


logger = logging.getLogger(__name__)


def send_notification(result: BatchProcessResult, settings: dict) -> None:
    notification_settings = settings.get("notification", {}) or {}
    if not bool(notification_settings.get("enabled", False)):
        logger.info("notification skipped for %s: notification disabled", result.file_name)
        return

    channels = notification_settings.get("channels", {}) or {}
    attempted = False

    email_settings = channels.get("email", {}) or {}
    if bool(email_settings.get("enabled", False)):
        attempted = True
        try:
            if send_email_notification(result, email_settings):
                logger.info("notification sent via email for %s", result.file_name)
            else:
                logger.info("notification skipped via email for %s", result.file_name)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail validation.
            logger.warning("notification failed via email for %s: %s", result.file_name, exc)

    teams_settings = channels.get("teams", {}) or {}
    if bool(teams_settings.get("enabled", False)):
        attempted = True
        try:
            if send_teams_notification(result, teams_settings):
                logger.info("notification sent via teams for %s", result.file_name)
            else:
                logger.info("notification skipped via teams for %s", result.file_name)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail validation.
            logger.warning("notification failed via teams for %s: %s", result.file_name, exc)

    if not attempted:
        logger.info("notification skipped for %s: no enabled channel", result.file_name)


def send_email_notification(result: BatchProcessResult, settings: dict) -> bool:
    recipients = result.notification_recipients or settings.get("recipients", []) or []
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [str(recipient).strip() for recipient in recipients if str(recipient).strip()]
    if not recipients:
        logger.info("notification skipped via email for %s: no recipients", result.file_name)
        return False

    smtp_host = str(settings.get("smtp_host") or "").strip()
    if not smtp_host:
        logger.warning("notification failed via email for %s: smtp_host is missing", result.file_name)
        return False

    smtp_port = int(settings.get("smtp_port", 587) or 587)
    smtp_user = str(settings.get("smtp_user") or "").strip()
    password_env = str(settings.get("smtp_password_env") or "").strip()
    smtp_password = os.getenv(password_env) if password_env else None
    if smtp_user and not smtp_password:
        logger.warning(
            "notification failed via email for %s: SMTP password env var is not set",
            result.file_name,
        )
        return False

    sender = str(settings.get("sender") or smtp_user or "").strip()
    if not sender:
        logger.warning("notification failed via email for %s: sender is missing", result.file_name)
        return False

    message = EmailMessage()
    message["Subject"] = f"SAP migration validation {result.status}: {result.file_name}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(_summary_text(result))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if smtp_port == 587:
            server.starttls()
        if smtp_user:
            server.login(smtp_user, smtp_password)
        server.send_message(message)
    return True


def send_teams_notification(result: BatchProcessResult, settings: dict) -> bool:
    webhook_env = str(settings.get("webhook_url_env") or "").strip()
    webhook_url = os.getenv(webhook_env) if webhook_env else None
    if not webhook_url:
        logger.info("notification skipped via teams for %s: webhook env var is not set", result.file_name)
        return False

    payload = {"text": _summary_text(result)}
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()
    return True


def _summary_text(result: BatchProcessResult) -> str:
    return "\n".join(
        [
            "SAP migration validation completed.",
            f"File name: {result.file_name}",
            f"Migration object: {result.object_name or 'Unknown'}",
            f"Status: {result.status}",
            f"Error count: {result.error_count}",
            f"Warning count: {result.warning_count}",
            f"Report path: {result.report_path or ''}",
            f"Cleaned template path: {result.cleaned_template_path or ''}",
            f"Mapping audit path: {result.mapping_audit_path or ''}",
        ]
    )
