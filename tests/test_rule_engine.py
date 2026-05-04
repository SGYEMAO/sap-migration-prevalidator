from __future__ import annotations

from pathlib import Path

from app.config_loader import load_config_files
from app.data_parser import load_template_excel_with_profile
from app.profile_loader import load_profile
from app.report_generator import generate_excel_report
from app.rule_engine import run_validation
from app.template_detector import detect_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_material_master_sample_expected_errors(tmp_path: Path) -> None:
    profile = load_profile("MATERIAL_MASTER", PROJECT_ROOT / "profiles")
    template_data = load_template_excel_with_profile(
        PROJECT_ROOT / "sample_templates" / "material_master_sample.xlsx",
        profile,
    )
    config_data = load_config_files(profile, fallback_dir=PROJECT_ROOT / "config_samples")

    result = run_validation("MATERIAL_MASTER", profile, template_data, config_data)

    assert result.error_count >= 5
    messages = "\n".join(issue.message for issue in result.issues)
    assert "INVALID" in messages
    assert "BADUOM" in messages
    assert "9999" in messages
    assert "Material in Plant Data must exist in Basic Data." in messages
    assert "ValuationClass" in messages

    report_path = generate_excel_report(result, tmp_path / "validation_report.xlsx")
    assert Path(report_path).exists()


def test_template_detector_identifies_material_master() -> None:
    profile = load_profile("MATERIAL_MASTER", PROJECT_ROOT / "profiles")
    template_data = load_template_excel_with_profile(
        PROJECT_ROOT / "sample_templates" / "material_master_sample.xlsx",
        profile,
    )

    detected = detect_template(template_data, PROJECT_ROOT / "profiles")

    assert detected == "MATERIAL_MASTER"

