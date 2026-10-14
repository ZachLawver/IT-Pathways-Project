
# ==========================================================
# TRACE - PROCESSOR REPLACEMENT CONFIRMATION TEST
# VERSION 0.015
#
# Uses a fictional controller and synthetic hardware.
# Does not communicate with a physical PLC.
# Creates and removes temporary SQL test records.
# ==========================================================

# STEP 1: IMPORT REQUIRED LIBRARIES.
import importlib.util
import uuid
from pathlib import Path
from unittest.mock import patch

import pyodbc


# STEP 2: LOAD THE EXISTING ETHERNET MONITOR.
monitor_path = (
    Path(__file__).resolve().parent
    / "V0.014_Ethernet_Monitor.py"
)

spec = importlib.util.spec_from_file_location(
    "trace_ethernet_monitor",
    monitor_path
)

monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


# STEP 3: CONFIGURE THE SYNTHETIC TEST.
# Use a unique loopback address and serial numbers.
# No network communication will occur.

test_id = uuid.uuid4().hex[:12]

test_name = f"TRACE_TEST_{test_id}"
test_ip = "127.0.0.2"

old_serial = f"TRACE_OLD_{test_id}"
new_serial = f"TRACE_NEW_{test_id}"

test_identity = {
    "ip_address": test_ip,
    "controller_name": "Synthetic Replacement Processor",
    "plc_model": "1769-L30ER/A",
    "controller_family": "CompactLogix",
    "firmware_major": 30,
    "firmware_minor": 11,
    "serial_number": new_serial,
}

controller_id = None
event_id = None


# STEP 4: CREATE TEMPORARY EQUIPMENT AND HARDWARE.
def create_test_records():

    connection = pyodbc.connect(
        monitor.SQL_CONNECTION,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 4A: CREATE A FICTIONAL EQUIPMENT INSTALLATION.
        cursor.execute("""
            INSERT INTO dbo.Controllers (
                ControllerName,
                IPAddress,
                PLCModel,
                ControllerFamily,
                FirmwareMajor,
                FirmwareMinor,
                SerialNumber,
                CommunicationStatus
            )
            OUTPUT INSERTED.ControllerID
            VALUES (
                ?, ?, ?, 'CompactLogix',
                30, 11, ?, 'Not checked'
            )
        """,
            test_name,
            test_ip,
            "1769-L30ER/A",
            old_serial
        )

        created_controller_id = cursor.fetchone()[0]

        # STEP 4B: REGISTER THE ORIGINAL PROCESSOR.
        cursor.execute("""
            INSERT INTO dbo.ControllerHardware (
                ControllerID,
                SerialNumber,
                PLCModel,
                FirmwareMajor,
                FirmwareMinor
            )
            VALUES (?, ?, ?, 30, 11)
        """,
            created_controller_id,
            old_serial,
            "1769-L30ER/A"
        )

        # STEP 4C: CREATE A PENDING REPLACEMENT WARNING.
        cursor.execute("""
            INSERT INTO dbo.HardwareEvents (
                ControllerID,
                EventType,
                DetectedSerialNumber,
                DetectedIPAddress,
                EventStatus
            )
            OUTPUT INSERTED.EventID
            VALUES (
                ?, 'PossibleReplacement',
                ?, ?, 'Pending'
            )
        """,
            created_controller_id,
            new_serial,
            test_ip
        )

        created_event_id = cursor.fetchone()[0]

        connection.commit()

        return created_controller_id, created_event_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 5: VERIFY THE REPLACEMENT RESULTS.
def verify_results(expected_controller_id, expected_event_id):

    connection = pyodbc.connect(
        monitor.SQL_CONNECTION,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 5A: VERIFY THE EQUIPMENT IDENTITY IS UNCHANGED.
        cursor.execute("""
            SELECT ControllerName, SerialNumber
            FROM dbo.Controllers
            WHERE ControllerID = ?
        """, expected_controller_id)

        controller = cursor.fetchone()

        assert controller is not None
        assert controller[0] == test_name
        assert controller[1] == new_serial

        # STEP 5B: VERIFY THE OLD PROCESSOR WAS RETIRED.
        cursor.execute("""
            SELECT RemovedAt
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
        """, expected_controller_id, old_serial)

        old_hardware = cursor.fetchone()

        assert old_hardware is not None
        assert old_hardware[0] is not None

        # STEP 5C: VERIFY THE REPLACEMENT IS ACTIVE.
        cursor.execute("""
            SELECT RemovedAt
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
        """, expected_controller_id, new_serial)

        new_hardware = cursor.fetchone()

        assert new_hardware is not None
        assert new_hardware[0] is None

        # STEP 5D: VERIFY THE EVENT WAS RESOLVED.
        cursor.execute("""
            SELECT EventStatus, ResolvedAt
            FROM dbo.HardwareEvents
            WHERE EventID = ?
        """, expected_event_id)

        event = cursor.fetchone()

        assert event is not None
        assert event[0] == "Confirmed"
        assert event[1] is not None

        # STEP 5E: VERIFY ONLY ONE PROCESSOR IS ACTIVE.
        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND RemovedAt IS NULL
        """, expected_controller_id)

        assert cursor.fetchone()[0] == 1

        print("PASS: Equipment identity preserved.")
        print("PASS: Original processor retired.")
        print("PASS: Replacement processor active.")
        print("PASS: Hardware event confirmed.")
        print("PASS: Exactly one active processor.")

    finally:
        connection.close()


# STEP 6: REMOVE ONLY THE SYNTHETIC TEST RECORDS.
def cleanup_test_records():

    if controller_id is None:
        return

    connection = pyodbc.connect(
        monitor.SQL_CONNECTION,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 6A: DELETE THE TEST EVENT FIRST.
        cursor.execute("""
            DELETE FROM dbo.HardwareEvents
            WHERE ControllerID = ?
              AND ControllerID IN (
                  SELECT ControllerID
                  FROM dbo.Controllers
                  WHERE ControllerName = ?
              )
        """, controller_id, test_name)

        # STEP 6B: DELETE THE TEST HARDWARE HISTORY.
        cursor.execute("""
            DELETE FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND ControllerID IN (
                  SELECT ControllerID
                  FROM dbo.Controllers
                  WHERE ControllerName = ?
              )
        """, controller_id, test_name)

        # STEP 6C: DELETE THE TEST EQUIPMENT.
        cursor.execute("""
            DELETE FROM dbo.Controllers
            WHERE ControllerID = ?
              AND ControllerName = ?
        """, controller_id, test_name)

        connection.commit()

        print("PASS: Synthetic SQL records removed.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 7: RUN THE ISOLATED CONFIRMATION TEST.
def main():

    global controller_id, event_id

    try:
        # STEP 7A: CREATE THE SYNTHETIC SQL RECORDS.
        controller_id, event_id = create_test_records()

        print("Synthetic equipment created.")
        print("Test ControllerID:", controller_id)

        # STEP 7B: REPLACE THE LIVE CIP IDENTITY FUNCTION.
        # This prevents any physical PLC connection.
        # The real confirmation SQL logic still executes.

        with patch.object(
            monitor,
            "identify_controller",
            return_value=test_identity
        ):
            result = monitor.confirm_hardware_replacement(event_id)

        assert result == controller_id

        # STEP 7C: VERIFY THE SQL RESULTS.
        verify_results(controller_id, event_id)

    finally:
        # STEP 7D: CLEAN UP EVEN IF THE TEST FAILS.
        cleanup_test_records()


# STEP 8: EXECUTE THE TEST.
if __name__ == "__main__":
    main()
