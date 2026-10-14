# STEP 169: REGISTER EXISTING ARCHIVED BACKUP.
# No PLC communication or new backup file creation.

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py"
)
manager = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)

archive = Path(
    r"C:\TRACE_Backups\Archive"
    r"\20261012T055444Z_097f0ba0df454d2da54415f14509298a_aac3b9e7c71c4d7d9e179ef767b5555a_Live_Test.L5K"
)

# STEP 169A: VERIFY ARCHIVED FILE.
if not archive.is_file():
    raise FileNotFoundError(archive)

# STEP 169B: PREVENT DUPLICATE REGISTRATION.
connection = manager.connect_trace_database()

try:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT BackupID FROM dbo.Backups WHERE FilePath = ?",
        str(archive.resolve()),
    )
    existing = cursor.fetchone()
finally:
    connection.close()

if existing:
    raise RuntimeError(
        f"Backup already registered as BackupID {existing[0]}."
    )

# STEP 169C: USE TRACE'S RETENTION ENGINE.
evaluation = manager.evaluate_backup(
    manager.BackupTrigger.MANUAL,
    manager.ComparisonResult.INCOMPLETE,
)

# STEP 169D: REGISTER BACKUP AND COMPARISON TOGETHER.
result = manager.register_backup_transaction(
    controller_id=1,
    project_id=1,
    backup_source=manager.BackupTrigger.MANUAL,
    evaluation=evaluation,
    archived_file=archive,
    notes="Initial manual backup; full-project comparison incomplete.",
)

print("BackupID:", result["BackupID"])
print("ComparisonID:", result["ComparisonID"])
print("FilePath:", result["FilePath"])
print("PASS: Backup registered successfully.")