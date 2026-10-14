# STEP 1: IMPORT LIBRARIES.
from pathlib import Path
from acd.api import ImportProjectFromFile


# STEP 2: SELECT THE ACD FILE.
folder = Path(__file__).resolve().parent
project_file = folder / "LANLOGIX.ACD"


# STEP 3: LOAD THE ACD PROJECT.
project = ImportProjectFromFile(str(project_file)).import_project()
controller = project.controller


# STEP 4: DISPLAY ONLY SMALL, SIMPLE ATTRIBUTES.
# Do not print dictionaries, lists, objects, or long strings.
def show_attributes(label, obj):
    print(f"\n{label}")

    for name in dir(obj):
        if name.startswith("__"):
            continue

        try:
            value = getattr(obj, name)

            if isinstance(value, (str, int, float, bool)):
                value_text = str(value)

                if len(value_text) <= 100:
                    print(f"{name}: {value_text}")

        except Exception:
            continue


# STEP 5: INSPECT CONTROLLER AND PROJECT METADATA.
show_attributes("CONTROLLER ATTRIBUTES:", controller)
show_attributes("PROJECT ATTRIBUTES:", project)


# STEP 6: FINISH.
print("\nTRACE ACD IDENTIFICATION TEST COMPLETE")

# STEP 7: CHECK IDENTIFICATION FIELDS.
# Only display short values associated with the controller.

for name in (
    "processor_type",
    "catalog_number",
    "catalog",
    "product_code",
    "product_name",
    "vendor_id",
    "device_type",
    "name",
    "_name",
):
    value = getattr(controller, name, None)

    if value is not None:
        print(f"{name}: {str(value)[:100]}")