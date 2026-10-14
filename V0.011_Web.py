# STEP 1: IMPORT FLASK WEB AND SESSION FEATURES.
from flask import Flask, render_template, request, session
import pyodbc

# STEP 1A: IMPORT SUPPORT FOR PROJECT FILE UPLOADS.
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util

# DEMO STEP 20A: IMPORT PLC AUDIT READER DEPENDENCIES.
from pycomm3 import CIPDriver
import struct

# STEP 1B: IMPORT THE LIVE ETHERNET CONTROLLER MONITOR.
ethernet_module_path = Path(__file__).resolve().parent / "V0.014_Ethernet_Monitor.py"

ethernet_spec = importlib.util.spec_from_file_location(
    "trace_ethernet_monitor",
    ethernet_module_path
)

ethernet_monitor = importlib.util.module_from_spec(ethernet_spec)
ethernet_spec.loader.exec_module(ethernet_monitor)
# STEP 2: CONFIGURE TRACE.
app = Flask(__name__)

# STEP 2A: CONFIGURE SESSION SECURITY.
# Flask signs session data so the browser cannot modify it unnoticed.
# Generate a new secret when Flask starts.
import secrets

app.secret_key = secrets.token_hex(32)

# STEP 2A: LIMIT UPLOADED PLC PROJECT FILES TO 20 MB.
# Prevents excessively large uploads from being processed.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

# STEP 2B: CONFIGURE THE SQL SERVER CONNECTION.
connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)
# STEP 2A: LOAD TRACE'S EXISTING CONTROLLER IDENTIFICATION MODULE.
# This allows Flask to reuse the parser without changing its filename.

module_path = Path(__file__).resolve().parent / "V0.012_Controller_ID.py"

spec = importlib.util.spec_from_file_location(
    "trace_controller_id",
    module_path
)

controller_id_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller_id_module)

# STEP 208: LOAD TRACE'S BACKUP MANAGER.
# Reuse the existing backup-history functions.

backup_module_path = (
    Path(__file__).resolve().parent / "V0_019_Backup_Manager.py"
)

backup_spec = importlib.util.spec_from_file_location(
    "trace_backup_manager",
    backup_module_path,
)

backup_manager = importlib.util.module_from_spec(backup_spec)
backup_spec.loader.exec_module(backup_manager)

# STEP 3: RETRIEVE DASHBOARD INFORMATION FROM SQL SERVER.
def get_dashboard_data():
    connection = pyodbc.connect(connection_string, timeout=5)

    try:
        cursor = connection.cursor()

        # Count registered controllers.
        cursor.execute("SELECT COUNT(*) FROM dbo.Controllers")
        controller_count = cursor.fetchone()[0]

        # Count recorded rung changes.
        cursor.execute("SELECT COUNT(*) FROM dbo.RungChanges")
        change_count = cursor.fetchone()[0]

        # Count registered backup records.
        cursor.execute("SELECT COUNT(*) FROM dbo.Backups")
        backup_count = cursor.fetchone()[0]

        return {
            "controllers": controller_count,
            "changes": change_count,
            "backups": backup_count
        }

    finally:
        connection.close()
        
# STEP 4: DISPLAY THE DASHBOARD.
@app.route("/")
def dashboard():
    data = get_dashboard_data()
    return render_template("dashboard.html", data=data)

  # STEP 5: DISPLAY CONTROLLERS AND HANDLE IDENTIFICATION OR REGISTRATION.
