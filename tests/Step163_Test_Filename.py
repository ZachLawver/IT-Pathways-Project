# STEP 163: TEST BACKUP FILENAME GENERATION.
# Read-only. Does not create or modify backups.

import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py"
)

manager = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)

filename = manager.generate_backup_filename(
    controller_id=1,
    storage_root=manager.BACKUP_STORAGE_ROOT,
    file_extension=".L5K"
)

print("Registered Controller:", manager.get_backup_controller_name(1))
print("Generated Filename:", filename)
print("File Already Exists:", (
    (manager.BACKUP_STORAGE_ROOT / "Archive" / filename).exists()
    or (manager.BACKUP_STORAGE_ROOT / "Hold" / filename).exists()
))
