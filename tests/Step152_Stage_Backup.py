# STEP 152: STAGE AND VERIFY MANUAL BACKUP.
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
staged = manager.stage_backup(
    source,
    manager.BACKUP_STORAGE_ROOT
)

print("Original:", source)
print("Staged:", staged)
print("Original exists:", source.is_file())
print("Staged exists:", staged.is_file())
print(
    "Hashes match:",
    manager.calculate_file_hash(source)
    == manager.calculate_file_hash(staged)
)
