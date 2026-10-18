
"""
TRACE V0.019 - Backup Manager
Backup retention, file staging, project comparison, and SQL registration.

Includes file-handling and comparison helpers; some workflows
require complete verification before allowing deletion.
"""
import hashlib
from pathlib import Path
import shutil
from datetime import datetime, timezone
from uuid import uuid4
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
import pyodbc
import os
import re

# STEP 1: CONFIGURE TRACE BACKUP STORAGE.
# Defaults to local storage during development.
# Can later be overridden with a server UNC path.

BACKUP_STORAGE_ROOT = Path(
    os.environ.get("TRACE_BACKUP_ROOT", r"C:\TRACE_Backups")
)

# STEP 2: DEFINE BACKUP TRIGGERS.

class BackupTrigger(str, Enum):
    SCHEDULED = "Scheduled"
    MONITOR = "MonitorTriggered"
    MANUAL = "Manual"


# STEP 3: DEFINE COMPARISON RESULTS.

class ComparisonResult(str, Enum):
    NO_CHANGES = "NoChanges"
    CHANGES_DETECTED = "ChangesDetected"
    INCOMPLETE = "Incomplete"
    FAILED = "Failed"


# STEP 4: DEFINE RETENTION DECISIONS.

class BackupDecision(str, Enum):
    RETAIN = "Retain"
    DISCARD = "Discard"
    HOLD = "Hold"


# STEP 5: DEFINE BACKUP EVALUATION DATA.

@dataclass(frozen=True)
class BackupEvaluation:
    trigger: BackupTrigger
    comparison: ComparisonResult
    decision: BackupDecision
    audit_required: bool
    reason: str



# STEP 6: EVALUATE BACKUP RETENTION.
# Only verified no-change monitoring captures
# may be automatically discarded.

def evaluate_backup(trigger, comparison):

    trigger = BackupTrigger(trigger)
    comparison = ComparisonResult(comparison)

    # STEP 7: RETAIN SCHEDULED AND MANUAL CAPTURES.
    # always retained, even when comparison fails.
    if trigger in (
        BackupTrigger.SCHEDULED,
        BackupTrigger.MANUAL,
    ):
        return BackupEvaluation(
            trigger=trigger,
            comparison=comparison,
            decision=BackupDecision.RETAIN,
            audit_required=(
                comparison != ComparisonResult.NO_CHANGES
            ),
            reason="Protected recovery backup; always retain.",
        )

    # STEP 8: HOLD UNRESOLVED MONITORING CAPTURES.
    # must preserve the captured file.
    if comparison in (
        ComparisonResult.INCOMPLETE,
        ComparisonResult.FAILED,
    ):
        return BackupEvaluation(
            trigger=trigger,
            comparison=comparison,
            decision=BackupDecision.HOLD,
            audit_required=True,
            reason="Comparison unresolved; hold for investigation.",
        )

    # STEP 9: RETAIN CHANGED MONITORING CAPTURES.
    if comparison == ComparisonResult.CHANGES_DETECTED:
        return BackupEvaluation(
            trigger=trigger,
            comparison=comparison,
            decision=BackupDecision.RETAIN,
            audit_required=True,
            reason="Changes detected; archive and generate audit event.",
        )

    # STEP 10: DISCARD VERIFIED UNCHANGED MONITORING CAPTURES.
    # captures are eligible for deletion.
    return BackupEvaluation(
        trigger=trigger,
        comparison=comparison,
        decision=BackupDecision.DISCARD,
        audit_required=False,
        reason="Verified no changes; discard monitoring capture.",
    )


# STEP 11: CALCULATE SHA-256 FILE HASH.
# Read in chunks so large ACD files do not need
# to be loaded entirely into memory.

def calculate_file_hash(file_path):

    file_path = Path(file_path)
    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


# STEP 12: COMPARE BINARY FILE HASHES.
# This checks whether their binary contents are identical.
# It does NOT establish whether PLC logic has changed.

def compare_file_hashes(current_file, baseline_file):

    current_hash = calculate_file_hash(current_file)
    baseline_hash = calculate_file_hash(baseline_file)

    return {
        "CurrentHash": current_hash,
        "BaselineHash": baseline_hash,
        "FilesIdentical": current_hash == baseline_hash,
    }


# STEP 13: INITIALIZE STORAGE DIRECTORIES.
# Creates shared Staging, Archive, and Hold directories in this version.

def initialize_backup_storage(storage_root):

    root = Path(storage_root)

    staging = root / "Staging"
    archive = root / "Archive"
    hold = root / "Hold"

    for folder in (staging, archive, hold):
        folder.mkdir(parents=True, exist_ok=True)

    return {
        "Staging": staging,
        "Archive": archive,
        "Hold": hold,
    }


# STEP 14: STAGE AND VERIFY A CAPTURE.
# The source file is never moved or deleted.

