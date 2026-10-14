
# ==========================================================
# TRACE V0.018 - PROCESSOR REPLACEMENT SAFETY TEST
#
# Tests three failure scenarios:
# 1. Incorrect physical processor identity.
# 2. Processor with previous installation history.
# 3. SQL failure after the original processor is retired.
#
# Uses synthetic SQL records and mocked PLC responses.
# Does not communicate with physical PLC equipment.
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
    "trace_safety_monitor",
    monitor_path
)

monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


# STEP 3: PREPARE UNIQUE SYNTHETIC IDENTIFIERS.
test_id = uuid.uuid4().hex[:12]

test_name = f"TRACE_SAFETY_{test_id}"
test_ip = "127.0.0.4"

old_serial = f"TRACE_SAFETY_OLD_{test_id}"
new_serial = f"TRACE_SAFETY_NEW_{test_id}"
wrong_serial = f"TRACE_SAFETY_WRONG_{test_id}"

controller_id = None
event_id = None

identity = {
    "ip_address": test_ip,
    "controller_name": test_name,
    "plc_model": "1769-L30ER/A",
    "controller_family": "CompactLogix",
    "firmware_major": 30,
    "firmware_minor": 11,
    "serial_number": new_serial,
}


# STEP 4: CREATE SYNTHETIC EQUIPMENT AND WARNING.
def setup_test():

    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        # STEP 4A: CREATE THE EQUIPMENT RECORD.
        cursor.execute("""
            INSERT INTO dbo.Controllers (
                ControllerName, IPAddress, PLCModel,
                ControllerFamily, FirmwareMajor,
                FirmwareMinor, SerialNumber
            )
            OUTPUT INSERTED.ControllerID
            VALUES (?, ?, ?, 'CompactLogix', 30, 11, ?)
        """, test_name, test_ip, "1769-L30ER/A", old_serial)

        new_controller_id = cursor.fetchone()[0]

        # STEP 4B: REGISTER THE ORIGINAL PROCESSOR.
        cursor.execute("""
            INSERT INTO dbo.ControllerHardware (
                ControllerID, SerialNumber, PLCModel,
                FirmwareMajor, FirmwareMinor
            )
            VALUES (?, ?, '1769-L30ER/A', 30, 11)
        """, new_controller_id, old_serial)

        # STEP 4C: CREATE THE PENDING REPLACEMENT EVENT.
        cursor.execute("""
            INSERT INTO dbo.HardwareEvents (
                ControllerID, EventType,
                DetectedSerialNumber, DetectedIPAddress,
                EventStatus
            )
            OUTPUT INSERTED.EventID
            VALUES (?, 'PossibleReplacement', ?, ?, 'Pending')
        """, new_controller_id, new_serial, test_ip)

        new_event_id = cursor.fetchone()[0]

        connection.commit()
        return new_controller_id, new_event_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 5: VERIFY THAT REJECTED CONFIRMATIONS
# DO NOT MODIFY THE EXISTING EQUIPMENT RECORDS.
def verify_unchanged():

    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        # STEP 5A: ORIGINAL PROCESSOR MUST REMAIN ACTIVE.
        cursor.execute("""
            SELECT RemovedAt
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
        """, controller_id, old_serial)

        original = cursor.fetchone()
        assert original is not None
        assert original[0] is None

        # STEP 5B: REPLACEMENT MUST NOT BE ACTIVE.
        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
        """, controller_id, new_serial)

        assert cursor.fetchone()[0] == 0

        # STEP 5C: WARNING MUST STILL BE PENDING.
        cursor.execute("""
            SELECT EventStatus
            FROM dbo.HardwareEvents
            WHERE EventID = ?
        """, event_id)

        assert cursor.fetchone()[0] == "Pending"

        # STEP 5D: EQUIPMENT IDENTITY MUST BE UNCHANGED.
        cursor.execute("""
            SELECT ControllerName, SerialNumber
            FROM dbo.Controllers
            WHERE ControllerID = ?
        """, controller_id)

        equipment = cursor.fetchone()

        assert equipment[0] == test_name
        assert equipment[1] == old_serial

    finally:
        connection.close()


# STEP 6: TEST INCORRECT PROCESSOR IDENTITY.
def test_wrong_identity():

    wrong_identity = dict(identity)
    wrong_identity["serial_number"] = wrong_serial

    # STEP 6A: SIMULATE A DIFFERENT PROCESSOR.
    with patch.object(
        monitor,
        "identify_controller",
        return_value=wrong_identity
    ):
        try:
            monitor.confirm_hardware_replacement(event_id)
            raise AssertionError(
                "TRACE incorrectly accepted the wrong processor."
            )
        except ValueError as error:
            assert "verification failed" in str(error).lower()

    # STEP 6B: VERIFY THE DATABASE IS UNCHANGED.
    verify_unchanged()
    print("PASS: Incorrect processor identity rejected.")


# STEP 7: TEST PREVIOUSLY REGISTERED HARDWARE.
def test_historical_processor():

    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        # STEP 7A: ADD A RETIRED INSTALLATION HISTORY
        # FOR THE PROPOSED REPLACEMENT PROCESSOR.
        cursor.execute("""
            INSERT INTO dbo.ControllerHardware (
                ControllerID, SerialNumber, PLCModel,
                FirmwareMajor, FirmwareMinor, RemovedAt
            )
            VALUES (
                ?, ?, '1769-L30ER/A',
                30, 11, SYSUTCDATETIME()
            )
        """, controller_id, new_serial)

        connection.commit()

    finally:
        connection.close()

    # STEP 7B: SIMULATE THE EXPECTED REPLACEMENT.
    with patch.object(
        monitor,
        "identify_controller",
        return_value=identity
    ):
        try:
            monitor.confirm_hardware_replacement(event_id)
            raise AssertionError(
                "TRACE incorrectly accepted historical hardware."
            )
        except ValueError as error:
            assert "installation history" in str(error).lower()

    # STEP 7C: VERIFY THE ORIGINAL REMAINS ACTIVE.
    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT RemovedAt
            FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
        """, controller_id, old_serial)

        assert cursor.fetchone()[0] is None

        # STEP 7D: REMOVE THE RETIRED TEST HISTORY
        # BEFORE THE NEXT TEST.
        cursor.execute("""
            DELETE FROM dbo.ControllerHardware
            WHERE ControllerID = ?
              AND SerialNumber = ?
              AND RemovedAt IS NOT NULL
        """, controller_id, new_serial)

        connection.commit()

    finally:
        connection.close()

    verify_unchanged()
    print("PASS: Previously registered processor rejected.")