@app.route("/controllers", methods=["GET", "POST"])
def controllers():

    # STEP 5A: PREPARE PAGE RESULTS.
    metadata = None
    error_message = None
    success_message = None

    # STEP 5B: HANDLE FORM SUBMISSIONS.
    if request.method == "POST":

        action = request.form.get("action")

        # STEP 5C: IDENTIFY A CONTROLLER WITHOUT MODIFYING SQL.
        if action == "identify":

            # Remove any previously identified controller.
            session.pop("identified_controller", None)

            uploaded_file = request.files.get("project_file")

            if uploaded_file is None or not uploaded_file.filename:
                error_message = "Please select an L5X project file."

            elif Path(uploaded_file.filename).suffix.lower() != ".l5x":
                error_message = "Only L5X files are supported."

            else:
                try:
                    # STEP 5D: PROCESS THE UPLOAD IN A TEMPORARY DIRECTORY.
                    with TemporaryDirectory(prefix="trace_upload_") as temp_dir:
                        project_path = Path(temp_dir) / "controller.l5x"
                        uploaded_file.save(project_path)

                        metadata = controller_id_module.identify_controller(
                            project_path
                        )

                    # STEP 5E: REMEMBER THE IDENTIFIED METADATA.
                    # Flask signs the session cookie to protect integrity.
                    session["identified_controller"] = metadata

                except (ValueError, OSError) as error:
                    error_message = f"Unable to identify controller: {error}"

                except Exception:
                    app.logger.exception("Controller identification failed")
                    error_message = "Controller identification failed."

        # STEP 5F: REGISTER A PREVIOUSLY IDENTIFIED CONTROLLER.
        elif action == "register":

            metadata = session.get("identified_controller")

            if not metadata:
                error_message = "Identify a controller before registering it."

            else:
                try:
                    # STEP 5G: REUSE THE EXISTING SQL REGISTRATION FUNCTION.
                    result, controller_id = controller_id_module.save_controller(
                        metadata
                    )

                    success_message = (
                        f"{result} controller '{metadata['name']}' "
                        f"with Controller ID {controller_id}."
                    )

                    # STEP 5H: CLEAR THE SESSION AFTER SUCCESS.
                    session.pop("identified_controller", None)
                    metadata = None

                except Exception:
                    app.logger.exception("Controller registration failed")
                    error_message = "Controller registration failed. Check the server log."
                
        # STEP 5K: SCAN AND AUTOMATICALLY REGISTER A LIVE PLC.
        elif action == "scan":

            ip_address = request.form.get("ip_address", "").strip()

            if not ip_address:
                error_message = "Enter a controller IP address."

            else:
                try:
                    # STEP 5L: IDENTIFY THE PLC OVER ETHERNET/IP.
                    identity = ethernet_monitor.identify_controller(ip_address)

                    # STEP 5M: REGISTER OR UPDATE ITS SQL RECORD.
                    controller_id, result = ethernet_monitor.register_controller(
                        identity
                    )

                    success_message = (
                        f"Controller successfully {result}. "
                        f"Controller ID: {controller_id}. "
                        "You can now assign it a friendly name."
                    )

                except Exception:
                    app.logger.exception("Ethernet controller scan failed")
                    error_message = (
                        "Unable to scan or register the controller. "
                        "Check its IP address and the server log."
                    )

        # STEP 5N: CHANGE A CONTROLLER'S FRIENDLY NAME.
        elif action == "rename":

            controller_id = request.form.get("controller_id", "").strip()
            new_name = request.form.get("controller_name", "").strip()

            if not controller_id.isdigit() or not new_name:
                error_message = "Select a controller and enter a name."

            elif len(new_name) > 255:
                error_message = "Controller names must be 255 characters or fewer."

            else:
                connection = None

                try:
                    # STEP 5O: UPDATE ONLY THE DISPLAY NAME.
                    # ControllerID, serial number, and history remain unchanged.
                    connection = pyodbc.connect(connection_string, timeout=5)
                    cursor = connection.cursor()
                    # STEP 348: CAPTURE THE OLD NAME BEFORE RENAMING.
                    cursor.execute(
                        "SELECT ControllerName FROM dbo.Controllers WHERE ControllerID = ?",
                        int(controller_id)
                    )

                    old_record = cursor.fetchone()
                    old_name = old_record[0] if old_record else None

                    cursor.execute("""
                        UPDATE dbo.Controllers
                        SET ControllerName = ?
                        WHERE ControllerID = ?
                    """, new_name, int(controller_id))

                    if cursor.rowcount != 1:
                        connection.rollback()
                        error_message = "Controller not found."

                    else:
                        # STEP 348: RENAME THE CONTROLLER BACKUP FOLDER.
                        backup_root = Path(r"C:\TRACE_Backups")

                        if old_name and old_name != new_name:
                            old_folder = backup_root / old_name
                            new_folder = backup_root / new_name

                            if old_folder.exists():
                                if new_folder.exists():
                                    raise FileExistsError(
                                        f"Backup folder already exists: {new_folder}"
                                    )

                                old_folder.rename(new_folder)

                        connection.commit()

                        success_message = (
                            f"Controller renamed to '{new_name}'. "
                            "Backup folder updated."
                        )

                except pyodbc.IntegrityError:
                    if connection:
                        connection.rollback()
                    error_message = "That controller name is already in use."

                except Exception:
                    if connection:
                        connection.rollback()
                    app.logger.exception("Controller rename failed")
                    error_message = "Unable to rename controller."

                finally:
                    if connection:
                        connection.close()


        # STEP 5R: CONFIRM A PROCESSOR REPLACEMENT.
        elif action == "confirm_replacement":

            # STEP 5R-1: VALIDATE THE SELECTED EVENT.
            event_id = request.form.get("event_id", "").strip()

            if not event_id.isdigit() or int(event_id) <= 0:
                error_message = "Invalid hardware event."

            else:
                try:
                    
                    # STEP 5R-2: COLLECT TECHNICIAN INFORMATION.
                    technician_name = request.form.get(
                        "technician_name", ""
                    ).strip()

                    resolution_notes = request.form.get(
                        "resolution_notes", ""
                    ).strip()

                    # STEP 5R-2: REVERIFY THE PHYSICAL PLC.
                    # The monitor checks the connected processor
                    # and performs the SQL updates transactionally.
                    
                    # STEP 5R-3: VERIFY THE PROCESSOR AND
                    # SAVE THE TECHNICIAN'S RESOLUTION.
                    controller_id = (
                        ethernet_monitor.confirm_hardware_replacement(
                            int(event_id),
                            technician_name,
                            resolution_notes
                        )
                    )


                    success_message = (
                        "Processor replacement confirmed for "
                        f"Controller ID {controller_id}."
                    )

                except ValueError as error:
                    error_message = str(error)

                except Exception:
                    app.logger.exception(
                        "Processor replacement confirmation failed"
                    )
                    error_message = (
                        "Unable to confirm processor replacement. "
                        "Check the server log."
                    )

        # STEP 5S: DISMISS A HARDWARE REPLACEMENT WARNING.
        elif action == "dismiss_replacement":

            # STEP 5S-1: VALIDATE THE SELECTED EVENT.
            event_id = request.form.get("event_id", "").strip()

            if not event_id.isdigit() or int(event_id) <= 0:
                error_message = "Invalid hardware event."

            else:
                
                # STEP 5S-2: COLLECT AND VALIDATE
                # TECHNICIAN ATTRIBUTION AND NOTES.
                technician_name = request.form.get(
                    "technician_name", ""
                ).strip()

                resolution_notes = request.form.get(
                    "resolution_notes", ""
                ).strip()

                if (
                    not technician_name
                    or len(technician_name) > 150
                    or not resolution_notes
                    or len(resolution_notes) > 1000
                ):
                    error_message = (
                        "Enter a technician name and maintenance "
                        "notes within the permitted lengths."
                    )

                connection = None

                if error_message is None:
                    try:
                        # STEP 5S-2: OPEN A DATABASE TRANSACTION.
                        connection = pyodbc.connect(
                            connection_string,
                            timeout=5
                        )
                        cursor = connection.cursor()

                        
                        # STEP 5S-3: RECORD THE DISMISSAL.
                        cursor.execute("""
                            UPDATE dbo.HardwareEvents
                            SET EventStatus = 'Dismissed',
                                ResolvedAt = SYSUTCDATETIME(),
                                ResolvedBy = ?,
                                ResolutionNotes = ?
                            WHERE EventID = ?
                              AND EventType = 'PossibleReplacement'
                              AND EventStatus = 'Pending'
                        """,
                            technician_name,
                            resolution_notes,
                            int(event_id)
                        )

                        if cursor.rowcount != 1:
                            raise ValueError(
                                "This warning is no longer pending."
                            )

                        # STEP 5S-4: PRESERVE THE EVENT HISTORY.
                        connection.commit()
                        success_message = (
                            "Hardware replacement warning dismissed."
                        )

                    except ValueError as error:
                        if connection:
                            connection.rollback()
                        error_message = str(error)

                    except Exception:
                        if connection:
                            connection.rollback()
                        app.logger.exception(
                            "Hardware warning dismissal failed"
                        )
                        error_message = (
                            "Unable to dismiss hardware warning."
                        )

                    finally:
                        if connection:
                            connection.close()

        else:
            error_message = "Unknown controller action."

    # STEP 5I: KEEP THE CURRENT IDENTIFICATION VISIBLE ON PAGE REFRESH.
    if metadata is None and not success_message:
        metadata = session.get("identified_controller")

   
    # STEP 5J: LOAD THE UPDATED SQL INVENTORY.
    controller_list = get_controllers()

    # STEP 5P: LOAD PENDING PROCESSOR REPLACEMENT WARNINGS.
    pending_hardware_events = get_pending_hardware_events()
   
    # STEP 5Q: RENDER CONTROLLERS AND HARDWARE WARNINGS.
    return render_template(
        "controllers.html",
        controllers=controller_list,
        metadata=metadata,
        error_message=error_message,
        success_message=success_message,
        pending_hardware_events=pending_hardware_events
    )