def stage_backup(source_file, storage_root):

    source = Path(source_file)

    if not source.is_file():
        raise FileNotFoundError(source)

    folders = initialize_backup_storage(storage_root)

    unique_name = f"{uuid4().hex}_{source.name}"
    staged_path = folders["Staging"] / unique_name

    shutil.copy2(source, staged_path)

    # Verify that the copied file matches the source.
    if calculate_file_hash(source) != calculate_file_hash(staged_path):
        staged_path.unlink(missing_ok=True)
        raise IOError("Staged backup failed SHA-256 verification.")

    return staged_path

# STEP 15: LOOK UP REGISTERED CONTROLLER NAME.
# Read-only SQL lookup. Does not modify controller records.

def get_backup_controller_name(controller_id):
    """Compatibility wrapper for the canonical controller-name lookup."""
    return get_controller_name(controller_id)

# STEP 16: GENERATE CONTROLLER BACKUP FILENAME.
# Uses the controller name registered in TRACE.
# Uses the controller name registered in TRACE.

def generate_backup_filename(controller_id, storage_root, file_extension):

    # Retrieve the manually registered controller name.
    controller_name = get_backup_controller_name(controller_id)

    # Replace characters that Windows cannot use in filenames.
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", controller_name)
    safe_name = re.sub(r"\s+", "_", safe_name).strip(" ._")

    if not safe_name:
        raise ValueError("Controller has no usable registered name.")

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    extension = file_extension.lstrip(".").upper()

    if extension not in ("l5x", "L5X", "ACD"):
        raise ValueError("Unsupported backup file extension.")

    root = Path(storage_root)

# Checks Backup, Hold, and Pending for filename collisions.
    existing_names = set()

    for folder_name in ("Backup", "Hold", "Pending"):
        folder = root / folder_name

        if folder.exists():
            existing_names.update(
                p.name.lower()
                for p in folder.iterdir()
                if p.is_file()
            )

    # Find the next available daily sequence number.
    sequence = 1

    while True:
        filename = f"{safe_name}_{date}_{sequence:03d}.{extension}"

        if filename.lower() not in existing_names:
            return filename

        sequence += 1

# STEP 17: PREPARE VERIFIED FILE COPY.
# File copying is separate from the retention decision.
# Only call this helper when the caller has selected a destination.

# STEP 18: COPY WITHOUT OVERWRITING AND VERIFY HASH.
# The copy helper receives explicit source and destination paths.

