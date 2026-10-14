# STEP 220: VERIFY THE CORRECT PLC IS SELECTED.
# Read-only Flask test.

import importlib.util
from pathlib import Path
from html.parser import HTMLParser


# STEP 220A: LOAD TRACE'S FLASK APPLICATION.

web_path = Path("V0.011_Web.py").resolve()

spec = importlib.util.spec_from_file_location(
    "trace_web",
    web_path,
)

web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

web.app.config["TESTING"] = True


# STEP 220B: INSPECT THE CONTROLLER DROPDOWN.

class ControllerSelectorParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.selected_ids = []

    def handle_starttag(self, tag, attrs):
        if tag != "option":
            return

        attributes = dict(attrs)

        if "selected" in attributes:
            self.selected_ids.append(attributes.get("value"))


# STEP 220C: REQUEST CONTROLLER 1.

with web.app.test_client() as client:

    response = client.get("/backups?controller_id=1")

    parser = ControllerSelectorParser()
    parser.feed(response.get_data(as_text=True))

    print("HTTP status:", response.status_code)
    print("Selected controller IDs:", parser.selected_ids)

    assert response.status_code == 200
    assert parser.selected_ids == ["1"]

    print("PASS: ControllerID 1 is selected correctly.")