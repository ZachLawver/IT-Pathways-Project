# STEP 197: TEST COMPLETE BACKUP ARCHIVAL AND REGISTRATION.
# Uses an existing staged file. No PLC communication.

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py",
)

manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

staged = Path(
    r"C:\TRACE_Backups\Staging"
    r"\658ca99d922b46bbb2e587e00d7fa144_Live_Test.L5K"
)

# STEP 197A: PROTECT AGAINST REPEATED EXECUTION.
if not staged.is_file():
    raise FileNotFoundError(
        "Staged backup not found. Test may already have completed."
    )

# STEP 197B: EVALUATE AS A MANUAL, INCOMPLETE BACKUP.
evaluation = manager.evaluate_backup(
    manager.BackupTrigger.MANUAL,
    manager.ComparisonResult.INCOMPLETE,
)

# STEP 197C: ARCHIVE AND REGISTER BOTH SQL RECORDS.
result = manager.archive_and_register_backup(
    controller_id=1,
    project_id=1,
    backup_source=manager.BackupTrigger.MANUAL,
    staged_file=staged,
    evaluation=evaluation,
    notes="Step 197 controlled backup workflow test.",
)

print("Registration result:", result)
print("Staged file remains:", staged.exists())
print("PASS: Archive and registration completed.")