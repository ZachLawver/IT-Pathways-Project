# STEP 191: TEST BACKUP FILENAME GENERATION.
# Read-only: does not create or modify backups.

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py",
)

manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

controller_folder = manager.get_controller_backup_folder(1)

filename = manager.generate_backup_filename(
    controller_id=1,
    storage_root=controller_folder,
    file_extension=".L5K",
)

print("Controller folder:", controller_folder)
print("Next backup filename:", filename)
print("Already exists:", (controller_folder / "Archive" / filename).exists())