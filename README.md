# SAP Migration Template Pre-Validation Agent

This MVP validates and prepares filled SAP S/4HANA Migration Cockpit Excel templates before data is uploaded to SAP. It checks required fields, max length, config existence, duplicate combinations, and cross-sheet consistency using YAML profiles and local reference files. It also supports deterministic legacy-to-SAP value mapping, auditable cleaned template generation, and optional local LLM explanations.

## Install

```bash
cd sap_migration_prevalidator
pip install -r requirements.txt
```

## Run

```bash
streamlit run app/main.py
```

## How It Works

The app is profile-driven, rule-driven, config-driven, and template-independent.

- `profiles/*.yml` declares sheets, fields, required flags, format rules, config sources, and cross-sheet rules.
- `config_samples/*` provides local reference data such as plants, UoM, material types, and valuation classes.
- `app/rule_engine.py` applies generic rules to any profile. Adding a new migration object should not require changing the main rule engine.
- `app/mapping_engine.py` applies deterministic mappings declared in the profile.
- `app/autofix_engine.py` writes a cleaned template and traceable audit sheets.
- `app/local_llm.py` can ask a local Ollama model to explain validation issues.
- `app/report_generator.py` creates a downloadable `validation_report.xlsx`.

## How To Use The Mapping Engine

1. Add a `mappings` section to the relevant YAML profile.
2. Put mapping files under `mappings/<OBJECT>/`, or upload them in Streamlit.
3. In Streamlit, select `Apply Mapping Before Validation`.
4. Run validation. The rule engine validates the mapped data, and the Mapping Audit shows every mapped, unmapped, ambiguous, or unchanged value.

Example profile mapping:

```yaml
mappings:
  base_uom:
    filename: uom_mapping.xlsx
    sheet: Sheet1
    source_column: LegacyUoM
    target_column: SAPUoM
    target_field:
      sheet: Basic Data
      field: BaseUoM
    strategy: exact
    on_missing: keep_original
    severity_on_missing: WARNING
```

Supported mapping strategies:

- `exact`
- `case_insensitive`
- `trim_upper`

Fuzzy matching is intentionally not used for automatic replacement.

## How To Create Mapping Files

Each mapping workbook should contain at least:

```text
LegacyValue | SAPValue | Active | Comment
```

Profiles can override the source and target column names, for example `LegacyUoM` and `SAPUoM`.

Rules:

- Only `Active = Y` rows are used.
- `Active = N` rows are ignored.
- Blank legacy values are ignored.
- Blank SAP target values are treated as mapping file errors.
- Duplicate active legacy values are marked `AMBIGUOUS` and are not changed.

Sample mapping workbooks are included under `mappings/`.

## How Auto Fix Works

When `Generate Cleaned Template` is selected, the app writes:

- `cleaned_template.xlsx`
- `mapping_audit.xlsx`
- the existing `validation_report.xlsx`

The cleaned template preserves source sheet names and field column order, removes the internal `__excel_row_number` column, and adds:

- `Mapping Audit`
- `Validation Issues`

Mapped cells also receive comments where supported by Excel.

## Safety Rules For Auto Fix

Auto Fix only performs deterministic, profile-driven changes:

- trim whitespace during parsing
- uppercase lookup normalization where the profile uses `trim_upper`
- replace legacy values with configured SAP values

Auto Fix never:

- lets an LLM guess or change business data
- auto-applies fuzzy matches
- changes amounts, dates, or quantities
- deletes rows
- creates SAP master data

Rule engine decides correctness. Mapping engine transforms deterministic values. Local LLM only explains.

## How To Use Ollama Local Model

Install and run Ollama locally, then enable `Use Local LLM Explanation` in Streamlit.

```bash
ollama pull llama3.1:8b
ollama serve
streamlit run app/main.py
```

Default local model:

```text
llama3.1:8b
```

You can also enter another local model name, such as:

- `qwen2.5:7b`
- `mistral:7b`
- `llama3.1:8b`

If Ollama is unavailable, validation continues and the report uses a deterministic fallback explanation.

## Semi-Automated Batch Mode

Batch mode watches an input folder, detects migration templates, loads config and mapping files, runs validation, writes reports, and moves source files through controlled folders. It never uploads to SAP and never executes SAP migration.

Folder flow:

```text
input/incoming   -> new files dropped by user
input/processing -> watcher-owned working folder
input/processed  -> successfully processed files
input/failed     -> unknown templates, missing config, or stopped validation failures
```

Outputs:

```text
output/reports
output/cleaned_templates
output/mapping_audits
output/logs
logs/automation.log
```

Run continuously:

```bash
python -m automation.watcher
```

Run once, suitable for Windows Task Scheduler or cron:

```bash
python -m automation.watcher --once
```

Use a custom settings file:

```bash
python -m automation.watcher --settings automation/settings.yml --once
```

Windows Task Scheduler can call:

```bash
python -m automation.watcher --once
```

The Streamlit app also has a `Semi-Automated Batch Mode` view showing the input path, output report path, watcher commands, and recent automation log entries. It does not start the watcher.

## Batch Configuration

Edit `automation/settings.yml`.

Config files are loaded from:

```text
config_samples
```

or the configured `paths.config_dir`. Missing required config files fail the batch item.

Mapping files are loaded from:

```text
mappings/<OBJECT>
```

Missing mapping files are logged as warnings and validation still runs, because mapping is an enhancement layer.

Output file names include the source file stem, detected migration object, timestamp, status, and artifact type, for example:

