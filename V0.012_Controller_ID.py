# ==========================================================
# TRACE - CONTROLLER IDENTIFICATION - VERSION 0.012
# Read controller metadata from L5X or ACD project files.
# Optionally register/update an existing TRACE SQL inventory.
# ==========================================================

# STEP 1: IMPORT STANDARD LIBRARIES.
from pathlib import Path
import argparse
import xml.etree.ElementTree as ET


# STEP 2: CLASSIFY ONLY RECOGNIZED ROCKWELL CATALOG NUMBERS.
def classify_controller(catalog):
    catalog = (catalog or "").strip().upper()
    if catalog.startswith("1756-L"):
        return "ControlLogix"  # GuardLogix subfamilies need further identification.
    if catalog.startswith(("5069-L", "1769-L", "1768-L")):
        return "CompactLogix"
    if catalog.startswith("1747-L"):
        return "SLC 500"
    if catalog.startswith("1785-L"):
        return "PLC-5"
    if catalog.startswith(("1762-L", "1763-L", "1764-L", "1766-L")):
        return "MicroLogix"
    return None


# STEP 3: READ CONTROLLER METADATA FROM A FULL-PROJECT L5X EXPORT.
def identify_l5x(filename):
    root = ET.parse(filename).getroot()
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]

    controller = root if root.tag == "Controller" else root.find("Controller")
    if controller is None:
        raise ValueError("No Controller element found; this may be a partial L5X export.")

    catalog = controller.get("ProcessorType") or None
    name = controller.get("Name") or root.get("TargetName")
    if not name:
        raise ValueError("No controller name found in L5X export.")

    return {
        "name": name,
        "catalog": catalog,
        "family": classify_controller(catalog),
        "raw_processor_type": None,
        "major_revision": controller.get("MajorRev"),
        "minor_revision": controller.get("MinorRev"),
        "source": "L5X",
    }


# STEP 4: READ NATIVE ACD METADATA THROUGH THE INSTALLED PARSER.
# Do not assume its CIP processor identifier is a Rockwell catalog number.
def identify_acd(filename):
    try:
        from acd.api import ImportProjectFromFile
    except ImportError as error:
        raise RuntimeError("Install acd-tools to inspect ACD files.") from error

    project = ImportProjectFromFile(str(filename)).import_project()
    controller = project.controller
    name = (getattr(controller, "_name", None)
            or getattr(controller, "name", None)
            or getattr(project, "target_name", None))
    if not isinstance(name, str) or not name.strip():
        raise ValueError("ACD parser did not return a usable controller name.")

    processor = getattr(controller, "processor_type", None)
    processor_text = str(processor) if processor is not None else None

    # Only accept a processor value as a catalog if it looks like one.
    # ACD parsers commonly return identifiers such as CIP-1-14-217.
    catalog = processor_text if classify_controller(processor_text) else None
    return {
        "name": name.strip(),
        "catalog": catalog,
        "family": classify_controller(catalog),
        "raw_processor_type": processor_text,
        "major_revision": getattr(controller, "major_rev", None),
        "minor_revision": getattr(controller, "minor_rev", None),
        "source": "ACD",
    }


# STEP 5: CHOOSE THE READER BASED ON FILE EXTENSION.
def identify_controller(filename):
    filename = Path(filename)
    if not filename.is_file():
        raise FileNotFoundError(filename)
    if filename.suffix.lower() == ".l5x":
        return identify_l5x(filename)
    if filename.suffix.lower() == ".acd":
        return identify_acd(filename)
    raise ValueError("Supported project formats: .L5X and .ACD")


# STEP 6: OPTIONALLY REGISTER OR UPDATE THE CONTROLLER IN SQL SERVER.
# This updates known catalog/family fields, never overwrites them with NULL.
# It does not save the project file or create a backup record.
def save_controller(metadata):
    import pyodbc

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        r"SERVER=localhost\SQLEXPRESS;"
        "DATABASE=TRACE;"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    connection = pyodbc.connect(connection_string, timeout=5)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT ControllerID FROM dbo.Controllers WHERE ControllerName = ?",
            metadata["name"],
        )
        matches = cursor.fetchall()
        if len(matches) > 1:
            raise ValueError("Multiple controllers have this name; refusing ambiguous update.")

        if matches:
            controller_id = matches[0][0]
            cursor.execute("""
                UPDATE dbo.Controllers
                SET PLCModel = COALESCE(?, PLCModel),
                    ControllerFamily = COALESCE(?, ControllerFamily)
                WHERE ControllerID = ?
            """, metadata["catalog"], metadata["family"], controller_id)
            action = "Updated"
        else:
            cursor.execute("""
                INSERT INTO dbo.Controllers (ControllerName, PLCModel, ControllerFamily)
                OUTPUT INSERTED.ControllerID
                VALUES (?, ?, ?)
            """, metadata["name"], metadata["catalog"], metadata["family"])
            controller_id = cursor.fetchone()[0]
            action = "Registered"

        connection.commit()
        return action, controller_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# STEP 7: PRINT A SHORT REPORT AND SAVE ONLY WHEN REQUESTED.
def main():
    parser = argparse.ArgumentParser(description="TRACE controller identification")
    parser.add_argument("project", help="Path to an .ACD or .L5X project")
    parser.add_argument("--save", action="store_true", help="Register/update SQL inventory")
    args = parser.parse_args()

    metadata = identify_controller(args.project)
    print("\nTRACE - CONTROLLER IDENTIFICATION v0.012")
    print("Project:", Path(args.project).name)
    print("Controller:", metadata["name"])
    print("Catalog:", metadata["catalog"] or "Not determined")
    print("Family:", metadata["family"] or "Not determined")
    print("Raw processor identifier:", metadata["raw_processor_type"] or "Not available")
    print("Major revision:", metadata["major_revision"] or "Not available")
    print("Minor revision:", metadata["minor_revision"] or "Not available")

    if args.save:
        action, controller_id = save_controller(metadata)
        print(f"SQL Server: {action} controller ID {controller_id}")
    else:
        print("SQL Server: No changes (read-only test)")


# STEP 8: RUN ONLY WHEN EXECUTED DIRECTLY.
if __name__ == "__main__":
    main()
