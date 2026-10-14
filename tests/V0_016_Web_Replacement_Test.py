
# ==========================================================
# TRACE - WEB REPLACEMENT WORKFLOW TEST
# Creates a fictional controller and pending warning.
# Does not connect to or modify a physical PLC.
# ==========================================================

# STEP 1: IMPORT REQUIRED LIBRARIES.
import uuid
import pyodbc


# STEP 2: CONFIGURE THE TRACE DATABASE CONNECTION.
SQL_CONNECTION = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


# STEP 3: GENERATE UNIQUE SYNTHETIC IDENTIFIERS.
test_id = uuid.uuid4().hex[:12]

test_name = f"TRACE_WEB_TEST_{test_id}"
test_ip = "127.0.0.2"
old_serial = f"TRACE_WEB_OLD_{test_id}"
new_serial = f"TRACE_WEB_NEW_{test_id}"


# STEP 4: CREATE THE SYNTHETIC TEST RECORDS.
def main():

    connection = pyodbc.connect(
        SQL_CONNECTION,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 4A: REGISTER FICTIONAL EQUIPMENT.
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
                ?, ?, '1769-L30ER/A',
                'CompactLogix', 30, 11, ?,
                'Not checked'
            )
        """, test_name, test_ip, old_serial)

        controller_id = cursor.fetchone()[0]

        # STEP 4B: REGISTER ITS FICTIONAL ORIGINAL PROCESSOR.
        cursor.execute("""
            INSERT INTO dbo.ControllerHardware (
                ControllerID,
                SerialNumber,
                PLCModel,
                FirmwareMajor,
                FirmwareMinor
            )
            VALUES (?, ?, '1769-L30ER/A', 30, 11)
        """, controller_id, old_serial)

        # STEP 4C: RECORD A FICTIONAL REPLACEMENT WARNING.
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
        """, controller_id, new_serial, test_ip)

        event_id = cursor.fetchone()[0]

        # STEP 4D: SAVE THE SYNTHETIC RECORDS.
        connection.commit()

        print("Synthetic web test created.")
        print("Controller ID:", controller_id)
        print("Event ID:", event_id)
        print("Controller Name:", test_name)
        print("No physical PLC was contacted.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 5: EXECUTE THE TEST.
if __name__ == "__main__":
    main()
