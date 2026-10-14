# ==========================================================
# TRACE - CONTROLLER REGISTRY - VERSION 0.021
# Unified PLC identification, project metadata, and SQL registry.
# PLC identity reads are read-only. SQL registration is opt-in.
# ==========================================================

# STEP 1: IMPORT LIBRARIES.
import argparse
import ipaddress
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET
import re
import pyodbc
from pycomm3 import CIPDriver

# STEP 2: CONFIGURE SQL SERVER.
SQL_CONNECTION = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

# STEP 3: LOOK UP CONTROLLER AND HARDWARE BY PERMANENT ID.
def get_controller(controller_id):

    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:

        cursor = connection.cursor()

        cursor.execute("""

            SELECT

                ControllerID,

                ControllerName,

                IPAddress,

                PLCModel,

                ControllerFamily,

                SerialNumber,

                CommunicationStatus

            FROM dbo.Controllers

            WHERE ControllerID = ?

        """, controller_id)

        row = cursor.fetchone()

        if row is None:

            return None

        return {

            "ControllerID": row[0],

            "ControllerName": row[1],

            "IPAddress": row[2],

            "PLCModel": row[3],

            "ControllerFamily": row[4],

            "SerialNumber": row[5],

            "CommunicationStatus": row[6],

        }

    finally:

        connection.close()

def get_hardware_history(controller_id):

    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:

        cursor = connection.cursor()

        cursor.execute("""

            SELECT

                HardwareID,

                SerialNumber,

                PLCModel,

                InstalledAt,

                RemovedAt

            FROM dbo.ControllerHardware

            WHERE ControllerID = ?

            ORDER BY HardwareID

        """, controller_id)

        return [

            {

                "HardwareID": row[0],

                "SerialNumber": row[1],

                "PLCModel": row[2],

                "InstalledAt": row[3],

                "RemovedAt": row[4],

            }

            for row in cursor.fetchall()

        ]

    finally:

        connection.close()

# STEP 5: CLASSIFY RECOGNIZED ROCKWELL CATALOG NUMBERS.
def classify_controller(catalog):
    catalog = (catalog or "").strip().upper()
    if catalog.startswith("1756-L"):
        return "ControlLogix"  # GuardLogix requires more detailed identification.
    if catalog.startswith(("5069-L", "1769-L", "1768-L")):
        return "CompactLogix"
    if catalog.startswith("1747-L"):
        return "SLC 500"
    if catalog.startswith("1785-L"):
        return "PLC-5"
    if catalog.startswith(("1762-L", "1763-L", "1764-L", "1766-L")):
        return "MicroLogix"
    return None

# STEP 98: IDENTIFY CONTROLLER FROM l5x EXPORT.
# Reads project metadata without modifying the file or PLC.

def identify_l5x(filename):

    # STEP 98A: READ THE l5x FILE.
    with open(filename, "r", encoding="utf-8-sig") as file:
        content = file.read()
        # STEP 98B: EXTRACT THE COMPLETE VERSION FROM THE l5x HEADER.
        version_match = re.search(
            r"^\s*Version\s*:=\s*RSLogix\s+5000\s+v(\d+\.\d+)",
            content,
            re.IGNORECASE | re.MULTILINE
        )

        if not version_match:
            raise ValueError("l5x version information not found.")

        revision = version_match.group(1)

    # STEP 98B: FIND THE CONTROLLER DECLARATION.
    match = re.search(
        r'\bCONTROLLER\s+([^\s(]+)\s*\(\s*'
        r'ProcessorType\s*:=\s*"([^"]+)"\s*,\s*'
        r'Major\s*:=\s*(\d+)',
        content,
        re.IGNORECASE
    )

    if not match:
        raise ValueError(
            "Could not identify the controller in the l5x export."
        )

    # STEP 98C: EXTRACT CONTROLLER METADATA.
    name = match.group(1)
    catalog = match.group(2)
    major_revision = match.group(3)

    # STEP 98D: RETURN STANDARDIZED PROJECT INFORMATION.
   # STEP 100: RETURN THE VERSION FROM THE l5x HEADER.
    return {
        "name": name,
        "catalog": catalog,
        "family": classify_controller(catalog),
        "raw_processor_type": None,
        "revision": revision,
        "source": "l5x",
    }