```text
material_master_legacy_values_sample__MATERIAL_MASTER__20260504_143200__SUCCESS__validation_report.xlsx
```

## Batch Notifications

Notifications are disabled by default. Enable them in `automation/settings.yml`.

Email uses SMTP and reads the password from an environment variable:

```yaml
notification:
  enabled: true
  channels:
    email:
      enabled: true
      smtp_password_env: SMTP_PASSWORD
```

Teams uses an incoming webhook URL from an environment variable:

```yaml
notification:
  enabled: true
  channels:
    teams:
      enabled: true
      webhook_url_env: TEAMS_WEBHOOK_URL
```

Template email extraction is supported. Batch mode scans columns such as `Email`, `ContactEmail`, `OwnerEmail`, and `ResponsibleEmail`, then scans string cells for email patterns. If template emails are found, they are preferred up to `max_template_recipients`; otherwise the default settings recipients are used.

Notification safety rules:

- Template emails are used only for notifications.
- Emails are never used for permission or approval decisions.
- The app does not email full business data.
- The app sends only a summary and local report paths.
- Reports are not attached by default.
- Notification failures are logged and do not fail validation.

## Batch Safety Rules

- The watcher does not modify files in `input/incoming`.
- Files are moved to `input/processing` before processing.
- Original files end in `input/processed` or `input/failed`.
- Cleaned templates are written only to `output/cleaned_templates`.
- Reports and audits are written as new files and never overwrite source data.
- No automatic SAP upload.
- No automatic SAP migration.

## Folder Scanner Mode

Use this mode when business users or migration consultants drop object load files into a watched folder instead of uploading them manually in Streamlit. Each migration object gets its own batch folder, so the folder name can be used as the migration object when template detection is weak or unavailable.

Recommended structure:

```text
input/object_batches/MATERIAL_MASTER/incoming/
input/object_batches/MATERIAL_MASTER/processing/
input/object_batches/MATERIAL_MASTER/processed/
input/object_batches/MATERIAL_MASTER/failed/

input/object_batches/BP_CUSTOMER/incoming/
input/object_batches/OPEN_PO/incoming/
```

Example:

```text
input/object_batches/MATERIAL_MASTER/incoming/material_load_001.xlsx
```

The scanner treats this as `MATERIAL_MASTER` when that folder name exists in `profiles/`. If the folder name is not a known profile, it falls back to template detection when enabled in `automation/settings.yml`.

Run once:

```bash
python -m automation.folder_scanner --once
```

Run continuously:

```bash
python -m automation.folder_scanner
```

Use a custom settings file:

```bash
python -m automation.folder_scanner --settings automation/settings.yml --once
```

Docker example:

```bash
docker compose run --rm sap-migration-agent python -m automation.folder_scanner --once
```

Folder scanner outputs are written to the same unified output folders:

```text
output/reports
output/cleaned_templates
output/mapping_audits
output/logs
```

## Folder Scanner Dashboard

Use the Streamlit UI to scan object folders without using the CLI:

- View object folder status.
- Click `Scan Folder Once` to trigger validation.
- Review latest scan results.
- Download validation reports, cleaned templates, and mapping audits.

Open the app:

```bash
streamlit run app/main.py
```

Then select `Folder Scanner Mode` in the sidebar.

The dashboard shows counts for:

```text
object_name | incoming | processing | processed | failed
```

The UI is only a control layer. It calls `automation.folder_scanner.scan_once(settings)` once per button click, then displays the returned `BatchProcessResult` list.

Design rules:

- Folder scanner orchestrates only.
- Batch processor validates.
- Rule engine decides correctness.
- Mapping engine only does deterministic mapping.
- Auto Fix only outputs cleaned templates.
- No SAP upload.
- No source file overwrite.
- No business data mutation in incoming folders.

## Add A New Migration Object

1. Create `profiles/YOUR_OBJECT.yml`.
2. Declare `template_detection`, `config_sources`, `sheets`, and optional `cross_sheet_rules`.
3. Add sample config files under `config_samples/` if the profile needs them.
4. Restart Streamlit and select the new object in the sidebar.

## Example Workflow

1. Select `MATERIAL_MASTER`.
2. Upload `sample_templates/material_master_sample.xlsx`.
3. Keep `Use files from config_samples when uploads are missing` checked.
4. Click `Run Validation`.
5. Review the summary and error details.
6. Download the Excel validation report.

The included Material Master sample intentionally produces at least five errors:

- Invalid material type.
- Invalid base unit of measure.
- Invalid plant.
- Plant Data material missing from Basic Data.
- Invalid valuation class for material type.

The included `sample_templates/material_master_legacy_values_sample.xlsx` demonstrates mapping behavior:

- `Finished` maps to `FERT`
- `Raw` maps to `ROH`
- `Each` maps to `EA`
- `PCS` maps to `PC`
- `SG01` maps to `1000`
- `SG02` maps to `1100`
- `SG99` remains unmapped
- `BADUOM` remains unmapped

## Tests

```bash
pytest tests -q
```

## Development Workflow

This project uses a branch-based pull request workflow. Develop changes on feature branches, run tests locally, push the branch, and open a pull request into `main`.

## Security Notes

- Do not commit real SAP data.
- Do not commit production mapping files.
- Do not store SMTP passwords or webhook URLs in settings.yml.
- Use environment variables for secrets.

## Quick Start (Docker)

```bash
docker build -t sap-migration-prevalidator .
docker run -p 8501:8501 sap-migration-prevalidator
```
