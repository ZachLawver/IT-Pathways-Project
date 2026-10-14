# STEP 195: STAGE A BACKUP FOR END-TO-END TESTING.

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py",
)

manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

source = Path("Live_Test.L5K").resolve()

staged = manager.stage_backup(
    source_file=source,
    storage_root=manager.BACKUP_STORAGE_ROOT,
)

print("Original:", source)
print("Staged:", staged)
print("Original exists:", source.exists())
print("Staged exists:", staged.exists())
print(
    "Hashes match:",
    manager.calculate_file_hash(source)
    == manager.calculate_file_hash(staged),
)