def copy_verified_backup(source, destination):
    """Copy and verify a backup without overwriting existing files."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()

    if not source.is_file():
        raise FileNotFoundError(source)

    # Exclusive creation prevents overwriting existing backups.
    created = False

    try:
        with destination.open("xb") as output:
            created = True
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)

        if calculate_file_hash(source) != calculate_file_hash(destination):
            raise IOError("Backup archive failed SHA-256 verification.")

    except Exception:
        # Only remove a destination created by this operation.
        if created:
            destination.unlink(missing_ok=True)
        raise

    return destination

def finalize_backup(staged_file, storage_root, evaluation, controller_id):
    staged = Path(staged_file)
    folders = initialize_backup_storage(storage_root)

    if not staged.is_file():
        raise FileNotFoundError(staged)

    # Require the file to be directly inside TRACE's
    # staging folder before allowing any file operations.
    if staged.resolve().parent != folders["Staging"].resolve():
        raise ValueError("Backup is not in the staging directory.")

    # STEP 19: BLOCK AUTOMATIC DELETION IN FINALIZATION.
    # A matching file hash or partial L5X comparison does not
    # establish that the complete PLC program is unchanged.
    #
    # Until full-project verification is implemented, TRACE
    # must preserve every staged capture.

    if evaluation.decision == BackupDecision.DISCARD:
        raise RuntimeError(
            "TRACE safety lock: automatic backup deletion is disabled. "
            "Full PLC project verification is not yet implemented."
    )

    if evaluation.decision == BackupDecision.HOLD:
        destination_folder = folders["Hold"]
    else:
        destination_folder = folders["Archive"]

    # STEP 20: GENERATE FINALIZED BACKUP FILENAME.
    # Format: ControllerName_YYYY-MM-DD_001.l5x

    filename = generate_backup_filename(
        controller_id=controller_id,
        storage_root=storage_root,
        file_extension=staged.suffix,
    )

    destination = destination_folder / filename

    # Prevent accidental overwriting.
    if destination.exists():
        raise FileExistsError(
            f"Backup already exists: {destination}"
        )

    # Copy exclusively and verify before removing staging.
    copy_verified_backup(staged, destination)

    staged.unlink()

    return destination


# STEP 21: EXTRACT LADDER RUNG LOGIC FROM AN L5X FILE.
# This reads the text of each rung and identifies its
# location by program, routine, and rung number.

def extract_l5x_rungs(file_path):

    tree = ET.parse(file_path)
    root = tree.getroot()

    rungs = {}

    for program in root.findall(".//Programs/Program"):

        program_name = program.get("Name", "")

        for routine in program.findall(".//Routines/Routine"):

            if routine.get("Type") != "RLL":
                continue

            routine_name = routine.get("Name", "")

            for rung in routine.findall("./RLLContent/Rung"):

                rung_number = rung.get("Number", "")

                logic = rung.findtext("Text", default="")

                key = (
                    program_name,
                    routine_name,
                    rung_number,
                )

                rungs[key] = logic.strip()

    return rungs


# STEP 22: COMPARE TWO L5X LADDER LOGIC SNAPSHOTS.
# Detect added, removed, and modified rungs.

def compare_l5x_rungs(current_file, baseline_file):

    current = extract_l5x_rungs(current_file)
    baseline = extract_l5x_rungs(baseline_file)

    changes = []

    all_keys = sorted(set(current) | set(baseline))

    for key in all_keys:

        old_logic = baseline.get(key)
        new_logic = current.get(key)

        if old_logic == new_logic:
            continue

        if old_logic is None:
            change_type = "Added"
        elif new_logic is None:
            change_type = "Removed"
        else:
            change_type = "Modified"

        changes.append({
            "Program": key[0],
            "Routine": key[1],
            "RungNumber": key[2],
            "ChangeType": change_type,
            "OldLogic": old_logic,
            "NewLogic": new_logic,
        })

    return changes




# STEP 23: EXTRACT SELECTED TAG DEFINITIONS.
# Compare tag structure without comparing live values,
# preset values, descriptions, or exported data.

def extract_l5x_tags(file_path):

    root = ET.parse(file_path).getroot()
    controller = root.find("./Controller")

    if controller is None:
        raise ValueError("L5X does not contain a Controller element.")

    tags = {}

    # Attributes that affect the tag definition.
    monitored_attributes = (
        "TagType",
        "DataType",
        "AliasFor",
        "ExternalAccess",
        "Constant",
        "Dimensions",
        "Radix",
    )

    def add_tags(container, scope):

        for tag in container.findall("./Tags/Tag"):

            name = tag.get("Name")

            if not name:
                raise ValueError("Encountered a tag without a name.")

            key = (scope, name)

            if key in tags:
                raise ValueError(f"Duplicate tag: {key}")

            # Extract only selected definition attributes.
            # Child <Data> elements are intentionally ignored.
            definition = tuple(
                (attribute, tag.get(attribute))
                for attribute in monitored_attributes
            )

            tags[key] = definition

    add_tags(controller, "Controller")

    for program in controller.findall("./Programs/Program"):

        program_name = program.get("Name")

        if not program_name:
            raise ValueError("Encountered a program without a name.")

        add_tags(program, f"Program:{program_name}")

    return tags

# STEP 24: EXTRACT STRUCTURED TEXT AND FUNCTION BLOCK ROUTINES.
# Compare their exported XML content.
# This is a structural comparison, not a semantic analysis.

def extract_l5x_other_routines(file_path):

    root = ET.parse(file_path).getroot()
    routines = {}

    for program in root.findall("./Controller/Programs/Program"):

        program_name = program.get("Name", "")

        for routine in program.findall("./Routines/Routine"):

            routine_type = routine.get("Type", "")

            if routine_type not in ("ST", "FBD"):
                continue

            routine_name = routine.get("Name", "")

            key = (program_name, routine_name, routine_type)

            if key in routines:
                raise ValueError(f"Duplicate routine: {key}")

            normalized = ET.canonicalize(
                ET.tostring(routine, encoding="unicode"),
                strip_text=True,
            )

            routines[key] = normalized

    return routines


# STEP 25: COMPARE TWO COLLECTIONS OF PROJECT COMPONENTS.
# Report added, removed, and modified components.

def compare_component_maps(current, baseline, category):

    changes = []

    for key in sorted(set(current) | set(baseline)):

        old_value = baseline.get(key)
        new_value = current.get(key)

        if old_value == new_value:
            continue

        if old_value is None:
            change_type = "Added"
        elif new_value is None:
            change_type = "Removed"
        else:
            change_type = "Modified"

        changes.append({
            "Category": category,
            "Component": key,
            "ChangeType": change_type,
        })

    return changes



# STEP 26: RUN THE EXPANDED L5X PROJECT COMPARISON.
# Combine program logic, tag definitions, and configuration.
# FullProjectVerified remains False until export coverage
# and comparison completeness are validated.

def compare_l5x_project(current_file, baseline_file):

    rung_changes = compare_l5x_rungs(
        current_file,
        baseline_file,
    )

    tag_changes = compare_component_maps(
        extract_l5x_tags(current_file),
        extract_l5x_tags(baseline_file),
        "Tag",
    )

    routine_changes = compare_component_maps(
        extract_l5x_other_routines(current_file),
        extract_l5x_other_routines(baseline_file),
        "ST/FBD Routine",
    )

    configuration = compare_l5x_configuration(
        current_file,
        baseline_file,
    )

    total_changes = (
        len(rung_changes)
        + len(tag_changes)
        + len(routine_changes)
        + configuration["TotalConfigurationChanges"]
    )

    return {
        "RungChanges": rung_changes,
        "TagChanges": tag_changes,
        "RoutineChanges": routine_changes,
        "ControllerChanges": configuration["ControllerChanges"],
        "ModuleChanges": configuration["ModuleChanges"],
        "TaskChanges": configuration["TaskChanges"],
        "TotalChanges": total_changes,
        "FullProjectVerified": False,
    }

# STEP 27: NORMALIZE CONFIGURATION XML.
# Remove descriptive text and exported tag data values.
# Preserve other configuration attributes and elements.
#
# This is an initial structural comparison, not yet a
# verified complete Rockwell configuration parser.

def normalize_configuration_xml(element):

    from copy import deepcopy

    normalized = deepcopy(element)

    for node in list(normalized.iter()):

        # Ignore descriptive metadata.
        node.attrib.pop("Description", None)

        for child in list(node):

            if child.tag in ("Description", "Data"):
                node.remove(child)

    return ET.canonicalize(
        ET.tostring(normalized, encoding="unicode"),
        strip_text=True,
    )


# STEP 28: EXTRACT CONTROLLER CONFIGURATION.
# Compare controller attributes, excluding identity fields
# and volatile metadata that are not program configuration.

def extract_l5x_controller_config(file_path):

    root = ET.parse(file_path).getroot()
    controller = root.find("./Controller")

    if controller is None:
        raise ValueError("L5X does not contain a Controller element.")

    excluded_attributes = {
        "Name",
        "Description",
        "LastModifiedDate",
    }

    return {
        attribute: value
        for attribute, value in controller.attrib.items()
        if attribute not in excluded_attributes
    }


# STEP 29: EXTRACT MODULE AND CHANNEL CONFIGURATION.
# Capture complete exported module subtrees, excluding
# descriptive metadata and Data elements.
#
# Channel settings may appear as nested configuration
# elements or encoded module-specific data.

def extract_l5x_modules(file_path):

    root = ET.parse(file_path).getroot()
    controller = root.find("./Controller")

    if controller is None:
        raise ValueError("L5X does not contain a Controller element.")

    modules = {}

    for module in controller.findall("./Modules/Module"):

        module_name = module.get("Name")

        if not module_name:
            raise ValueError("Encountered a module without a name.")

        if module_name in modules:
            raise ValueError(f"Duplicate module: {module_name}")

        modules[module_name] = normalize_configuration_xml(module)

    return modules


# STEP 30: EXTRACT TASK CONFIGURATION.
# Compare task attributes and task-to-program scheduling.
# Program logic is compared separately.

def extract_l5x_tasks(file_path):

    root = ET.parse(file_path).getroot()
    controller = root.find("./Controller")

    if controller is None:
        raise ValueError("L5X does not contain a Controller element.")

    tasks = {}

    for task in controller.findall("./Tasks/Task"):

        task_name = task.get("Name")

        if not task_name:
            raise ValueError("Encountered a task without a name.")

        if task_name in tasks:
            raise ValueError(f"Duplicate task: {task_name}")

        tasks[task_name] = normalize_configuration_xml(task)

    return tasks


# STEP 31: COMPARE CONTROLLER, MODULE, AND TASK CONFIGURATION.

def compare_l5x_configuration(current_file, baseline_file):

    current_controller = extract_l5x_controller_config(current_file)
    baseline_controller = extract_l5x_controller_config(baseline_file)

    controller_changes = compare_component_maps(
        current_controller,
        baseline_controller,
        "Controller Configuration",
    )

    module_changes = compare_component_maps(
        extract_l5x_modules(current_file),
        extract_l5x_modules(baseline_file),
        "Module Configuration",
    )

    task_changes = compare_component_maps(
        extract_l5x_tasks(current_file),
        extract_l5x_tasks(baseline_file),
        "Task Configuration",
    )

    return {
        "ControllerChanges": controller_changes,
        "ModuleChanges": module_changes,
        "TaskChanges": task_changes,
        "TotalConfigurationChanges": (
            len(controller_changes)
            + len(module_changes)
            + len(task_changes)
        ),
    }


# STEP 32: TRANSLATE PROJECT COMPARISON INTO
# A BACKUP RETENTION DECISION.
#
# A zero-change result is NOT sufficient to delete
# a monitoring capture unless full-project
# comparison has been verified.

def evaluate_project_backup(trigger, comparison_report):

    trigger = BackupTrigger(trigger)

    # Validate the comparison report before using its results.
    if not isinstance(comparison_report, dict):
        result = ComparisonResult.FAILED

    elif (
        not isinstance(comparison_report.get("TotalChanges"), int)
        or isinstance(comparison_report.get("TotalChanges"), bool)
        or comparison_report["TotalChanges"] < 0
        or type(comparison_report.get("FullProjectVerified")) is not bool
    ):
        result = ComparisonResult.FAILED

    # Actual detected changes take priority over verification status.
    elif comparison_report["TotalChanges"] > 0:
        result = ComparisonResult.CHANGES_DETECTED

    # A verified complete comparison can report no changes.
    elif comparison_report["FullProjectVerified"] is True:
        result = ComparisonResult.NO_CHANGES

    # Otherwise, comparison coverage is incomplete.
    else:
        result = ComparisonResult.INCOMPLETE

    return evaluate_backup(trigger, result)


# STEP 33: CONNECT TO THE TRACE SQL SERVER DATABASE.
# Uses Windows authentication and the existing
# local SQL Server Express instance.

def connect_trace_database():

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ.get('TRACE_SQL_SERVER', r'localhost\SQLEXPRESS')};"
        "DATABASE=TRACE;"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string,
        autocommit=False,
    )


# STEP 34: REGISTER A BACKUP FILE IN SQL.
# This function records metadata for an existing file.
# It does not acquire or copy the PLC project.

# The optional ProjectID associates this backup with a project.

def register_backup(
    controller_id,
    file_path,
    backup_source,
    project_id=None,
):

    file_path = Path(file_path)

    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    backup_source = BackupTrigger(backup_source)

    file_hash = calculate_file_hash(file_path)

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

                # Insert the backup record with its optional project association.
        # SQL verifies that ProjectID belongs to ControllerID.

        cursor.execute(
            """
            INSERT INTO dbo.Backups
                (ControllerID, ProjectID, FilePath, FileHash,
                 BackupSource, OriginalFileName, FileType)
            OUTPUT INSERTED.BackupID
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            controller_id,
            project_id,
            str(file_path.resolve()),
            file_hash,
            backup_source.value,
            file_path.name,
            file_path.suffix.lstrip(".").upper(),
        )

        backup_id = cursor.fetchone()[0]

        connection.commit()

        return backup_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 35: RECORD A BACKUP COMPARISON.
