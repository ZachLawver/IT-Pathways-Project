
# ==========================================================
# TRACE - ETHERNET MONITOR - VERSION 0.014
# Automatic PLC identification and SQL registration.
# Tracks physical processors separately from installations.
# Read-only communication with the PLC.
# ==========================================================

# STEP 1: IMPORT REQUIRED LIBRARIES.
from datetime import datetime, timezone
import os
import ipaddress
import uuid

from pycomm3 import CIPDriver, LogixDriver
import pyodbc

SQL_CONNECTION = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.environ.get('TRACE_SQL_SERVER', r'localhost\SQLEXPRESS')};"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


# STEP 3: READ THE PHYSICAL CONTROLLER IDENTITY.
def identify_controller(ip_address):

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

        # STEP 455A: READ THE CONTROLLER'S LOGIX PROJECT NAME.
    # This is read-only and does not upload or modify logic.

    controller_name = product_name

    try:
        with LogixDriver(ip_address) as logix:
            detected_name = logix.info.get("name")

            if detected_name and str(detected_name).strip():
                controller_name = str(detected_name).strip()

    except Exception as error:
        print(
            "TRACE: Logix project name unavailable. "
            f"Using hardware identity. Details: {error}"
        )
    
    # STEP 3C: RETURN THE CONTROLLER INFORMATION.
    # Serial numbers are used internally for identification.

    return {
        "ip_address": ip_address,
        "controller_name": controller_name,
        "plc_model": product_name.split(" ")[0],
        "controller_family": "CompactLogix",
        "firmware_major": revision.get("major"),
        "firmware_minor": revision.get("minor"),
        "serial_number": (
            serial.hex()
            if isinstance(serial, bytes)
            else str(serial)
        ),
    }


# STEP 4: REGISTER OR UPDATE CONTROLLER HARDWARE.
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
                SET PLCModel = ?,
                    FirmwareMajor = ?,
                    FirmwareMinor = ?,
                    LastSeen = SYSUTCDATETIME()
                WHERE HardwareID = ?
            """,
                identity["plc_model"],
                identity["firmware_major"],
                identity["firmware_minor"],
                hardware_id
            )
            
            # STEP 485: RECOVER AN UNNAMED CONTROLLER'S PROGRAMMED NAME.
            # Never overwrite a technician-assigned friendly name.

            detected_name = str(
                identity.get("controller_name") or ""
            ).strip()

            current_name = str(existing[3] or "").strip()

            if (
                current_name.startswith("Unnamed_")
                and detected_name
                and not detected_name.startswith("Unnamed_")
            ):
                cursor.execute("""
                    UPDATE dbo.Controllers
                    SET ControllerName = ?
                    WHERE ControllerID = ?
                """,
                    detected_name,
                    controller_id
                )
                
            # STEP 4F: UPDATE THE EQUIPMENT'S CURRENT
            # CONNECTION INFORMATION.
            # Keep the original ControllerID and name.

            cursor.execute("""
                UPDATE dbo.Controllers
                SET IPAddress = ?,
                    PLCModel = ?,
                    ControllerFamily = ?,
                    FirmwareMajor = ?,
                    FirmwareMinor = ?,
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

            # STEP 456: USE THE DETECTED LOGIX CONTROLLER NAME.
            # Preserve the ability to assign a friendly name later.
            # Existing controller names are not overwritten during rescans.

            controller_name = str(
                identity.get("controller_name") or ""
            ).strip()

            # STEP 456A: FALL BACK TO A UNIQUE TEMPORARY NAME
            # IF THE CONTROLLER NAME CANNOT BE READ.

            if not controller_name:
                controller_name = f"Unnamed_{uuid.uuid4().hex[:12]}"

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


# STEP 5: CONFIRM A PROCESSOR REPLACEMENT.
# Only a technician-initiated action should call this function.
# Never call it automatically during normal scanning.


# STEP 5: CONFIRM A PROCESSOR REPLACEMENT.
# Require technician attribution and maintenance notes.

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

    identity = identify_controller(detected_ip)

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


# STEP 5: RUN THE COMPLETE MONITORING TEST.
def main():

    try:

        # STEP 5A: IDENTIFY THE LIVE PLC.

        identity = identify_controller(PLC_IP)

        print("\nTRACE - LIVE CONTROLLER")
        print("IP Address:", identity["ip_address"])
        print("Product:", identity["controller_name"])

        print(
            "Firmware:",
            f"{identity['firmware_major']}."
            f"{identity['firmware_minor']}"
        )

        # STEP 5B: REGISTER OR UPDATE THE CONTROLLER.

        controller_id, action = register_controller(identity)

        print(f"SQL Controller ID: {controller_id}")
        print(f"Controller successfully {action}.")

        print(
            "Last Contact:",
            datetime.now(timezone.utc).isoformat()
        )

    except Exception as error:
        print(f"TRACE monitoring failed: {error}")


# STEP 6: EXECUTE THE MONITOR.
if __name__ == "__main__":
    main()


