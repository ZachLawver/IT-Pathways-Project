# STEP 212: TEST THE TRACE BACKUPS WEB PAGE.
# Read-only. No PLC communication or SQL modifications.

import importlib.util
from pathlib import Path

web_path = Path("V0.011_Web.py").resolve()

spec = importlib.util.spec_from_file_location(
    "trace_web",
    web_path,
)

web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

web.app.config["TESTING"] = True

with web.app.test_client() as client:
    response = client.get("/backups")

    print("HTTP status:", response.status_code)

    html = response.get_data(as_text=True)

    print("BackupID 1 filename found:", "Live_Test.L5K" in html)
    print("BackupID 2 filename found:",
          "Test_PLC_2026-10-12_001.L5K" in html)
    print("Project name found:", "zacks_a_fairy" in html)

    assert response.status_code == 200
    assert "Live_Test.L5K" in html
    assert "Test_PLC_2026-10-12_001.L5K" in html
    assert "zacks_a_fairy" in html

    print("PASS: TRACE Backups page displays both backups.")