# A comparison record may exist without a BackupID
# when a monitoring capture was discarded.

def register_backup_comparison(
    controller_id,
    backup_source,
    evaluation,
    comparison_report=None,
    backup_id=None,
    notes=None,
):

    backup_source = BackupTrigger(backup_source)

    total_changes = None
    full_project_verified = False

    if isinstance(comparison_report, dict):
        total_changes = comparison_report.get("TotalChanges")
        full_project_verified = (
            comparison_report.get("FullProjectVerified") is True
        )

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO dbo.BackupComparisons
                (ControllerID, BackupID, BackupSource,
                 ComparisonResult, RetentionDecision,
                 TotalChanges, FullProjectVerified,
                 AuditRequired, ComparisonNotes)
            OUTPUT INSERTED.ComparisonID
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            controller_id,
            backup_id,
            backup_source.value,
            evaluation.comparison.value,
            evaluation.decision.value,
            total_changes,
            int(full_project_verified),
            int(evaluation.audit_required),
            notes or evaluation.reason,
        )

        comparison_id = cursor.fetchone()[0]

        connection.commit()

        return comparison_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 36: RETRIEVE COMPARISON HISTORY.
# Results are ordered newest first.

def get_backup_comparison_history(controller_id):

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ComparisonID,
                BackupID,
                BackupSource,
                ComparisonResult,
                RetentionDecision,
                TotalChanges,
                FullProjectVerified,
                AuditRequired,
                PossibleMonitorMiss,
                ComparedAt,
                ComparisonNotes
            FROM dbo.BackupComparisons
            WHERE ControllerID = ?
            ORDER BY ComparedAt DESC, ComparisonID DESC
            """,
            controller_id,
        )

        columns = [
            column[0] for column in cursor.description
        ]

        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()

# STEP 37: RETRIEVE CONTROLLER BACKUP HISTORY.
# Uses the existing TRACE SQL schema.
# Read-only. Does not modify backup files or database records.

def get_controller_backup_history(controller_id):

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                b.BackupID,
                b.ControllerID,
                b.BackupSource,
                b.FilePath,
                b.FileHash,
                b.BackupTime AS CreatedAt,
                b.BackupStatus,
                b.OriginalFileName,
                b.FileType,
                bc.ComparisonID,
                bc.ComparisonResult,
                bc.RetentionDecision,
                bc.FullProjectVerified,
                bc.AuditRequired
            FROM dbo.Backups AS b
            OUTER APPLY (
                SELECT TOP (1)
                    c.ComparisonID,
                    c.ComparisonResult,
                    c.RetentionDecision,
                    c.FullProjectVerified,
                    c.AuditRequired
                FROM dbo.BackupComparisons AS c
                WHERE c.BackupID = b.BackupID
                  AND c.ControllerID = b.ControllerID
                ORDER BY c.ComparedAt DESC, c.ComparisonID DESC
            ) AS bc
            WHERE b.ControllerID = ?
            ORDER BY b.BackupTime DESC, b.BackupID DESC
            """,
            controller_id,
        )

        columns = [column[0] for column in cursor.description]

        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()

