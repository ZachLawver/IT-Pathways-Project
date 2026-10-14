# STEP 161: TEST REGISTERED CONTROLLER NAME LOOKUP.
# Read-only. No backup or database modifications.

import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py"
)

manager = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)

name = manager.get_backup_controller_name(1)

print("ControllerID:", 1)
print("Registered Name:", name)
print("PASS" if name == "Test PLC" else "CHECK NAME")