# STEP 6: IDENTIFY A FULL-PROJECT L5X FILE.
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
  
# STEP 101: IDENTIFY PROJECT FROM l5x OR L5X EXPORT.
# ACD files are intentionally unsupported.

def identify_project_controller(filename):
    filename = Path(filename)

    if not filename.is_file():
        raise FileNotFoundError(filename)

    extension = filename.suffix.lower()

    if extension == ".l5x":
        return identify_l5x(filename)

    if extension == ".l5x":
        return identify_l5x(filename)

    raise ValueError(
        "Unsupported project format. TRACE accepts l5x and L5X only."
    )

# STEP 9: ASSOCIATE PROJECT CATALOG/FAMILY WITH A KNOWN CONTROLLER ID.
# Explicit opt-in. No new controller creation, no name matching.
# Project revision is NOT assumed to equal live processor firmware.
def update_controller_from_project(controller_id, metadata):
    if not isinstance(controller_id, int) or controller_id < 1:
        raise ValueError("A valid permanent ControllerID is required.")
    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)
    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE dbo.Controllers
            SET PLCModel = COALESCE(?, PLCModel),
                ControllerFamily = COALESCE(?, ControllerFamily)
            WHERE ControllerID = ?
        """, metadata.get("catalog"), metadata.get("family"), controller_id)
        if cursor.rowcount != 1:
            raise ValueError("ControllerID not found; no controller was created.")
        connection.commit()
        return controller_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

# STEP 10: READ LIVE PLC IDENTITY.
def identify_live_controller(ip_address):

    # STEP 3A: VALIDATE THE CONTROLLER IP ADDRESS.

    # TRACE should only scan an address explicitly supplied

    # for a controller the user is authorized to monitor.

    ip_address = str(ipaddress.ip_address(ip_address.strip()))

    print(f"TRACE: Connecting to {ip_address}...")

    # STEP 3B: READ THE CONTROLLER'S CIP IDENTITY.

    # This does not modify the controller's program.

    with CIPDriver(ip_address) as plc:

        identity = plc.get_module_info(0)

    if not isinstance(identity, dict):

        raise ValueError("Invalid CIP identity response.")

    revision = identity.get("revision") or {}

    product_name = str(

        identity.get("product_name") or ""

    ).strip()

    serial = identity.get("serial")

    if not product_name or serial is None:

        raise ValueError("Controller identity is incomplete.")

    # STEP 3C: RETURN THE CONTROLLER INFORMATION.

    # Serial numbers are used internally for identification.

    return {

        "ip_address": ip_address,

        "controller_name": product_name,

        "plc_model": product_name.split(" ")[0],

        "controller_family": classify_controller(product_name.split(" ")[0]),

        "firmware_major": revision.get("major"),

        "firmware_minor": revision.get("minor"),

        "serial_number": (

            serial.hex()

            if isinstance(serial, bytes)

            else str(serial)

        ),

    }

# STEP 116: REGISTER A VERIFIED PROJECT TO ITS CONTROLLER.
# Rejects incompatible hardware.
# Stores project metadata separately from physical PLC identity.
# Prevents duplicate project registrations.

def register_project(controller_id, metadata):
    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:
        cursor = connection.cursor()

        # STEP 116A: VERIFY THE PHYSICAL CONTROLLER.
        cursor.execute("""
            SELECT PLCModel
            FROM dbo.Controllers
            WHERE ControllerID = ?
        """, controller_id)

        row = cursor.fetchone()

        if row is None:
            raise ValueError(
                f"ControllerID {controller_id} does not exist."
            )

        registered_model = (row[0] or "").strip().upper()
        project_model = (metadata.get("catalog") or "").strip().upper()

        registered_catalog = registered_model.split("/")[0]
        project_catalog = project_model.split("/")[0]

        if not registered_catalog or not project_catalog:
            raise ValueError("Missing processor catalog.")

        if registered_catalog != project_catalog:
            raise ValueError(
                f"Hardware mismatch: ControllerID {controller_id} "
                f"is {registered_model}, but project is {project_model}."
            )

        # STEP 116B: CHECK FOR AN EXISTING REGISTRATION.
        cursor.execute("""
            SELECT ProjectID
            FROM dbo.ControllerProjects
            WHERE ControllerID = ?
              AND ProjectName = ?
              AND ProcessorCatalog = ?
              AND SourceFormat = ?
        """,
            controller_id,
            metadata["name"],
            metadata["catalog"],
            metadata["source"]
        )

        existing = cursor.fetchone()

        if existing:
            return existing[0]

        # STEP 116C: REGISTER THE PROJECT.
        cursor.execute("""
            INSERT INTO dbo.ControllerProjects (
                ControllerID,
                ProjectName,
                ProcessorCatalog,
                ProjectRevision,
                SourceFormat
            )
            OUTPUT INSERTED.ProjectID
            VALUES (?, ?, ?, ?, ?)
        """,
            controller_id,
            metadata["name"],
            metadata["catalog"],
            metadata.get("revision"),
            metadata["source"]
        )

        project_id = cursor.fetchone()[0]

        connection.commit()

        return project_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

 # STEP 123: RETRIEVE PROJECTS FOR A REGISTERED CONTROLLER.
# Read-only. Does not modify SQL Server or the PLC.

def get_controller_projects(controller_id):
    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                ProjectID,
                ControllerID,
                ProjectName,
                ProcessorCatalog,
                ProjectRevision,
                SourceFormat,
                RegisteredAt
            FROM dbo.ControllerProjects
            WHERE ControllerID = ?
            ORDER BY ProjectID
        """, controller_id)

        columns = [column[0] for column in cursor.description]

        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()