# STEP 6: RETRIEVE CONTROLLER INVENTORY AND MONITORING INFORMATION.
def get_controllers():
    connection = pyodbc.connect(connection_string, timeout=5)

    try:
        cursor = connection.cursor()

        # STEP 6A: RETRIEVE DISPLAY FIELDS ONLY.
        # Hardware serial numbers remain internal to TRACE.
                # STEP 435: INCLUDE INITIAL AUDIT REGISTRATION STATUS.
        cursor.execute("""
            SELECT
                c.ControllerID,
                c.ControllerName,
                c.IPAddress,
                c.PLCModel,
                c.FirmwareMajor,
                c.FirmwareMinor,
                c.CommunicationStatus,
                c.LastSeen,

                CAST(
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM dbo.ControllerHardware AS h
                            WHERE h.ControllerID = c.ControllerID
                              AND h.RemovedAt IS NULL
                              AND h.InitialAuditValue IS NOT NULL
                        )
                        THEN 1
                        ELSE 0
                    END
                AS BIT) AS IsRegistered

            FROM dbo.Controllers AS c
            ORDER BY c.ControllerName
        """)

        # STEP 6B: CONVERT SQL RESULTS TO NAMED DICTIONARIES.
        columns = [column[0] for column in cursor.description]

        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()


# STEP 7: RETRIEVE PENDING HARDWARE REPLACEMENT EVENTS.
# Only display information technicians need for review.
# Hardware serial numbers remain internal to TRACE.

