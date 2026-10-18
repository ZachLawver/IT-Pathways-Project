

# STEP 1: Import monitoring and identification libraries.
from datetime import datetime, timezone
import os
import ipaddress
import uuid

from pycomm3 import CIPDriver, LogixDriver
import pyodbc

# STEP 2: Configure the TRACE SQL Server connection.
SQL_CONNECTION = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.environ.get('TRACE_SQL_SERVER', r'localhost\SQLEXPRESS')};"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


# STEP 3: Begin read-only controller identification.
def identify_controller(ip_address):


    # STEP 4: Validate the supplied controller IP address.
    ip_address = str(ipaddress.ip_address(ip_address.strip()))

    print(f"TRACE: Connecting to {ip_address}...")


    # STEP 5: Read the controller's CIP hardware identity.
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


    # STEP 6: Prepare to retrieve the Logix project name.
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
    

    # STEP 7: Return the identified controller information.
    return {
        "ip_address": ip_address,
        "controller_name": controller_name,
        "plc_model": product_name.split(" ")[0],
        "controller_family": (
            "CompactLogix"
            if "CompactLogix" in product_name
            else "ControlLogix"
            if "ControlLogix" in product_name
            else "Unknown"
        ),
        "firmware_major": revision.get("major"),
        "firmware_minor": revision.get("minor"),
        "serial_number": (
            serial.hex()
            if isinstance(serial, bytes)
            else str(serial)
        ),
    }


# STEP 8: Begin SQL registration and hardware tracking.
def register_controller(identity):

    connection = pyodbc.connect(
        SQL_CONNECTION,
        timeout=5
    )

    try:
        cursor = connection.cursor()


        cursor.execute(
            # STEP 9: Protect registration against concurrent changes.
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )


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

        # STEP 10: Check for existing processor installation history.
        existing = cursor.fetchone()


        # STEP 11: Update a previously registered active processor.
        if existing and existing[2] is None:

            hardware_id = existing[0]
            controller_id = existing[1]


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

            # STEP 12: Reject conflicting controller IP assignments.
            if conflict:
                raise ValueError(
                    "IP address is assigned to another "
                    "TRACE installation. Possible processor "
                    "relocation or IP conflict. "
                    "No records were changed."
                )


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

            # STEP 13: Record successful registration updates.
            action = "updated"

        # STEP 14: Handle newly detected or historically removed processors.
        else:


            cursor.execute("""
                SELECT ControllerID, ControllerName
                FROM dbo.Controllers
                    WITH (UPDLOCK, HOLDLOCK)
                WHERE IPAddress = ?
            """, identity["ip_address"])

            conflict = cursor.fetchone()

           

            # STEP 15: Record a possible processor replacement warning.
            if conflict:
                controller_id = conflict[0]


                connection.rollback()


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


                connection.commit()

                raise ValueError(
                    "POSSIBLE PROCESSOR REPLACEMENT: "
                    f"Different hardware detected at "
                    f"{identity['ip_address']}. "
                    "A pending hardware event was recorded. "
                    "Technician confirmation is required."
                )



            # STEP 16: Prevent automatic reassignment of historical hardware.
            if existing:
                raise ValueError(
                    "KNOWN PROCESSOR REDETECTED: "
                    "This processor has a previous "
                    "installation history. "
                    "Manual review is required before "
                    "assigning it to equipment."
                )


            # STEP 17: Select the detected controller name.
            controller_name = str(
                identity.get("controller_name") or ""
            ).strip()


            if not controller_name:
                controller_name = f"Unnamed_{uuid.uuid4().hex[:12]}"

            # STEP 18: Create the new controller installation.
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

            # STEP 19: Retrieve the new controller installation ID.
            controller_id = cursor.fetchone()[0]


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

            # STEP 20: Record successful new registration.
            action = "registered"


        # STEP 21: Commit verified controller registration changes.
        connection.commit()

        return controller_id, action

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()





# STEP 22: Begin technician-confirmed processor replacement.
def confirm_hardware_replacement(
    event_id,
    technician_name,
    resolution_notes
):

    # STEP 23: Validate technician identity and maintenance notes.
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


        if detected_ip != assigned_ip:
            raise ValueError(
                "The equipment IP has changed. "
                "Review the warning before confirming."
            )

    finally:
        connection.close()


    # STEP 24: Verify the replacement processor is physically present.
    identity = identify_controller(detected_ip)

    if identity["serial_number"] != expected_serial:
        raise ValueError(
            "Replacement verification failed. "
            "The connected processor does not match "
            "the pending hardware event."
        )

    connection = pyodbc.connect(SQL_CONNECTION, timeout=5)

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )


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
        

        cursor.execute("""
            SELECT
                HardwareID,
                ControllerID,
                InstalledAt,
                RemovedAt
            FROM dbo.ControllerHardware WITH (UPDLOCK, HOLDLOCK)
            WHERE SerialNumber = ?
        """, identity["serial_number"])

        # STEP 25: Check the replacement processor's complete history.
        previous_installations = cursor.fetchall()


        if previous_installations:
            raise ValueError(
                "This processor has an existing installation "
                "history in TRACE. Manual review is required "
                "before assigning it to this equipment."
            )



        cursor.execute("""
            UPDATE dbo.ControllerHardware
            SET RemovedAt = SYSUTCDATETIME()
            WHERE ControllerID = ?
              AND RemovedAt IS NULL
              AND SerialNumber <> ?
        """, controller_id, identity["serial_number"])

        # STEP 26: Verify exactly one existing processor was retired.
        if cursor.rowcount != 1:
            raise ValueError(
                "Expected exactly one installed processor. "
                "Replacement was cancelled."
            )


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

        if cursor.rowcount != 1:
            raise ValueError(
                "Replacement event changed. Transaction cancelled."
            )


        # STEP 27: Commit the confirmed processor replacement.
        connection.commit()
        return controller_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 28: Run live identification and SQL registration.
def main(ip_address):

    try:


        identity = identify_controller(ip_address)

        print("\nTRACE - LIVE CONTROLLER")
        print("IP Address:", identity["ip_address"])
        print("Product:", identity["controller_name"])

        print(
            "Firmware:",
            f"{identity['firmware_major']}."
            f"{identity['firmware_minor']}"
        )


        controller_id, action = register_controller(identity)

        print(f"SQL Controller ID: {controller_id}")
        print(f"Controller successfully {action}.")

        print(
            "Last Contact:",
            datetime.now(timezone.utc).isoformat()
        )

    except Exception as error:
        print(f"TRACE monitoring failed: {error}")


# STEP 29: Accept a controller IP address from the command line.
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("ip_address", help="PLC IPv4 address")
    args = parser.parse_args()
    main(args.ip_address)


