from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.models import ValidationIssue


OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
DEFAULT_LOCAL_MODEL = "llama3.1:8b"
REQUIRED_KEYS = {
    "business_explanation",
    "likely_cause",
    "recommended_action",
    "risk_level",
}


def explain_issue_with_local_llm(
    issue: ValidationIssue,
    context: dict,
    model_name: str,
) -> str:
    """Explain a validation issue with Ollama, falling back deterministically."""
    prompt = _build_prompt(issue, context)
    payload = json.dumps(
        {
            "model": model_name or DEFAULT_LOCAL_MODEL,
            "prompt": prompt,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        explanation = _normalize_llm_json(str(body.get("response", "")))
        if explanation:
            return explanation
    except (OSError, TimeoutError, ValueError, urllib.error.URLError, urllib.error.HTTPError):
        pass

    return deterministic_fallback_explanation(issue, context)


def deterministic_fallback_explanation(issue: ValidationIssue, context: dict | None = None) -> str:
    suggested_fix = issue.suggested_fix or _default_recommended_action(issue)
    payload = {
        "business_explanation": issue.message,
        "likely_cause": _fallback_likely_cause(issue),
        "recommended_action": suggested_fix,
        "risk_level": _fallback_risk_level(issue),
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_prompt(issue: ValidationIssue, context: dict) -> str:
    issue_json = json.dumps(issue.model_dump(), ensure_ascii=False, default=str)
    context_json = json.dumps(context or {}, ensure_ascii=False, default=str)
    return f"""You are a SAP data migration validation assistant.
Explain the validation issue in simple business language.
Do not invent SAP configuration values.
Do not suggest changing values unless provided by mapping/config context.
If unsure, say the value must be checked with SAP configuration or migration consultant.
Return only JSON.

Output JSON schema:
{{
  "business_explanation": "...",
  "likely_cause": "...",
  "recommended_action": "...",
  "risk_level": "LOW|MEDIUM|HIGH"
}}

Validation issue:
{issue_json}

Provided mapping/config context:
{context_json}
"""


def _normalize_llm_json(response_text: str) -> str | None:
    candidate = _strip_code_fence(response_text.strip())
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not REQUIRED_KEYS.issubset(parsed):
        return None
    risk_level = str(parsed.get("risk_level", "")).upper()
    if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
        risk_level = "MEDIUM"
    normalized = {
        "business_explanation": str(parsed.get("business_explanation") or ""),
        "likely_cause": str(parsed.get("likely_cause") or ""),
        "recommended_action": str(parsed.get("recommended_action") or ""),
        "risk_level": risk_level,
    }
    return json.dumps(normalized, ensure_ascii=False)


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _fallback_likely_cause(issue: ValidationIssue) -> str:
    if issue.rule_type == "CONFIG_CHECK":
        return "The value is not present in the loaded SAP configuration or reference file."
    if issue.rule_type == "REQUIRED":
        return "A mandatory migration field is blank or missing."
    if issue.rule_type == "MAX_LENGTH":
        return "The value is longer than the target SAP field allows."
    if issue.rule_type in {"DUPLICATE", "UNIQUE_COMBINATION"}:
        return "The template contains a duplicate business key."
    return "The value or row does not satisfy the configured validation rule."


def _default_recommended_action(issue: ValidationIssue) -> str:
    if issue.rule_type == "CONFIG_CHECK":
        return "Check the value against SAP configuration or confirm the correct mapping with a migration consultant."
    return "Review the source data and the migration profile rule before upload."


def _fallback_risk_level(issue: ValidationIssue) -> str:
    if issue.severity == "ERROR":
        return "HIGH"
    return "MEDIUM"