def get_pending_hardware_events():

    # STEP 7A: CONNECT TO THE TRACE DATABASE.
    connection = pyodbc.connect(
        connection_string,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 7B: RETRIEVE UNRESOLVED REPLACEMENT WARNINGS.
        # Join to Controllers to display the friendly name.

        cursor.execute("""
            SELECT
                h.EventID,
                h.ControllerID,
                c.ControllerName,
                h.EventType,
                h.DetectedIPAddress,
                h.EventStatus,
                h.DetectedAt
            FROM dbo.HardwareEvents AS h
            INNER JOIN dbo.Controllers AS c
                ON h.ControllerID = c.ControllerID
            WHERE h.EventStatus = 'Pending'
              AND h.EventType = 'PossibleReplacement'
            ORDER BY h.DetectedAt DESC
        """)

        # STEP 7C: CONVERT RESULTS INTO DICTIONARIES.
        columns = [
            column[0]
            for column in cursor.description
        ]

        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()


# SECTION 1: BACKUP MANAGEMENT PAGE
# STEP 215: LOAD BACKUP HISTORY FOR A SELECTED CONTROLLER.
@app.route("/backups")
def backups():

    # STEP 215A: LOAD ALL REGISTERED CONTROLLERS.
    controller_list = get_controllers()

    # STEP 215B: READ THE SELECTED CONTROLLER ID.
    selected_id = request.args.get("controller_id", type=int)

    # STEP 215C: DEFAULT TO THE FIRST REGISTERED CONTROLLER.
    if selected_id is None and controller_list:
        selected_id = controller_list[0]["ControllerID"]

    # STEP 215D: ONLY ACCEPT REGISTERED CONTROLLER IDS.
    valid_ids = {
        controller["ControllerID"]
        for controller in controller_list
    }

    if selected_id not in valid_ids:
        selected_id = None

    # STEP 215E: RETRIEVE THE SELECTED CONTROLLER'S BACKUPS.
    backup_history = []

    if selected_id is not None:
        backup_history = backup_manager.get_controller_backup_history(
            selected_id
        )

    # STEP 215F: PASS CONTROLLERS AND HISTORY TO THE TEMPLATE.
    return render_template(
        "backups.html",
        controllers=controller_list,
        selected_controller_id=selected_id,
        backup_history=backup_history,
    )

# SECTION 2: AUDIT AND COMPARISON PAGE
@app.route("/audit")
def audit():
    return render_template("audit.html")

# DEMO STEP 20B: READ LIVE CONTROLLER AUDIT VALUE.
# Read-only CIP request. Does not write to the PLC.

def read_demo_audit_value(plc_ip):
    with CIPDriver(plc_ip) as plc:
        response = plc.generic_message(
            service=0x0E,
            class_code=0x8E,
            instance=1,
            attribute=0x1B,
            connected=True,
            name="TRACE Demo Audit Value"
        )

        if not response:
            raise RuntimeError(
                f"PLC audit read failed: {response.error}"
            )

        if not isinstance(response.value, bytes) or len(response.value) != 8:
            raise ValueError("Unexpected PLC audit response")

        low, high = struct.unpack("<II", response.value)

        return f"{high:08X}{low:08X}"

# DEMO STEP 26: REGISTER INITIAL AUDIT VALUE.
# Associates the Audit Value with the physical PLC serial number.
# Refuses to overwrite an existing registration.
# PLC communication is read-only.

def register_demo_initial_audit(controller_id):

    # STEP 41A: GET THE SELECTED PLC FROM SQL SERVER.
    selected_controller = get_demo_selected_controller(controller_id)
    plc_ip = selected_controller["ip_address"]

    # STEP 26A: READ THE PHYSICAL PLC SERIAL NUMBER.
    from pycomm3 import LogixDriver

    with LogixDriver(plc_ip) as plc:
        info = plc.get_plc_info()
        serial_number = str(info["serial"]).lower()

    # STEP 26B: READ THE CURRENT AUDIT VALUE.
    audit_value = read_demo_audit_value(plc_ip)

    # STEP 26C: OPEN TRACE'S EXISTING DATABASE.
    connection = pyodbc.connect(connection_string, timeout=5)

    try:
        cursor = connection.cursor()

        # STEP 26D: REGISTER ONLY THE MATCHING ACTIVE PROCESSOR.
        # The initial value cannot be overwritten by this operation.
        cursor.execute("""
            UPDATE h
            SET
                InitialAuditValue = ?,
                AuditRegisteredAt = SYSUTCDATETIME()
            FROM dbo.ControllerHardware AS h
            INNER JOIN dbo.Controllers AS c
                ON c.ControllerID = h.ControllerID
            WHERE h.SerialNumber = ?
              AND c.IPAddress = ?
              AND h.RemovedAt IS NULL
              AND h.InitialAuditValue IS NULL
        """, audit_value, serial_number, plc_ip)

                # DEMO STEP 30: HANDLE AN ALREADY REGISTERED PLC.
        if cursor.rowcount != 1:

            cursor.execute("""
                SELECT c.ControllerName, h.InitialAuditValue
                FROM dbo.ControllerHardware AS h
                INNER JOIN dbo.Controllers AS c
                    ON c.ControllerID = h.ControllerID
                WHERE h.SerialNumber = ?
                  AND c.IPAddress = ?
                  AND h.RemovedAt IS NULL
            """, serial_number, plc_ip)

            existing = cursor.fetchone()

            connection.rollback()

            if existing is None:
                raise RuntimeError(
                    "PLC not found in TRACE's active hardware records. "
                    f"Live serial number: {serial_number}"
                )

            if existing.InitialAuditValue is not None:
                return (
                    existing.ControllerName,
                    serial_number,
                    existing.InitialAuditValue,
                    "already_registered"
                )

            raise RuntimeError(
                "PLC was found, but its initial Audit Value "
                "could not be registered."
            )

                # DEMO STEP 27: RETRIEVE THE FRIENDLY PLC NAME.
        # The serial number identifies the physical processor.
        # ControllerID links that processor to its friendly name.

        cursor.execute("""
            SELECT c.ControllerName
            FROM dbo.Controllers AS c
            INNER JOIN dbo.ControllerHardware AS h
                ON h.ControllerID = c.ControllerID
            WHERE h.SerialNumber = ?
              AND h.RemovedAt IS NULL
        """, serial_number)

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError("Friendly PLC name not found.")

        connection.commit()

        return row.ControllerName, serial_number, audit_value, "registered"

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

# DEMO STEP 31: READ REGISTERED AUDIT VALUE.
# Read-only database operation. Never updates the baseline.

def get_demo_registered_audit(controller_id):

    # DEMO STEP 42A: USE THE SELECTED CONTROLLER.
    selected_controller = get_demo_selected_controller(controller_id)
    plc_ip = selected_controller["ip_address"]

    connection = pyodbc.connect(connection_string, timeout=5)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                c.ControllerName,
                h.SerialNumber,
                h.InitialAuditValue
            FROM dbo.ControllerHardware AS h
            INNER JOIN dbo.Controllers AS c
                ON c.ControllerID = h.ControllerID
            WHERE c.IPAddress = ?
              AND h.RemovedAt IS NULL
        """, plc_ip)

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "No active PLC registration found in TRACE."
            )

        if row.InitialAuditValue is None:
            raise RuntimeError(
                "PLC found, but its initial Audit Value "
                "has not been registered."
            )

        return (
            row.ControllerName,
            str(row.SerialNumber).lower(),
            row.InitialAuditValue.strip()
        )

    finally:
        connection.close()

# DEMO STEP 32: COMPARE LIVE AND REGISTERED AUDIT VALUES.
# PLC and database operations are read-only.
# Never overwrite the initial registered Audit Value.

def check_demo_audit_value(controller_id):

    from pycomm3 import LogixDriver

    # DEMO STEP 42B: USE THE SELECTED CONTROLLER.
    selected_controller = get_demo_selected_controller(controller_id)
    plc_ip = selected_controller["ip_address"]

    # STEP 32A: GET THE REGISTERED BASELINE.
    friendly_name, registered_serial, initial_audit = (
        get_demo_registered_audit(controller_id)
    )

    # STEP 32B: VERIFY THE PHYSICAL PROCESSOR.
    with LogixDriver(plc_ip) as plc:
        info = plc.get_plc_info()
        live_serial = str(info["serial"]).lower()

    if live_serial != registered_serial:
        raise RuntimeError(
            "PLC serial number mismatch. "
            f"Registered: {registered_serial}, "
            f"Connected: {live_serial}. "
            "A processor replacement may have occurred."
        )

    # STEP 32C: READ THE CURRENT AUDIT VALUE.
    current_audit = read_demo_audit_value(plc_ip)

    # STEP 32D: DETERMINE WHETHER A CHANGE OCCURRED.
    change_detected = current_audit != initial_audit

    return {
        "friendly_name": friendly_name,
        "serial_number": registered_serial,
        "initial_audit": initial_audit,
        "current_audit": current_audit,
        "change_detected": change_detected
    }

# DEMO STEP 40: RESOLVE SELECTED CONTROLLER.
# Reads the existing TRACE registry without changing SQL records.

def get_demo_selected_controller(controller_id):

    if not str(controller_id).isdigit():
        raise ValueError("Select a valid PLC.")

    connection = pyodbc.connect(connection_string, timeout=5)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT ControllerID, ControllerName, IPAddress
            FROM dbo.Controllers
            WHERE ControllerID = ?
        """, int(controller_id))

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Selected PLC was not found in TRACE."
            )

        return {
            "controller_id": row.ControllerID,
            "friendly_name": row.ControllerName,
            "ip_address": row.IPAddress
        }

    finally:
        connection.close()