# STEP 125: RETRIEVE A REGISTERED PROJECT BY PROJECT ID.
# Read-only. Does not modify SQL Server or the PLC.

def get_project(project_id):
    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                ProjectID,
                ControllerID,
                ProjectName,
                ProcessorCatalog,
                ProjectRevision,
                SourceFormat,
                RegisteredAt
            FROM dbo.ControllerProjects
            WHERE ProjectID = ?
        """, project_id)

        row = cursor.fetchone()

        if row is None:
            return None

        columns = [column[0] for column in cursor.description]

        return dict(zip(columns, row))

    finally:
        connection.close()

# STEP 11: REGISTER LIVE HARDWARE WITH SQL SAFETY CHECKS.
def register_controller(identity):

    connection = pyodbc.connect(

        SQL_CONNECTION,

        timeout=5

    )

    try:

        cursor = connection.cursor()

        # STEP 4A: START A SERIALIZABLE TRANSACTION.

        # This protects registration decisions from

        # concurrent scans modifying the same records.

        cursor.execute(

            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"

        )

        # STEP 4B: SEARCH THE HARDWARE HISTORY BY SERIAL.

        # Find the most recent installation of this processor.

        cursor.execute("""

            SELECT TOP (1)

                h.HardwareID,

                h.ControllerID,

                h.RemovedAt,

                c.ControllerName,

                c.IPAddress

            FROM dbo.ControllerHardware AS h

                WITH (UPDLOCK, HOLDLOCK)

            INNER JOIN dbo.Controllers AS c

                WITH (UPDLOCK, HOLDLOCK)

                ON h.ControllerID = c.ControllerID

            WHERE h.SerialNumber = ?

            ORDER BY

                CASE WHEN h.RemovedAt IS NULL

                    THEN 0 ELSE 1 END,

                h.HardwareID DESC

        """, identity["serial_number"])

        existing = cursor.fetchone()

        # STEP 4C: HANDLE A KNOWN, ACTIVE PROCESSOR.

        # Preserve its equipment name and ControllerID.

        if existing and existing[2] is None:

            hardware_id = existing[0]

            controller_id = existing[1]

            # STEP 4D: CHECK WHETHER THE NEW IP BELONGS

            # TO ANOTHER CONTROLLER INSTALLATION.

            cursor.execute("""

                SELECT ControllerID, ControllerName

                FROM dbo.Controllers

                    WITH (UPDLOCK, HOLDLOCK)

                WHERE IPAddress = ?

                  AND ControllerID <> ?

            """,

                identity["ip_address"],

                controller_id

            )

            conflict = cursor.fetchone()

            if conflict:

                raise ValueError(

                    "IP address is assigned to another "

                    "TRACE installation. Possible processor "

                    "relocation or IP conflict. "

                    "No records were changed."

                )

            # STEP 4E: UPDATE THE PHYSICAL PROCESSOR.

            cursor.execute("""

                UPDATE dbo.ControllerHardware

                SET PLCModel = COALESCE(?, PLCModel),

                    FirmwareMajor = COALESCE(?, FirmwareMajor),

                    FirmwareMinor = COALESCE(?, FirmwareMinor),

                    LastSeen = SYSUTCDATETIME()

                WHERE HardwareID = ?

            """,

                identity["plc_model"],

                identity["firmware_major"],

                identity["firmware_minor"],

                hardware_id

            )

            # STEP 4F: UPDATE THE EQUIPMENT'S CURRENT

            # CONNECTION INFORMATION.

            # Keep the original ControllerID and name.

            cursor.execute("""

                UPDATE dbo.Controllers

                SET IPAddress = ?,

                    PLCModel = ?,

                    ControllerFamily = ?,

                    FirmwareMajor = COALESCE(?, FirmwareMajor),

                    FirmwareMinor = COALESCE(?, FirmwareMinor),

                    LastSeen = SYSUTCDATETIME(),

                    CommunicationStatus = 'Online'

                WHERE ControllerID = ?

            """,

                identity["ip_address"],

                identity["plc_model"],

                identity["controller_family"],

                identity["firmware_major"],

                identity["firmware_minor"],

                controller_id

            )

            action = "updated"

        else:

            # STEP 4G: CHECK WHETHER THIS IP ADDRESS

            # ALREADY BELONGS TO AN EXISTING INSTALLATION.

            cursor.execute("""

                SELECT ControllerID, ControllerName

                FROM dbo.Controllers

                    WITH (UPDLOCK, HOLDLOCK)

                WHERE IPAddress = ?

            """, identity["ip_address"])

            conflict = cursor.fetchone()

            # STEP 4H: RECORD A POSSIBLE PROCESSOR REPLACEMENT.

            # An unfamiliar processor has appeared at an IP

            # address assigned to an existing installation.

            # Do not change the controller or hardware records.

            if conflict:

                controller_id = conflict[0]

                # STEP 4H-1: ROLL BACK THE REGISTRATION TRANSACTION.

                # Start a separate transaction for the warning.

                connection.rollback()

                # STEP 4H-2: RECORD THE WARNING ONLY ONCE.

                # Repeated scans of the same processor should

                # not create duplicate pending events.

                cursor.execute("""

                    IF NOT EXISTS (

                        SELECT 1

                        FROM dbo.HardwareEvents WITH (UPDLOCK, HOLDLOCK)

                        WHERE ControllerID = ?

                          AND DetectedSerialNumber = ?

                          AND EventType = 'PossibleReplacement'

                          AND EventStatus = 'Pending'

                    )

                    BEGIN

                        INSERT INTO dbo.HardwareEvents (

                            ControllerID,

                            EventType,

                            DetectedSerialNumber,

                            DetectedIPAddress,

                            EventStatus

                        )

                        VALUES (

                            ?, 'PossibleReplacement', ?, ?, 'Pending'

                        )

                    END

                """,

                    controller_id,

                    identity["serial_number"],

                    controller_id,

                    identity["serial_number"],

                    identity["ip_address"]

                )

                # STEP 4H-3: SAVE THE WARNING BEFORE

                # STOPPING AUTOMATIC REGISTRATION.

                connection.commit()

                raise ValueError(

                    "POSSIBLE PROCESSOR REPLACEMENT: "

                    f"Different hardware detected at "

                    f"{identity['ip_address']}. "

                    "A pending hardware event was recorded. "

                    "Technician confirmation is required."

                )

            # STEP 4I: DO NOT AUTOMATICALLY REASSIGN

            # HARDWARE THAT HAS A HISTORICAL RECORD.

            # This could be a previously removed processor.

            if existing:

                raise ValueError(

                    "KNOWN PROCESSOR REDETECTED: "

                    "This processor has a previous "

                    "installation history. "

                    "Manual review is required before "

                    "assigning it to equipment."

                )

            # STEP 4J: REGISTER A NEW EQUIPMENT INSTALLATION.

            # Give it a temporary name that can be edited.

            controller_name = (

                f"Unnamed_{uuid.uuid4().hex[:12]}"

            )

            cursor.execute("""

                INSERT INTO dbo.Controllers (

                    ControllerName,

                    IPAddress,

                    PLCModel,

                    ControllerFamily,

                    FirmwareMajor,

                    FirmwareMinor,

                    SerialNumber,

                    LastSeen,

                    CommunicationStatus

                )

                OUTPUT INSERTED.ControllerID

                VALUES (

                    ?, ?, ?, ?, ?, ?, ?,

                    SYSUTCDATETIME(), 'Online'

                )

            """,

                controller_name,

                identity["ip_address"],

                identity["plc_model"],

                identity["controller_family"],

                identity["firmware_major"],

                identity["firmware_minor"],

                identity["serial_number"]

            )

            controller_id = cursor.fetchone()[0]

            # STEP 4K: REGISTER THE PHYSICAL PROCESSOR.

            # The hardware record links to the new

            # permanent equipment installation.

            cursor.execute("""

                INSERT INTO dbo.ControllerHardware (

                    ControllerID,

                    SerialNumber,

                    PLCModel,

                    FirmwareMajor,

                    FirmwareMinor,

                    LastSeen

                )

                VALUES (

                    ?, ?, ?, ?, ?,

                    SYSUTCDATETIME()

                )

            """,

                controller_id,

                identity["serial_number"],

                identity["plc_model"],

                identity["firmware_major"],

                identity["firmware_minor"]

            )

            action = "registered"

        # STEP 4L: COMMIT BOTH DATABASE UPDATES TOGETHER.

        connection.commit()

        return controller_id, action

    except Exception:

        connection.rollback()

        raise

    finally:

        connection.close()

# STEP 12: TECHNICIAN-CONFIRMED HARDWARE REPLACEMENT.
def confirm_hardware_replacement(

    event_id,

    technician_name,

    resolution_notes

):

    # STEP 5A-1: VALIDATE TECHNICIAN INFORMATION.

    technician_name = technician_name.strip()

    resolution_notes = resolution_notes.strip()

    if not technician_name or len(technician_name) > 150:

        raise ValueError(

            "Enter a technician name of 150 characters or fewer."

        )

    if not resolution_notes or len(resolution_notes) > 1000:

        raise ValueError(

            "Enter maintenance notes of 1000 characters or fewer."

        )

    # STEP 5A: LOAD THE PENDING EVENT WITHOUT CHANGING DATA.

    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:

        cursor = connection.cursor()

        cursor.execute("""

            SELECT

                e.ControllerID,

                e.DetectedIPAddress,

                e.DetectedSerialNumber,

                c.IPAddress

            FROM dbo.HardwareEvents AS e

            INNER JOIN dbo.Controllers AS c

                ON c.ControllerID = e.ControllerID

            WHERE e.EventID = ?

              AND e.EventType = 'PossibleReplacement'

              AND e.EventStatus = 'Pending'

        """, event_id)

        event = cursor.fetchone()

        if not event:

            raise ValueError("Pending replacement event not found.")

        controller_id, detected_ip, expected_serial, assigned_ip = event

        # STEP 5B: VERIFY THE EVENT STILL REFERS

        # TO THE EQUIPMENT'S CURRENT IP ADDRESS.

        if detected_ip != assigned_ip:

            raise ValueError(

                "The equipment IP has changed. "

                "Review the warning before confirming."

            )

    finally:

        connection.close()

    # STEP 5C: RECONNECT TO THE PHYSICAL PLC.

    # Confirm that the replacement is still present.

    identity = identify_live_controller(detected_ip)

    if identity["serial_number"] != expected_serial:

        raise ValueError(

            "Replacement verification failed. "

            "The connected processor does not match "

            "the pending hardware event."

        )

    # STEP 5D: BEGIN THE DATABASE REPLACEMENT TRANSACTION.

    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:

        cursor = connection.cursor()

        cursor.execute(

            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"

        )

        # STEP 5E: LOCK AND REVALIDATE THE PENDING EVENT.

        cursor.execute("""

            SELECT

                e.ControllerID,

                e.DetectedIPAddress,

                e.DetectedSerialNumber,

                c.IPAddress

            FROM dbo.HardwareEvents AS e WITH (UPDLOCK, HOLDLOCK)

            INNER JOIN dbo.Controllers AS c WITH (UPDLOCK, HOLDLOCK)

                ON c.ControllerID = e.ControllerID

            WHERE e.EventID = ?

              AND e.EventType = 'PossibleReplacement'

              AND e.EventStatus = 'Pending'

        """, event_id)

        event = cursor.fetchone()

        if not event:

            raise ValueError(

                "This replacement event is no longer pending."

            )

        if (

            event[1] != identity["ip_address"]

            or event[2] != identity["serial_number"]

            or event[3] != identity["ip_address"]

        ):

            raise ValueError(

                "The replacement event or equipment assignment "

                "changed during verification."

            )

        controller_id = event[0]

        # STEP 5F: CHECK FOR EXISTING ACTIVE USE

        # OF THE REPLACEMENT PROCESSOR.

        cursor.execute("""

            SELECT ControllerID

            FROM dbo.ControllerHardware WITH (UPDLOCK, HOLDLOCK)

            WHERE SerialNumber = ?

              AND RemovedAt IS NULL

        """, identity["serial_number"])

        active = cursor.fetchone()

        if active:

            raise ValueError(

                "The replacement processor is already "

                "registered as active. Manual review required."

            )

        # STEP 5F-1: CHECK THE REPLACEMENT'S FULL HISTORY.

        # A processor that was previously installed anywhere

        # requires additional technician review.

        # Do not automatically reuse historical hardware.

        cursor.execute("""

            SELECT

                HardwareID,

                ControllerID,

                InstalledAt,

                RemovedAt

            FROM dbo.ControllerHardware WITH (UPDLOCK, HOLDLOCK)

            WHERE SerialNumber = ?

        """, identity["serial_number"])

        previous_installations = cursor.fetchall()

        # STEP 5F-2: REJECT PREVIOUSLY REGISTERED HARDWARE.

        # This also prevents duplicate registration of a

        # processor that is already active elsewhere.

        if previous_installations:

            raise ValueError(

                "This processor has an existing installation "

                "history in TRACE. Manual review is required "

                "before assigning it to this equipment."

            )

        # STEP 5G: RETIRE THE OLD PROCESSOR.

        # Preserve its historical hardware record.

        cursor.execute("""

            UPDATE dbo.ControllerHardware

            SET RemovedAt = SYSUTCDATETIME()

            WHERE ControllerID = ?

              AND RemovedAt IS NULL

              AND SerialNumber <> ?

        """, controller_id, identity["serial_number"])

        if cursor.rowcount != 1:

            raise ValueError(

                "Expected exactly one installed processor. "

                "Replacement was cancelled."

            )

        # STEP 5H: REGISTER THE NEW PHYSICAL PROCESSOR.

        cursor.execute("""

            INSERT INTO dbo.ControllerHardware (

                ControllerID,

                SerialNumber,

                PLCModel,

                FirmwareMajor,

                FirmwareMinor,

                LastSeen

            )

            VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME())

        """,

            controller_id,

            identity["serial_number"],

            identity["plc_model"],

            identity["firmware_major"],

            identity["firmware_minor"]

        )

        # STEP 5I: UPDATE THE EQUIPMENT'S CURRENT INFORMATION.

        # Preserve ControllerID and the friendly name.

        cursor.execute("""

            UPDATE dbo.Controllers

            SET PLCModel = ?,

                ControllerFamily = ?,

                FirmwareMajor = ?,

                FirmwareMinor = ?,

                SerialNumber = ?,

                LastSeen = SYSUTCDATETIME(),

                CommunicationStatus = 'Online'

            WHERE ControllerID = ?

              AND IPAddress = ?

        """,

            identity["plc_model"],

            identity["controller_family"],

            identity["firmware_major"],

            identity["firmware_minor"],

            identity["serial_number"],

            controller_id,

            identity["ip_address"]

        )

        if cursor.rowcount != 1:

            raise ValueError(

                "Equipment record changed. Replacement cancelled."

            )

        # STEP 5J: RESOLVE THE HARDWARE EVENT.

        # STEP 5J: RESOLVE THE HARDWARE EVENT.

        # Record technician attribution and maintenance notes

        # in the same transaction as the processor replacement.

        cursor.execute("""

            UPDATE dbo.HardwareEvents

            SET EventStatus = 'Confirmed',

                ResolvedAt = SYSUTCDATETIME(),

                ResolvedBy = ?,

                ResolutionNotes = ?

            WHERE EventID = ?

              AND EventStatus = 'Pending'

        """,

            technician_name,

            resolution_notes,

            event_id

        )

        # STEP 5K: SAVE ALL CHANGES TOGETHER.

        connection.commit()

        return controller_id

    except Exception:

        connection.rollback()

        raise

    finally:

        connection.close()

# STEP 13: COMMAND-LINE TESTS. READ-ONLY BY DEFAULT.
def main():
    parser = argparse.ArgumentParser(description="TRACE unified controller registry")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--controller-id", type=int, help="Read controller and hardware history")
    group.add_argument("--live", metavar="IP", help="Read PLC identity without SQL writes")
    group.add_argument("--register-live", metavar="IP", help="Explicitly register live PLC in SQL")
    group.add_argument("--project", metavar="FILE", help="Read ACD/L5X project metadata")
    args = parser.parse_args()

    if args.controller_id is not None:
        controller = get_controller(args.controller_id)
        if controller is None:
            raise ValueError("ControllerID not found.")
        print("Controller:", controller)
        print("Hardware history:", get_hardware_history(args.controller_id))
    elif args.live:
        print("Live PLC identity:", identify_live_controller(args.live))
    elif args.register_live:
        identity = identify_live_controller(args.register_live)
        controller_id, action = register_controller(identity)
        print("ControllerID:", controller_id, "Action:", action)
    elif args.project:
        print("Project metadata:", identify_project_controller(args.project))
    else:
        parser.print_help()

# STEP 14: RUN ONLY WHEN EXECUTED DIRECTLY.
if __name__ == "__main__":
    main()
