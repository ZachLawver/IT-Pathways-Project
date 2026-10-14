# STEP 204: TEST CONTROLLER BACKUP HISTORY.
# Read-only. No SQL modifications or PLC communication.

import importlib.util

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py",
)

manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

history = manager.get_controller_backup_history(1)

for backup in history:
    print("-" * 60)
    print("BackupID:", backup["BackupID"])
    print("ControllerID:", backup["ControllerID"])
    print("ProjectID:", backup["ProjectID"])
    print("ProjectName:", backup["ProjectName"])
    print("FilePath:", backup["FilePath"])
    print("Comparison:", backup["ComparisonResult"])
    print("Retention:", backup["RetentionDecision"])

backup_ids = {backup["BackupID"] for backup in history}

assert 1 in backup_ids, "BackupID 1 missing."
assert 2 in backup_ids, "BackupID 2 missing."

print("-" * 60)
print("PASS: Controller backup history retrieved successfully.")