# STEP 8: TEST SQL TRANSACTION ROLLBACK.
def test_transaction_rollback():

    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        # STEP 8A: CREATE A TEMPORARY SQL TRIGGER.
        # The trigger deliberately blocks the new
        # hardware INSERT after the old processor
        # has already been marked as removed.
        #
        # This trigger is scoped to the synthetic serial.

        trigger_name = f"TRACE_TestRollback_{test_id}"

        cursor.execute(f"""
            CREATE TRIGGER dbo.{trigger_name}
            ON dbo.ControllerHardware
            AFTER INSERT
            AS
            BEGIN
                SET NOCOUNT ON;

                IF EXISTS (
                    SELECT 1
                    FROM inserted
                    WHERE SerialNumber = '{new_serial}'
                )
                BEGIN
                    THROW 51000,
                        'Synthetic rollback test failure',
                        1;
                END
            END
        """)

        connection.commit()

    finally:
        connection.close()

    try:
        # STEP 8B: ATTEMPT THE REPLACEMENT.
        # The trigger must cause SQL to reject it.
        with patch.object(
            monitor,
            "identify_controller",
            return_value=identity
        ):
            try:
                monitor.confirm_hardware_replacement(event_id)
                raise AssertionError(
                    "TRACE failed to roll back the transaction."
                )
            except pyodbc.Error:
                pass

        # STEP 8C: VERIFY THE ORIGINAL IS STILL ACTIVE.
        verify_unchanged()
        print("PASS: SQL transaction rolled back correctly.")

    finally:
        # STEP 8D: REMOVE THE TEMPORARY TRIGGER.
        connection = pyodbc.connect(monitor.SQL_CONNECTION)

        try:
            cursor = connection.cursor()

            cursor.execute(
                f"DROP TRIGGER IF EXISTS dbo.{trigger_name}"
            )

            connection.commit()

        finally:
            connection.close()


# STEP 9: CLEAN UP SYNTHETIC TEST RECORDS.
def cleanup():

    if controller_id is None:
        return

    connection = pyodbc.connect(monitor.SQL_CONNECTION)

    try:
        cursor = connection.cursor()

        # STEP 9A: DELETE ONLY THE SYNTHETIC EVENT.
        cursor.execute("""
            DELETE FROM dbo.HardwareEvents
            WHERE ControllerID = ?
        """, controller_id)

        # STEP 9B: DELETE ONLY SYNTHETIC HARDWARE.
        cursor.execute("""
            DELETE FROM dbo.ControllerHardware
            WHERE ControllerID = ?
        """, controller_id)

        # STEP 9C: DELETE ONLY SYNTHETIC EQUIPMENT.
        cursor.execute("""
            DELETE FROM dbo.Controllers
            WHERE ControllerID = ?
              AND ControllerName = ?
        """, controller_id, test_name)

        connection.commit()
        print("PASS: Synthetic safety records removed.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 10: RUN ALL THREE SAFETY TESTS.
def main():

    global controller_id, event_id

    try:
        controller_id, event_id = setup_test()

        test_wrong_identity()
        test_historical_processor()
        test_transaction_rollback()

    finally:
        cleanup()


# STEP 11: EXECUTE THE TEST SUITE.
if __name__ == "__main__":
    main()
