from __future__ import annotations


SCHEDULER_NOTES = """
Use the watcher in one-shot mode for operating-system schedulers.

Windows Task Scheduler action:
  Program: python
  Arguments: -m automation.watcher --once
  Start in: <path to sap_migration_prevalidator>

Cron example:
  */15 * * * * cd /path/to/sap_migration_prevalidator && python -m automation.watcher --once

The scheduler does not upload to SAP and does not execute SAP migration. It only
starts the local batch validation watcher.
"""


def print_scheduler_notes() -> None:
    print(SCHEDULER_NOTES.strip())


if __name__ == "__main__":
    print_scheduler_notes()

