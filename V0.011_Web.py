# STEP 1: IMPORT FLASK WEB AND SESSION FEATURES.
from flask import Flask, render_template, request, session, redirect, url_for
import pyodbc
import os

# STEP 1A: IMPORT SUPPORT FOR PROJECT FILE UPLOADS.
from pathlib import Path
import importlib.util

# DEMO STEP 20A: IMPORT PLC AUDIT READER DEPENDENCIES.
from pycomm3 import CIPDriver
import struct

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

BACKUP_ROOT = Path(os.environ.get("TRACE_BACKUP_ROOT", r"C:\TRACE_Backups"))

# STEP 2B: CONFIGURE THE SQL SERVER CONNECTION.
connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.environ.get('TRACE_SQL_SERVER', r'localhost\SQLEXPRESS')};"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

@app.route("/")
def home():
    return redirect(url_for("demo"))

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
                InitialAuditValue = ?
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
                staged_path = None

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

                staging_folder = BACKUP_ROOT / "Staging"
                staging_folder.mkdir(parents=True, exist_ok=True)

                staged_path = staging_folder / f"{uuid4().hex}.L5X"

                with staged_path.open("xb") as output:
                    uploaded_file.save(output)

                # STEP 337: GET CONTROLLER NAME FROM THE SELECTED PLC.
                controller_name = selected_controller["friendly_name"]

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
                controller_folder = BACKUP_ROOT / controller_name

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
            finally:
                if staged_path is not None:
                    staged_path.unlink(missing_ok=True)
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
                        BACKUP_ROOT / controller_name
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
                            BACKUP_ROOT
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

                expected_pending = (controller_folder / "Pending").resolve()
                if pending_path.resolve().parent != expected_pending:
                    raise ValueError("Backup is outside the Pending directory.")

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
                    BACKUP_ROOT
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