# STEP 38: REGISTER A BACKUP AND ITS COMPARISON TOGETHER.
# Both records use one SQL transaction.
# A discarded capture has no BackupID.
# This function does not move or delete files.

def register_backup_transaction(
    controller_id,
    backup_source,
    evaluation,
    comparison_report=None,
    archived_file=None,
    notes=None,
    project_id=None,  # Optional registered project association
):

    backup_source = BackupTrigger(backup_source)

    # Validate the requested retention decision and required file.
    # Retained backups must have an existing archive file.
    # Discarded captures must not have an archive file.

    if evaluation.trigger != backup_source:
        raise ValueError("Backup source does not match evaluation.")

    if evaluation.decision in (
        BackupDecision.RETAIN,
        BackupDecision.HOLD,
    ):
        if archived_file is None:
            raise ValueError("Retained or held backup requires a file.")

    elif archived_file is not None:
        raise ValueError("Discarded backup cannot have an archive file.")

    file_path = None
    file_hash = None

    if archived_file is not None:
        file_path = Path(archived_file).resolve()

        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        file_hash = calculate_file_hash(file_path)

    # Extract change count and full-project verification status.
    total_changes = None
    full_project_verified = False

    if isinstance(comparison_report, dict):
        total_changes = comparison_report.get("TotalChanges")
        full_project_verified = (
            comparison_report.get("FullProjectVerified") is True
        )

    # Open a database connection for a single transaction.
    connection = connect_trace_database()

    try:
        cursor = connection.cursor()
        backup_id = None

        # Insert backup metadata only when a retained or held file exists.
        if file_path is not None:

            # Include the optional registered project association.
            # SQL enforces that ProjectID belongs to ControllerID.

            cursor.execute(
                """
                INSERT INTO dbo.Backups
                    (ControllerID, ProjectID, FilePath, FileHash,
                     BackupSource, OriginalFileName, FileType)
                OUTPUT INSERTED.BackupID
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                controller_id,
                project_id,
                str(file_path),
                file_hash,
                backup_source.value,
                file_path.name,
                file_path.suffix.lstrip(".").upper(),
            )

            backup_id = cursor.fetchone()[0]

        # Insert the comparison record in the same transaction.
        cursor.execute(
            """
            INSERT INTO dbo.BackupComparisons
                (ControllerID, BackupID, BackupSource,
                 ComparisonResult, RetentionDecision,
                 TotalChanges, FullProjectVerified,
                 AuditRequired, ComparisonNotes)
            OUTPUT INSERTED.ComparisonID
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            controller_id,
            backup_id,
            backup_source.value,
            evaluation.comparison.value,
            evaluation.decision.value,
            total_changes,
            int(full_project_verified),
            int(evaluation.audit_required),
            notes or evaluation.reason,
        )

        comparison_id = cursor.fetchone()[0]

        # Commit the backup and comparison records together.
        connection.commit()

        return {
            "BackupID": backup_id,
            "ComparisonID": comparison_id,
            "FilePath": str(file_path) if file_path else None,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 39: COPY A STAGED BACKUP AND REGISTER IT IN SQL.
# The archive copy is verified before database registration.
# If SQL registration fails, preserve the file for recovery.
# Automatic deletion is intentionally disabled here.

def archive_and_register_backup(
    controller_id,
    backup_source,
    staged_file,
    evaluation,
    comparison_report=None,
    notes=None,
    project_id=None,
):

    backup_source = BackupTrigger(backup_source)

    # Confirm the trigger matches the retention evaluation.
    if evaluation.trigger != backup_source:
        raise ValueError("Backup source does not match evaluation.")

    # Reject DISCARD requests; this function does not convert them to HOLD.
    # Monitoring captures must be preserved until TRACE can
    # verify the complete PLC program.

    if evaluation.decision == BackupDecision.DISCARD:
        raise ValueError(
            "Unverified DISCARD decision rejected. "
            "Re-evaluate this capture as INCOMPLETE and HOLD "
            "before archival."
        )
    

    # Confirm the staged file exists before copying.
    staged = Path(staged_file).resolve()

    if not staged.is_file():
        raise FileNotFoundError(staged)

    # Resolve the shared staging area and controller-specific destination.
    # Staging remains shared, but archived files belong to
    # the permanent folder associated with their ControllerID.

    storage_root = BACKUP_STORAGE_ROOT.resolve()
    folders = initialize_persistent_storage()

    # Verify the file came from TRACE's configured staging folder.
    if staged.parent != folders["Staging"].resolve():
        raise ValueError(
            "File must be inside TRACE's configured staging folder."
        )

    # Find or create the permanent folder for this PLC.
    controller_folder = get_controller_backup_folder(controller_id)

    # Route retained backups into Archive and held backups into Hold.
    destination_folder = (
        controller_folder / "Hold"
        if evaluation.decision == BackupDecision.HOLD
        else controller_folder / "Archive"
    )

    # Generate a readable filename for this registered controller.
    filename = generate_backup_filename(
        controller_id=controller_id,
        storage_root=controller_folder,
        file_extension=staged.suffix,
    )

    destination = destination_folder / filename

    # Never intentionally overwrite an existing backup.
    if destination.exists():
        raise FileExistsError(
            f"Backup destination already exists: {destination}"
        )
    
    # Copy exclusively and verify before SQL registration.
    copy_verified_backup(staged, destination)

    # Register the backup and comparison in one SQL transaction.
    try:
        result = register_backup_transaction(
            controller_id=controller_id,
            project_id=project_id,
            backup_source=backup_source,
            evaluation=evaluation,
            comparison_report=comparison_report,
            archived_file=destination,
            notes=notes,
        )

    except Exception:
        # Preserve both copies for investigation.
        # The archive file can be reconciled with SQL later.
        print(
            "WARNING: SQL registration failed. "
            f"Backup preserved at: {destination}"
        )
        raise

    # Remove the staged copy only after SQL registration succeeds.
    staged.unlink()

    return result

# STEP 40: INITIALIZE PERSISTENT BACKUP STORAGE.
# Existing files and directories are preserved.

def initialize_persistent_storage():

    folders = initialize_backup_storage(BACKUP_STORAGE_ROOT)

    recovery = BACKUP_STORAGE_ROOT / "Recovery"
    recovery.mkdir(parents=True, exist_ok=True)

    folders["Recovery"] = recovery

    return folders

# STEP 41: GET THE REGISTERED PLC NAME FROM SQL SERVER.

def get_controller_name(controller_id):

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT ControllerName
            FROM dbo.Controllers
            WHERE ControllerID = ?
            """,
            controller_id,
        )

        record = cursor.fetchone()

        if record is None:
            raise ValueError(
                f"ControllerID {controller_id} is not registered."
            )

        return record[0]

    finally:
        connection.close()


# STEP 42: CREATE OR LOCATE A PLC'S BACKUP FOLDER.

def get_controller_backup_folder(controller_id):

    controller_name = get_controller_name(controller_id)

    # Remove characters Windows does not permit in folder names.
    safe_name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        controller_name,
    ).strip(" .")

    if not safe_name:
        safe_name = "Unnamed_PLC"

    # Include the permanent ControllerID.
    folder_name = f"{safe_name}_ID{controller_id}"

    controller_folder = BACKUP_STORAGE_ROOT / folder_name

    # If the controller was renamed, reuse its existing folder.
    existing_folders = list(
        BACKUP_STORAGE_ROOT.glob(f"*_ID{controller_id}")
    ) if BACKUP_STORAGE_ROOT.exists() else []

    if len(existing_folders) > 1:
        raise RuntimeError(
            f"Multiple backup folders found for ControllerID {controller_id}."
        )

    if existing_folders:
        controller_folder = existing_folders[0]

    # Create the folder structure.
    (controller_folder / "Archive").mkdir(
        parents=True,
        exist_ok=True,
    )

    (controller_folder / "Hold").mkdir(
        parents=True,
        exist_ok=True,
    )

    return controller_folder


# STEP 43: AUDIT REGISTERED BACKUP FILES.
# Read-only operation: no files or SQL records are modified.

def audit_registered_backups(controller_id=None):

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        # Retrieve backup records for all controllers or one controller.
        if controller_id is None:
            cursor.execute(
                """
                SELECT BackupID, ControllerID, FilePath, FileHash
                FROM dbo.Backups
                ORDER BY ControllerID, BackupID
                """
            )
        else:
            cursor.execute(
                """
                SELECT BackupID, ControllerID, FilePath, FileHash
                FROM dbo.Backups
                WHERE ControllerID = ?
                ORDER BY BackupID
                """,
                controller_id,
            )

        records = cursor.fetchall()

    finally:
        connection.close()

    results = []

    # Verify each stored file against its registered SHA-256 hash.
    for record in records:

        backup_id, plc_id, file_path, expected_hash = record

        status = "Healthy"
        actual_hash = None

        if not file_path:
            status = "Missing"

        else:
            backup_file = Path(file_path)

            if not backup_file.is_file():
                status = "Missing"

            else:
                try:
                    actual_hash = calculate_file_hash(backup_file)

                    if (
                        not expected_hash
                        or actual_hash.lower() != expected_hash.lower()
                    ):
                        status = "Corrupted"

                except (OSError, PermissionError):
                    status = "Unreadable"

        results.append(
            {
                "BackupID": backup_id,
                "ControllerID": plc_id,
                "FilePath": file_path,
                "Status": status,
                "ExpectedHash": expected_hash,
                "ActualHash": actual_hash,
            }
        )

    return results


# STEP 44: FIND BACKUP FILES THAT ARE NOT REGISTERED IN SQL.
# Read-only: does not modify files or database records.

def audit_unregistered_backups():

    # Retrieve registered file paths from SQL for comparison.
    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT FilePath
            FROM dbo.Backups
            WHERE FilePath IS NOT NULL
            """
        )

        registered_paths = {
            os.path.normcase(os.path.abspath(record[0]))
            for record in cursor.fetchall()
        }

    finally:
        connection.close()

    # Search controller-specific Archive and Hold folders for unmatched files.
    unregistered = []

    if not BACKUP_STORAGE_ROOT.exists():
        return unregistered

    for controller_folder in BACKUP_STORAGE_ROOT.iterdir():

        if not controller_folder.is_dir():
            continue

        # Only inspect registered PLC-style folders.
        if not re.search(r"_ID\d+$", controller_folder.name):
            continue

        for subfolder_name in ("Archive", "Hold"):

            subfolder = controller_folder / subfolder_name

            if not subfolder.is_dir():
                continue

            for file_path in subfolder.rglob("*"):

                if not file_path.is_file():
                    continue

                normalized_path = os.path.normcase(
                    os.path.abspath(file_path)
                )

                if normalized_path not in registered_paths:
                    unregistered.append(str(file_path))

    return unregistered


