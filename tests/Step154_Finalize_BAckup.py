# STEP 154: FINALIZE MANUAL BACKUP.
# Does not modify SQL Server or communicate with the PLC.

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

source = Path("Live_Test.L5K").resolve()
staging = manager.BACKUP_STORAGE_ROOT / "Staging"

matches = [
    p for p in staging.glob("*_Live_Test.L5K")
    if p.is_file()
    and manager.calculate_file_hash(p)
    == manager.calculate_file_hash(source)
]

if len(matches) != 1:
    raise RuntimeError(
        f"Expected one matching staged backup; found {len(matches)}."
    )

evaluation = manager.evaluate_backup(
    manager.BackupTrigger.MANUAL,
    manager.ComparisonResult.INCOMPLETE
)

archived = manager.finalize_backup(
    matches[0],
    manager.BACKUP_STORAGE_ROOT,
    evaluation
)

print("Archive:", archived)
print("Original exists:", source.is_file())
print("Archive exists:", archived.is_file())
print(
    "Hashes match:",
    manager.calculate_file_hash(source)
    == manager.calculate_file_hash(archived)
)