# DEMO STEP 28: HANDLE INITIAL AUDIT REGISTRATION.

@app.route("/demo", methods=["GET", "POST"])
def demo():

    registration_message = None
    registration_error = None
    friendly_name = None
    registered_serial = None
    registered_audit = None

    # DEMO STEP 43F: INITIALIZE AUDIT RESULTS.
    # Only check the PLC when the user clicks Check Audit Value.
    audit_result = None
    audit_error = None

    demo_controllers = get_controllers()

    # DEMO STEP 54: PREPARE MANUAL L5X UPLOAD RESULTS.
    upload_message = None
    upload_error = None
    comparison_details = None
    # STEP 378: PREPARE STRUCTURED RUNG CHANGES FOR DISPLAY.
    rung_changes = []

    if request.method == "POST":
        # STEP 467: DISCOVER AND SYNCHRONIZE NETWORK PLCs.
        # Reuse the existing network discovery and registration engine.
        # Preserve controller IDs and existing audit registrations.

        if request.form.get("action") == "scan_network":

            try:
                import importlib.util

                discovery_path = Path(__file__).resolve().parent / (
                    "V0.015_Network_Discovery.py"
                )

                spec = importlib.util.spec_from_file_location(
                    "trace_network_discovery",
                    discovery_path
                )

                discovery = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(discovery)

                # STEP 467A: DISCOVER DEVICES AND IDENTIFY PLCs.

                devices = discovery.discover_devices()

                controllers = discovery.identify_discovered_plcs(
                    devices
                )

                # STEP 467B: SYNCHRONIZE IDENTIFIED PLCs WITH SQL.

                synchronized = discovery.synchronize_discovered_plcs(
                    controllers
                )

                # STEP 467C: REFRESH THE WEB INVENTORY.

                demo_controllers = get_controllers()

                registration_message = (
                    f"Network scan complete. "
                    f"Discovered {len(controllers)} PLC(s). "
                    f"Successfully synchronized "
                    f"{len(synchronized)} controller(s)."
                )

            except Exception as error:
                registration_error = (
                    f"Network discovery failed: {error}"
                )        
                
                # DEMO STEP 55: RECEIVE MANUAL L5X UPLOAD.
        if request.form.get("action") == "upload_L5X":
            try:
                from uuid import uuid4

                uploaded_file = request.files.get("L5X_file")
                
                # STEP 312: VALIDATE THE SELECTED PLC.
                controller_id = request.form.get("controller_id")
                selected_controller = get_demo_selected_controller(controller_id)
                # STEP 372: VERIFY THE SELECTED CONTROLLER ASSOCIATION.
                print(
                    "TRACE UPLOAD ASSOCIATION:",
                    "Controller ID =", controller_id,
                    "Controller Record =", selected_controller,
                    flush=True
                )

                if uploaded_file is None or not uploaded_file.filename:
                    raise ValueError("Select an L5X file.")

                if Path(uploaded_file.filename).suffix.lower() != ".l5x":
                    raise ValueError("Only L5X files are supported.")

                staging_folder = Path(r"C:\TRACE_Backups\Staging")
                staging_folder.mkdir(parents=True, exist_ok=True)

                staged_path = staging_folder / f"{uuid4().hex}.L5X"

                with staged_path.open("xb") as output:
                    uploaded_file.save(output)

                # STEP 337: GET CONTROLLER NAME FROM THE SELECTED PLC.
                controller_name = selected_controller.get(
                    "ControllerName",
                    selected_controller.get("Name", f"Controller_{controller_id}")
                )

                # STEP 341: LOAD THE EXISTING TRACE BACKUP NAMING FUNCTIONS.
                import importlib.util

                backup_manager_path = Path(__file__).with_name(
                    "V0_019_Backup_Manager.py"
                )

                spec = importlib.util.spec_from_file_location(
                    "trace_backup_manager", backup_manager_path
                )
                backup_manager = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(backup_manager)

                controller_name = backup_manager.get_backup_controller_name(
                    int(controller_id)
                )

                # STEP 345: USE THE REGISTERED FRIENDLY NAME AS THE BACKUP FOLDER.
                controller_folder = Path(r"C:\TRACE_Backups") / controller_name

                archive_folder = controller_folder / "Backup"
                archive_folder.mkdir(parents=True, exist_ok=True)

                (controller_folder / "Hold").mkdir(parents=True, exist_ok=True)

                existing_backups = sorted(
                    archive_folder.glob("*.L5X"),
                    key=lambda file: file.stat().st_mtime,
                    reverse=True
                )

                # STEP 336: ESTABLISH BASELINE OR COMPARE AGAINST LATEST BACKUP.

                import hashlib
                import shutil

                if not existing_backups:

                    baseline_filename = backup_manager.generate_backup_filename(
                        controller_id=int(controller_id),
                        storage_root=controller_folder,
                        file_extension=".L5X"
                    )

                    baseline_path = archive_folder / baseline_filename

                    shutil.copy2(staged_path, baseline_path)

                    upload_message = (
                        f"Baseline established for {controller_name}. "
                        f"Saved: {baseline_path.name}"
                    )

                else:

                    # Compare against the newest existing L5X backup.
                    latest_backup = existing_backups[0]

                    def sha256(path):
                        with path.open("rb") as file:
                            return hashlib.file_digest(file, "sha256").hexdigest()

                    baseline_hash = sha256(latest_backup)
                    uploaded_hash = sha256(staged_path)


                   # STEP 365: DETERMINE WHETHER THE UPLOADED PROJECT CHANGED.
                    if baseline_hash == uploaded_hash:
                        upload_message = (
                            f"Compared against: {latest_backup.name} | "
                            f"NO CHANGES DETECTED for {controller_name}"
                        )
                    else:

                        # STEP 364: RUN STRUCTURED L5X LADDER LOGIC COMPARISON.
                        # Load TRACE's comparison engine and compare the accepted
                        # baseline against the newly uploaded project.
                        #
                        # Results identify the task, program, routine, rung number,
                        # change type, previous logic, and new logic.

                        comparison_engine_path = Path(__file__).with_name(
                            "V0.020_Comparison_Engine.py"
                        )

                        comparison_spec = importlib.util.spec_from_file_location(
                            "trace_comparison_engine",
                            comparison_engine_path
                        )

                        comparison_engine = importlib.util.module_from_spec(
                            comparison_spec
                        )

                        comparison_spec.loader.exec_module(comparison_engine)

                        rung_changes = comparison_engine.compare_l5x_rungs(
                            latest_backup,
                            staged_path
                        )
                        
                        # STEP 388: LOAD THE GRAPHICAL LADDER RENDERER.

                        ladder_renderer_path = Path(__file__).with_name(
                            "V0.022_Ladder_Renderer.py"
                        )

                        ladder_spec = importlib.util.spec_from_file_location(
                            "trace_ladder_renderer",
                            ladder_renderer_path
                        )

                        ladder_renderer = importlib.util.module_from_spec(
                            ladder_spec
                        )

                        ladder_spec.loader.exec_module(ladder_renderer)

                        # STEP 382: ADD EXACT CHANGE HIGHLIGHTING TO EACH RUNG.
                        # Preserve the complete instruction strings while identifying
                        # changed characters, instructions, and operands.

                        for change in rung_changes:

                            previous_parts, new_parts = (
                                comparison_engine.highlight_rung_changes(
                                    change["previous_logic"],
                                    change["new_logic"]
                                )
                            )

                            change["previous_parts"] = previous_parts
                            change["new_parts"] = new_parts
                            # STEP 388: PREPARE INSTRUCTIONS FOR GRAPHICAL DISPLAY.

                            change["previous_instructions"] = ladder_renderer.parse_ladder_rung(
                                change["previous_logic"]
                            )

                            change["new_instructions"] = ladder_renderer.parse_ladder_rung(
                                change["new_logic"]
                            )

                            # STEP 512: COMPARE INSTRUCTIONS BEFORE SVG RENDERING.
                            # Preserve instruction-level change information for both versions.

                            previous_elements = ladder_renderer.parse_ladder_structure(
                                change["previous_logic"]
                            )

                            new_elements = ladder_renderer.parse_ladder_structure(
                                change["new_logic"]
                            )

                            previous_elements, new_elements = (
                                ladder_renderer.mark_ladder_changes(
                                    previous_elements,
                                    new_elements
                                )
                            )

                            change["previous_svg"] = ladder_renderer.render_ladder_svg(
                                change["previous_logic"],
                                elements=previous_elements
                            )

                            change["new_svg"] = ladder_renderer.render_ladder_svg(
                                change["new_logic"],
                                elements=new_elements
                            )

                        comparison_details = ""

                        if rung_changes:
                            for change in rung_changes:
                                comparison_details += (
                                    f"\n{'=' * 65}\n"
                                    f"TASK: {change['task']}\n"
                                    f"PROGRAM: {change['program']}\n"
                                    f"ROUTINE: {change['routine']}\n"
                                    f"RUNG: {change['rung']}\n"
                                    f"CHANGE: {change['change_type']}\n\n"
                                    f"PREVIOUS LOGIC:\n"
                                    f"{change['previous_logic']}\n\n"
                                    f"NEW LOGIC:\n"
                                    f"{change['new_logic']}\n"
                                )
                        else:
                            comparison_details = (
                                "No ladder rung changes detected. "
                                "Other project data may have changed."
                            )
                        # STEP 352: SAVE CHANGED L5X FOR USER REVIEW.
                        pending_folder = controller_folder / "Pending"
                        pending_folder.mkdir(parents=True, exist_ok=True)

                        new_backup_name = backup_manager.generate_backup_filename(
                            controller_id=int(controller_id),
                            storage_root=controller_folder,
                            file_extension=".L5X"
                        )

                        new_backup_path = pending_folder / new_backup_name

                        shutil.copy2(staged_path, new_backup_path)

                        # STEP 354A: REMEMBER THE EXACT BACKUP AWAITING REVIEW.
                        session["pending_backup_review"] = {
                            "controller_id": int(controller_id),
                            "filename": new_backup_name
                        }

                        upload_message = (
                            f"Compared against: {latest_backup.name} | "
                            f"CHANGES DETECTED for {controller_name} | "
                            f"Backup save pending review: {new_backup_name}"
    )
                                    
            except Exception as error:
                upload_error = str(error)
        # STEP 354B: PROCESS THE USER'S BACKUP REVIEW DECISION.
        # Retain moves the pending file into the accepted Backup folder.
        # Discard deletes only the pending file, never the baseline.
        if request.form.get("action") in ("retain_backup", "discard_backup"):
            try:
                import shutil

                action = request.form.get("action")
                review = session.get("pending_backup_review")

                if review:
                    # Resolve the PLC from SQL, not from a browser-supplied path.
                    selected = get_demo_selected_controller(
                        review["controller_id"]
                    )

                    controller_name = selected["friendly_name"]
                    filename = review["filename"]

                    if Path(filename).name != filename:
                        raise ValueError("Invalid pending backup filename.")

                    controller_folder = (
                        Path(r"C:\TRACE_Backups") / controller_name
                    )

                    pending_path = (
                        controller_folder / "Pending" / filename
                    )

                else:
                    # Recover an existing pending file when the server was
                    # restarted before session tracking was added.
                    candidates = []

                    for controller in demo_controllers:
                        folder = (
                            Path(r"C:\TRACE_Backups")
                            / controller["ControllerName"]
                        )

                        for file in (folder / "Pending").glob("*.L5X"):
                            candidates.append(
                                (controller["ControllerName"], file)
                            )

                    if len(candidates) != 1:
                        raise ValueError(
                            "Unable to identify a single pending backup. "
                            "Run the comparison again."
                        )

                    controller_name, pending_path = candidates[0]
                    controller_folder = pending_path.parent.parent

                if not pending_path.is_file():
                    raise FileNotFoundError(
                        "Pending backup file was not found."
                    )

                if action == "retain_backup":
                    backup_folder = controller_folder / "Backup"
                    backup_folder.mkdir(parents=True, exist_ok=True)

                    destination = backup_folder / pending_path.name

                    if destination.exists():
                        raise FileExistsError(
                            "An accepted backup already has this filename."
                        )

                    shutil.move(str(pending_path), str(destination))

                    upload_message = (
                        f"Backup Retained for {controller_name}: "
                        f"{destination.name}"
                    )

                else:
                    pending_filename = pending_path.name
                    pending_path.unlink()

                    upload_message = (
                        f"Backup Discarded for {controller_name}: "
                        f"{pending_filename}"
                    )

                session.pop("pending_backup_review", None)

            except Exception as error:
                upload_error = str(error)
        if request.form.get("action") == "register_audit":
            try:
                (
                    friendly_name,
                    registered_serial,
                    registered_audit,
                    registration_status
                ) = register_demo_initial_audit(
                    request.form.get("controller_id")
                )
                # STEP 493: CREATE CONTROLLER BACKUP FOLDERS
                # AFTER SUCCESSFUL INITIAL AUDIT REGISTRATION.

                controller_id = int(
                    request.form.get("controller_id")
                )

                backup_root = (
                    Path(r"C:\TRACE_Backups")
                    / friendly_name
                )

                (backup_root / "Backup").mkdir(
                    parents=True,
                    exist_ok=True
                )

                (backup_root / "Hold").mkdir(
                    parents=True,
                    exist_ok=True
                )

                if registration_status == "already_registered":
                    registration_message = "PLC already registered."
                else:
                    registration_message = (
                        "Initial Audit Value registered successfully."
                    )
            except Exception as error:
                registration_error = str(error)
        if request.form.get("action") == "check_audit":
            try:
                audit_result = check_demo_audit_value(
                    request.form.get("controller_id")
                )
            except Exception as error:
                audit_error = str(error)

    return render_template(
        "demo.html",
        registration_message=registration_message,
        registration_error=registration_error,
        friendly_name=friendly_name,
        registered_serial=registered_serial,
        registered_audit=registered_audit,
        audit_result=audit_result,
        audit_error=audit_error,
        demo_controllers=demo_controllers,
        upload_message=upload_message,
        upload_error=upload_error,
        comparison_details=comparison_details,
        rung_changes=rung_changes
    )

