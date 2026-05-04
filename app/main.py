from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from automation.folder_scanner import get_object_folder_status, scan_once
from automation.watcher import configure_logging, load_settings
from app.audit_logger import generate_mapping_audit_report_bytes
from app.autofix_engine import generate_cleaned_template
from app.config_loader import ConfigLoaderError, load_config_files
from app.data_parser import load_template_excel, load_template_excel_with_profile
from app.local_llm import DEFAULT_LOCAL_MODEL, explain_issue_with_local_llm
from app.mapping_engine import MappingLoaderError, apply_mappings, load_mapping_files
from app.models import MappingAction, ValidationIssue
from app.profile_loader import (
    list_profile_names,
    load_profile,
    required_config_filenames,
    required_mapping_filenames,
)
from app.report_generator import generate_excel_report_bytes
from app.rule_engine import run_validation
from app.template_detector import detect_template
from app.utils import project_root


ROOT = project_root()
PROFILES_DIR = ROOT / "profiles"
CONFIG_DIR = ROOT / "config_samples"
MAPPINGS_DIR = ROOT / "mappings"
CLEANED_TEMPLATES_DIR = ROOT / "reports" / "cleaned_templates"
AUDIT_LOGS_DIR = ROOT / "reports" / "audit_logs"


def main() -> None:
    st.set_page_config(page_title="SAP Migration Pre-Validation Agent", layout="wide")
    st.title("SAP Migration Template Pre-Validation Agent")

    mode = st.sidebar.radio(
        "Mode",
        ["Manual Validation", "Semi-Automated Batch Mode", "Folder Scanner Mode"],
    )
    if mode == "Semi-Automated Batch Mode":
        _render_batch_mode_page()
        return
    if mode == "Folder Scanner Mode":
        _render_folder_scanner_page()
        return

    profile_names = list_profile_names(PROFILES_DIR)
    with st.sidebar:
        selected_object = st.selectbox("Migration object", profile_names)
        profile = load_profile(selected_object, PROFILES_DIR)
        st.subheader("Required config files")
        for source_name, filename in required_config_filenames(profile).items():
            st.caption(f"{source_name}: {filename}")
        st.subheader("Required mapping files")
        mapping_filenames = required_mapping_filenames(profile)
        if mapping_filenames:
            for mapping_name, filename in mapping_filenames.items():
                st.caption(f"{mapping_name}: {filename}")
        else:
            st.caption("No mappings declared for this profile.")

    template_file = st.file_uploader("Upload filled migration template", type=["xlsx", "xlsm", "xls"])
    use_sample_configs = st.checkbox("Use files from config_samples when uploads are missing", value=True)
    config_uploads = st.file_uploader(
        "Upload config/reference files",
        type=["xlsx", "xlsm", "xls", "csv"],
        accept_multiple_files=True,
    )
    st.subheader("Mapping Files")
    mapping_filenames = required_mapping_filenames(profile)
    if mapping_filenames:
        st.caption("Upload mapping files or use the sample files under mappings/<object>.")
        mapping_uploads = st.file_uploader(
            "Upload mapping files",
            type=["xlsx", "xlsm", "xls", "csv"],
            accept_multiple_files=True,
        )
        use_sample_mappings = st.checkbox(
            "Use files from mappings/<object> when uploads are missing",
            value=True,
        )
    else:
        st.info("The selected profile does not declare mapping files.")
        mapping_uploads = []
        use_sample_mappings = False

    apply_mapping_before_validation = st.checkbox("Apply Mapping Before Validation", value=False)
    generate_cleaned_template_option = st.checkbox("Generate Cleaned Template", value=False)
    use_local_llm = st.checkbox("Use Local LLM Explanation", value=False)
    local_model_name = st.text_input("Local Model Name", value=DEFAULT_LOCAL_MODEL)

    if template_file is not None:
        with st.expander("Template detection", expanded=False):
            try:
                detected_data = load_template_excel(template_file)
                detected_object = detect_template(detected_data, PROFILES_DIR)
                st.write(detected_object or "No confident match.")
            except Exception as exc:  # noqa: BLE001 - Streamlit should display friendly diagnostics.
                st.warning(f"Template detection failed: {exc}")

    run_clicked = st.button("Run Validation", type="primary", disabled=template_file is None)
    if not run_clicked:
        return

    try:
        profile = load_profile(selected_object, PROFILES_DIR)
        template_data = load_template_excel_with_profile(template_file, profile)
        uploaded_by_name = {Path(upload.name).name: upload for upload in config_uploads}
        fallback_dir = CONFIG_DIR if use_sample_configs else None
        config_data = load_config_files(profile, uploaded_by_name, fallback_dir=fallback_dir)
        mapped_template_data = template_data
        mapping_actions: list[MappingAction] = []
        if apply_mapping_before_validation:
            mapping_sources = _mapping_sources(
                selected_object,
                profile,
                mapping_uploads,
                use_sample_mappings,
            )
            mappings = load_mapping_files(profile, mapping_sources)
            mapped_template_data, mapping_actions = apply_mappings(
                selected_object,
                profile,
                template_data,
                mappings,
            )
        result = run_validation(selected_object, profile, mapped_template_data, config_data)
    except ConfigLoaderError as exc:
        st.error(str(exc))
        return
    except MappingLoaderError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - Streamlit should display friendly diagnostics.
        st.exception(exc)
        return

    llm_explanations: list[str] | None = None
    if use_local_llm and result.issues:
        with st.spinner("Generating local LLM explanations..."):
            llm_explanations = [
                explain_issue_with_local_llm(
                    issue,
                    _issue_context(issue, mapping_actions),
                    local_model_name,
                )
                for issue in result.issues
            ]

    summary_columns = st.columns(4)
    summary_columns[0].metric("Total Rows", result.total_rows)
    summary_columns[1].metric("Errors", result.error_count)
    summary_columns[2].metric("Warnings", result.warning_count)
    summary_columns[3].metric("Status", result.status)

    issue_rows = []
    for index, issue in enumerate(result.issues):
        row = issue.model_dump()
        if llm_explanations is not None:
            row["llm_explanation"] = llm_explanations[index]
        issue_rows.append(row)
    issues_df = pd.DataFrame(issue_rows)
    if issues_df.empty:
        st.success("No validation issues found.")
    else:
        st.subheader("Error Details")
        st.dataframe(
            issues_df[issues_df["severity"] == "ERROR"],
            hide_index=True,
            use_container_width=True,
        )
        warnings_df = issues_df[issues_df["severity"] == "WARNING"]
        if not warnings_df.empty:
            st.subheader("Warning Details")
            st.dataframe(warnings_df, hide_index=True, use_container_width=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_bytes = generate_excel_report_bytes(result, llm_explanations=llm_explanations)
    st.download_button(
        label="Download validation_report.xlsx",
        data=report_bytes,
        file_name=f"validation_report_{selected_object}_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if mapping_actions:
        st.subheader("Mapping Audit")
        mapping_df = pd.DataFrame([action.model_dump() for action in mapping_actions])
        st.dataframe(mapping_df, hide_index=True, use_container_width=True)
        audit_bytes = generate_mapping_audit_report_bytes(mapping_actions)
        AUDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (AUDIT_LOGS_DIR / f"mapping_audit_{selected_object}_{timestamp}.xlsx").write_bytes(audit_bytes)
        st.download_button(
            label="Download mapping_audit.xlsx",
            data=audit_bytes,
            file_name=f"mapping_audit_{selected_object}_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if generate_cleaned_template_option:
        source_template_path = _persist_uploaded_template(template_file, selected_object, timestamp)
        cleaned_path = generate_cleaned_template(
            str(source_template_path),
            mapped_template_data,
            mapping_actions,
            result,
            str(CLEANED_TEMPLATES_DIR / f"cleaned_template_{selected_object}_{timestamp}.xlsx"),
        )
        st.download_button(
            label="Download cleaned_template.xlsx",
            data=Path(cleaned_path).read_bytes(),
            file_name=f"cleaned_template_{selected_object}_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _mapping_sources(
    object_name: str,
    profile: dict,
    mapping_uploads: list,
    use_sample_mappings: bool,
) -> dict[str, object]:
    sources: dict[str, object] = {Path(upload.name).name: upload for upload in mapping_uploads}
    if not use_sample_mappings:
        return sources

    fallback_dir = MAPPINGS_DIR / object_name
    for mapping_name, filename in required_mapping_filenames(profile).items():
        if mapping_name in sources or filename in sources:
            continue
        candidate = fallback_dir / filename
        if candidate.exists():
            sources[filename] = candidate
    return sources


def _issue_context(issue: ValidationIssue, mapping_actions: list[MappingAction]) -> dict:
    related_actions = [
        action.model_dump()
        for action in mapping_actions
        if action.sheet_name == issue.sheet_name
        and action.row_number == issue.row_number
        and action.field_name == issue.field_name
    ]
    return {"related_mapping_actions": related_actions[:5]}


def _persist_uploaded_template(template_file, selected_object: str, timestamp: str) -> Path:
    CLEANED_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(getattr(template_file, "name", "template.xlsx")).suffix or ".xlsx"
    output_path = CLEANED_TEMPLATES_DIR / f"source_template_{selected_object}_{timestamp}{suffix}"
    template_file.seek(0)
    output_path.write_bytes(template_file.read())
    template_file.seek(0)
    return output_path


def _render_batch_mode_page() -> None:
    st.header("Semi-Automated Batch Mode")
    st.caption("The Streamlit app does not start the watcher. Run it from a terminal or scheduler.")

    incoming_dir = ROOT / "input" / "incoming"
    reports_dir = ROOT / "output" / "reports"
    log_path = ROOT / "logs" / "automation.log"

    col1, col2 = st.columns(2)
    col1.metric("Input incoming folder", str(incoming_dir))
    col2.metric("Output reports folder", str(reports_dir))

    st.subheader("Watcher commands")
    st.code("python -m automation.watcher", language="bash")
    st.code("python -m automation.watcher --once", language="bash")
    st.code("python -m automation.watcher --settings automation/settings.yml --once", language="bash")

    st.subheader("Recent processing log")
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        st.text("\n".join(lines[-30:]) or "No batch processing entries yet.")
    else:
        st.info("No automation log found yet.")


def _render_folder_scanner_page() -> None:
    st.header("Folder Scanner Dashboard")
    st.caption(
        "Use this when object load files are dropped into watched object folders instead of uploaded manually."
    )

    settings = load_settings("automation/settings.yml")
    scanner_settings = settings.get("folder_scanner", {}) or {}
    paths_settings = settings.get("paths", {}) or {}
    base_dir = _resolve_project_path(scanner_settings.get("base_dir", "input/object_batches"))
    reports_dir = _resolve_project_path(paths_settings.get("output_reports_dir", "output/reports"))
    log_path = ROOT / "logs" / "automation.log"
    profile_names = list_profile_names(PROFILES_DIR)

    col1, col2 = st.columns(2)
    col1.metric("Base folder", str(base_dir))
    col2.metric("Output reports folder", str(reports_dir))

    if st.button("Refresh Status"):
        _rerun()

    st.subheader("Object Folder Status")
    status_df = get_object_folder_status(base_dir)
    if status_df.empty:
        st.info("No object batch folders found yet.")
    else:
        st.dataframe(status_df, hide_index=True, use_container_width=True)

    with st.expander("Object incoming folders", expanded=False):
        for object_name in profile_names:
            st.code(str(base_dir / object_name / "incoming"), language="text")

    if st.button("Scan Folder Once", type="primary"):
        with st.spinner("Scanning folders and running pre-validation..."):
            configure_logging(settings)
            results = scan_once(settings)
        st.session_state["folder_scan_results"] = [result.model_dump() for result in results]
        st.success(f"Processed {len(results)} file(s)")

    _render_latest_folder_scan_results()

    st.subheader("Folder scanner commands")
    st.code("python -m automation.folder_scanner --once", language="bash")
    st.code("python -m automation.folder_scanner", language="bash")
    st.code(
        "python -m automation.folder_scanner --settings automation/settings.yml --once",
        language="bash",
    )

    st.subheader("Recent processing log")
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        st.text("\n".join(lines[-30:]) or "No folder scanner entries yet.")
    else:
        st.info("No automation log found yet.")

    auto_mode = st.checkbox("Enable auto scan (every 10s)", value=False)
    if auto_mode:
        time.sleep(10)
        configure_logging(settings)
        results = scan_once(settings)
        st.session_state["folder_scan_results"] = [result.model_dump() for result in results]
        _rerun()


def _render_latest_folder_scan_results() -> None:
    result_rows = st.session_state.get("folder_scan_results", [])
    if not result_rows:
        return

    result_df = pd.DataFrame(
        [
            {
                "file": row.get("file_name"),
                "object": row.get("object_name"),
                "status": row.get("status"),
                "errors": row.get("error_count"),
                "warnings": row.get("warning_count"),
            }
            for row in result_rows
        ]
    )
    st.subheader("Latest Scan Results")
    st.dataframe(result_df, hide_index=True, use_container_width=True)

    for index, row in enumerate(result_rows, start=1):
        st.caption(f"{row.get('file_name')} - {row.get('status')}")
        columns = st.columns(3)
        _download_artifact_button(columns[0], row.get("report_path"), "Download Report", index)
        _download_artifact_button(
            columns[1],
            row.get("cleaned_template_path"),
            "Download Cleaned Template",
            index,
        )
        _download_artifact_button(
            columns[2],
            row.get("mapping_audit_path"),
            "Download Mapping Audit",
            index,
        )


def _download_artifact_button(column, artifact_path: str | None, label: str, index: int) -> None:
    if not artifact_path:
        column.write("")
        return
    path = Path(artifact_path)
    if not path.exists():
        column.warning(f"{label} unavailable")
        return
    column.download_button(
        label=label,
        data=path.read_bytes(),
        file_name=path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"folder_scan_{label}_{index}_{path.name}",
    )


def _resolve_project_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _rerun() -> None:
    rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun:
        rerun()


if __name__ == "__main__":
    main()
