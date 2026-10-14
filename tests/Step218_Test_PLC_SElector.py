# STEP 219: TEST AN UNREGISTERED CONTROLLER ID.
# Verify that invalid controller IDs cannot retrieve backup history.
# Read-only test. No SQL modifications or PLC communication.

import importlib.util
from pathlib import Path


# STEP 219A: LOAD THE TRACE FLASK APPLICATION.

web_path = Path("V0.011_Web.py").resolve()

spec = importlib.util.spec_from_file_location(
    "trace_web",
    web_path,
)

web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

web.app.config["TESTING"] = True


# STEP 219B: REQUEST BACKUPS FOR AN UNREGISTERED CONTROLLER.

with web.app.test_client() as client:

    response = client.get("/backups?controller_id=999999")

    html = response.get_data(as_text=True)


    # STEP 219C: DISPLAY TEST RESULTS.

    print("HTTP status:", response.status_code)

    print(
        "No backups message:",
        "No registered backups found." in html,
    )

    print(
        "Backup 1 hidden:",
        "Live_Test.L5K" not in html,
    )

    print(
        "Backup 2 hidden:",
        "Test_PLC_2026-10-12_001.L5K" not in html,
    )


    # STEP 219D: VERIFY INVALID IDS DO NOT DISPLAY BACKUPS.

    assert response.status_code == 200

    assert "No registered backups found." in html

    assert "Live_Test.L5K" not in html

    assert "Test_PLC_2026-10-12_001.L5K" not in html

    print(
        "PASS: Unregistered controller ID does not display backup history."
    )