# SECTION 3: EVENT HISTORY PAGE.
# Retrieve recorded hardware events from SQL Server.
# Preserve all events, including resolved warnings.

@app.route("/history")
def history():

    # STEP 1: CONNECT TO THE TRACE DATABASE.
    connection = pyodbc.connect(
        connection_string,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 2: RETRIEVE HARDWARE EVENT HISTORY.
        # Join each event to its permanent equipment record.
        # Do not retrieve or display processor serial numbers.

        cursor.execute("""
            SELECT
                e.EventID,
                e.ControllerID,
                c.ControllerName,
                e.EventType,
                e.DetectedIPAddress,
                e.EventStatus,
                e.DetectedAt,
                e.ResolvedAt,
                e.ResolvedBy,
                e.ResolutionNotes
            FROM dbo.HardwareEvents AS e
            INNER JOIN dbo.Controllers AS c
                ON e.ControllerID = c.ControllerID
            ORDER BY e.DetectedAt DESC, e.EventID DESC
        """)

        # STEP 3: CONVERT SQL RESULTS TO DICTIONARIES.
        columns = [
            column[0]
            for column in cursor.description
        ]

        hardware_events = [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        # STEP 4: CLOSE THE DATABASE CONNECTION.
        connection.close()

    # STEP 5: DISPLAY THE EVENT HISTORY.
    return render_template(
        "history.html",
        hardware_events=hardware_events
    )



# SECTION 4: SYSTEM SETTINGS PAGE
@app.route("/settings")
def settings():
    return render_template("settings.html")

# STEP 8: INITIALIZE SQL SERVER BEFORE STARTING TRACE.
# STEP 8: INITIALIZE SQL SERVER BEFORE STARTING TRACE.
if __name__ == "__main__":
    from V0_013_Database_Setup import initialize_database

    # STEP 8A: RUN DATABASE SETUP AUTOMATICALLY.
    print("TRACE: Checking database installation...")
    initialize_database()
    print("TRACE: Database initialization successful.")

    # STEP 8B: START THE WEB INTERFACE.
    app.run(debug=True, host="127.0.0.1", port=5000)