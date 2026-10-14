# STEP 221: VERIFY BACKUP HISTORY ISOLATION BETWEEN PLCS.
# Test-only controller data. No database modifications.

import importlib.util
from pathlib import Path
from unittest.mock import patch


# STEP 221A: LOAD TRACE'S FLASK APPLICATION.

web_path = Path("V0.011_Web.py").resolve()

spec = importlib.util.spec_from_file_location(
    "trace_web",
    web_path,
)

web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

web.app.config["TESTING"] = True


# STEP 221B: SIMULATE TWO REGISTERED CONTROLLERS.

test_controllers = [
    {"ControllerID": 1, "ControllerName": "Test PLC"},
    {"ControllerID": 2, "ControllerName": "Second PLC"},
]


# STEP 221C: REQUEST BACKUPS FOR THE SECOND PLC.

with patch.object(web, "get_controllers", return_value=test_controllers):

    with patch.object(
        web.backup_manager,
        "get_controller_backup_history",
        return_value=[],
    ) as history_query:

        with web.app.test_client() as client:

            response = client.get("/backups?controller_id=2")
            html = response.get_data(as_text=True)

            print("HTTP status:", response.status_code)
            print("Second PLC listed:", "Second PLC" in html)
            print("No backups message:", "No registered backups found." in html)
            print("Test PLC backup hidden:", "Live_Test.L5K" not in html)

            history_query.assert_called_once_with(2)

            assert response.status_code == 200
            assert "Second PLC" in html
            assert "No registered backups found." in html
            assert "Live_Test.L5K" not in html

            print("PASS: Controller 2 requests its own backup history.")