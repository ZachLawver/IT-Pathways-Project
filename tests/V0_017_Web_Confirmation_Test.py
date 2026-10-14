
# ==========================================================
# TRACE - WEB CONFIRMATION TEST
# Tests the Flask Confirm Replacement action using
# synthetic hardware and a mocked Ethernet response.
# ==========================================================

# STEP 1: IMPORT REQUIRED LIBRARIES.
import importlib.util
import uuid
from pathlib import Path
from unittest.mock import patch

import pyodbc


# STEP 2: LOAD THE EXISTING FLASK APPLICATION.
web_path = (
    Path(__file__).resolve().parent
    / "V0.011_Web.py"
)

spec = importlib.util.spec_from_file_location(
    "trace_web_test",
    web_path
)

web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


# STEP 3: CONFIGURE SYNTHETIC TEST IDENTIFIERS.
test_id = uuid.uuid4().hex[:12]
test_name = f"TRACE_CONFIRM_TEST_{test_id}"
test_ip = "127.0.0.3"

old_serial = f"TRACE_CONFIRM_OLD_{test_id}"
new_serial = f"TRACE_CONFIRM_NEW_{test_id}"

identity = {
    "ip_address": test_ip,
    "controller_name": test_name,
    "plc_model": "1769-L30ER/A",
    "controller_family": "CompactLogix",
    "firmware_major": 30,
    "firmware_minor": 11,
    "serial_number": new_serial
}


# STEP 4: CREATE THE SYNTHETIC CONTROLLER AND EVENT.
def create_records(connection):

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO dbo.Controllers (
            ControllerName, IPAddress, PLCModel,
            ControllerFamily, FirmwareMajor, FirmwareMinor,
            SerialNumber, CommunicationStatus
        )
        OUTPUT INSERTED.ControllerID
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Not checked')
    """,
        test_name, test_ip, "1769-L30ER/A",
        "CompactLogix", 30, 11, old_serial
    )

    controller_id = cursor.fetchone()[0]

    cursor.execute("""
        INSERT INTO dbo.ControllerHardware (
            ControllerID, SerialNumber, PLCModel,
            FirmwareMajor, FirmwareMinor
        )
        VALUES (?, ?, ?, 30, 11)
    """, controller_id, old_serial, "1769-L30ER/A")

    cursor.execute("""
        INSERT INTO dbo.HardwareEvents (
            ControllerID, EventType,
            DetectedSerialNumber, DetectedIPAddress,
            EventStatus
        )
        OUTPUT INSERTED.EventID
        VALUES (?, 'PossibleReplacement', ?, ?, 'Pending')
    """, controller_id, new_serial, test_ip)

    event_id = cursor.fetchone()[0]
    connection.commit()

    return controller_id, event_id


# STEP 5: VERIFY THE WEB CONFIRMATION RESULTS.
def verify_records(connection, controller_id, event_id):

    cursor = connection.cursor()

    # STEP 5A: VERIFY THE EQUIPMENT NAME WAS PRESERVED.
    cursor.execute("""
        SELECT ControllerName, SerialNumber
        FROM dbo.Controllers
        WHERE ControllerID = ?
    """, controller_id)

    equipment = cursor.fetchone()

    assert equipment is not None
    assert equipment[0] == test_name
    assert equipment[1] == new_serial

    # STEP 5B: VERIFY THE ORIGINAL HARDWARE WAS RETIRED.
    cursor.execute("""
        SELECT RemovedAt
        FROM dbo.ControllerHardware
        WHERE ControllerID = ? AND SerialNumber = ?
    """, controller_id, old_serial)

    assert cursor.fetchone()[0] is not None

    # STEP 5C: VERIFY THE NEW HARDWARE IS ACTIVE.
    cursor.execute("""
        SELECT RemovedAt
        FROM dbo.ControllerHardware
        WHERE ControllerID = ? AND SerialNumber = ?
    """, controller_id, new_serial)

    assert cursor.fetchone()[0] is None

    
    # STEP 5D: VERIFY THE EVENT AND TECHNICIAN ATTRIBUTION.
    # Check the event status, timestamp, technician, and notes.

    cursor.execute("""
        SELECT
            EventStatus,
            ResolvedAt,
            ResolvedBy,
            ResolutionNotes
        FROM dbo.HardwareEvents
        WHERE EventID = ?
    """, event_id)

    event = cursor.fetchone()

    assert event is not None
    assert event[0] == "Confirmed"
    assert event[1] is not None
    assert event[2] == "TRACE Test Technician"
    assert event[3] == "Synthetic processor replacement test."

    print("PASS: Technician attribution and notes saved.")


    print("PASS: Flask confirmation action executed.")
    print("PASS: Equipment identity preserved.")
    print("PASS: Original processor retired.")
    print("PASS: Replacement processor registered.")
    print("PASS: Hardware event confirmed.")


# STEP 6: REMOVE ONLY THIS TEST'S RECORDS.
def cleanup(connection, controller_id):

    cursor = connection.cursor()

    # STEP 6A: DELETE THE SYNTHETIC EVENT.
    cursor.execute("""
        DELETE FROM dbo.HardwareEvents
        WHERE ControllerID = ?
    """, controller_id)

    # STEP 6B: DELETE SYNTHETIC HARDWARE HISTORY.
    cursor.execute("""
        DELETE FROM dbo.ControllerHardware
        WHERE ControllerID = ?
    """, controller_id)

    # STEP 6C: DELETE SYNTHETIC EQUIPMENT.
    cursor.execute("""
        DELETE FROM dbo.Controllers
        WHERE ControllerID = ?
          AND ControllerName = ?
    """, controller_id, test_name)

    connection.commit()


# STEP 7: RUN THE WEB CONFIRMATION TEST.
def main():

    connection = pyodbc.connect(
        web.connection_string,
        timeout=5
    )

    controller_id = None

    try:
        # STEP 7A: CREATE THE TEST RECORDS.
        controller_id, event_id = create_records(connection)

        # STEP 7B: SEND A TEST POST TO THE FLASK ROUTE.
        # Mock the identity function so no PLC is contacted.
        web.app.config["TESTING"] = True

       
        # STEP 7B: SUBMIT A SYNTHETIC TECHNICIAN CONFIRMATION.
        # Mock the PLC identity so no physical PLC is contacted.

        with patch.object(
            web.ethernet_monitor,
            "identify_controller",
            return_value=identity
        ):
            with web.app.test_client() as client:
                response = client.post(
                    "/controllers",
                    data={
                        "action": "confirm_replacement",
                        "event_id": str(event_id),
                        "technician_name": "TRACE Test Technician",
                        "resolution_notes": (
                            "Synthetic processor replacement test."
                        )
                    }
                )


        # STEP 7C: CHECK THE WEB RESPONSE.
        assert response.status_code == 200

        # STEP 7D: VERIFY DATABASE CHANGES.
        verify_records(connection, controller_id, event_id)

    finally:
        # STEP 7E: REMOVE THE SYNTHETIC RECORDS.
        if controller_id is not None:
            cleanup(connection, controller_id)
            print("PASS: Synthetic test records removed.")

        connection.close()


# STEP 8: EXECUTE THE TEST.
if __name__ == "__main__":
    main()