# STEP 45: REGISTER AN EXISTING UNREGISTERED BACKUP FILE.
# Registers an existing file without changing its contents.
# Recovery does not establish PLC program validity or approval.

def recover_unregistered_backup(controller_id, file_path, project_id=None):

    # Resolve the requested recovery file and confirm it exists.
    backup_file = Path(file_path).resolve(strict=True)

    if not backup_file.is_file():
        raise ValueError("Recovery path is not a file.")

    # Confirm the file belongs to the selected controller's
    # Archive or Hold folder before registering it.
    controller_folder = get_controller_backup_folder(
        controller_id
    ).resolve()

    archive_folder = (controller_folder / "Archive").resolve()
    hold_folder = (controller_folder / "Hold").resolve()

    if (
        archive_folder not in backup_file.parents
        and hold_folder not in backup_file.parents
    ):
        raise ValueError(
            "File is not inside this PLC's backup folders."
        )

    # Calculate the recovered file's SHA-256 hash.
    file_hash = calculate_file_hash(backup_file)

    connection = connect_trace_database()

    try:
        cursor = connection.cursor()

        # Lock and check for an existing registration to avoid duplicates.
        # Lock matching records to prevent duplicate recovery.

        cursor.execute(
            """
            SELECT BackupID
            FROM dbo.Backups WITH (UPDLOCK, HOLDLOCK)
            WHERE FilePath = ?
            """,
            str(backup_file),
        )

        existing = cursor.fetchone()

        if existing is not None:
            raise ValueError(
                f"File is already registered as BackupID {existing[0]}."
            )

        # Register the recovered backup with its optional project association.
        # SQL verifies ProjectID belongs to ControllerID.

        cursor.execute(
            """
            INSERT INTO dbo.Backups
                (
                    ControllerID,
                    ProjectID,
                    FilePath,
                    FileHash,
                    BackupSource,
                    OriginalFileName,
                    FileType
                )
            OUTPUT INSERTED.BackupID
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            controller_id,
            project_id,
            str(backup_file),
            file_hash,
            "Recovery",
            backup_file.name,
            backup_file.suffix.lstrip(".").upper(),
        )
        backup_id = cursor.fetchone()[0]

        # Record recovery as incomplete and requiring an audit.
        # No verified comparison is claimed.
        cursor.execute(
            """
            INSERT INTO dbo.BackupComparisons
                (
                    ControllerID,
                    BackupID,
                    BackupSource,
                    ComparisonResult,
                    RetentionDecision,
                    TotalChanges,
                    FullProjectVerified,
                    AuditRequired,
                    ComparisonNotes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            controller_id,
            backup_id,
            "Recovery",
            "Incomplete",
            "Hold",
            None,
            0,
            1,
            "Recovered unregistered archive file; "
            "program comparison not verified.",
        )

        # Commit the backup and comparison records in one transaction.
        connection.commit()

        return backup_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




# STEP 46: RUN THE BACKUP INTEGRITY AUDIT DEMONSTRATION.
# READ-ONLY: NO BACKUPS WILL BE DELETED.

if __name__ == "__main__":

    controller_id = 1

    # Check registered backup files for missing or corrupted content.
    registered = audit_registered_backups(controller_id)

    # Locate backup files that do not have SQL registrations.
    unregistered = audit_unregistered_backups()

    # Display the status of each registered backup.
    print("\nREGISTERED BACKUPS")

    for record in registered:
        print(
            "Backup ID:", record["BackupID"],
            "| Status:", record["Status"]
        )

    # Count healthy files and display the audit summary.
    healthy = sum(
        1 for record in registered
        if record["Status"] == "Healthy"
    )

    print("\nTRACE BACKUP AUDIT")
    print("Registered:", len(registered))
    print("Healthy:", healthy)
    print("Unregistered:", len(unregistered))

    # Assert the specific one-backup demonstration test conditions.
    assert len(registered) == 1
    assert registered[0]["BackupID"] == 1
    assert registered[0]["Status"] == "Healthy"
    assert len(unregistered) == 0

    print("\nStep 82 passed: backup storage is clean.")







