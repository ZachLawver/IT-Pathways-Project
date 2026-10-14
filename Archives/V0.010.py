# ==========================================================
# TRACE - PLC VERSION MANAGER - VERSION 0.010
# Compare ladder rung logic in Studio 5000 L5X or ACD files.
# Save comparison results to Microsoft SQL Server Express.
# Runtime tag values are not compared.
# ==========================================================

# STEP 1: IMPORT STANDARD PYTHON LIBRARIES AND SQL CONNECTOR.
from pathlib import Path
import sys
import hashlib
import xml.etree.ElementTree as ET
import pyodbc


# STEP 2: CONFIGURE THE TWO PROJECT FILES AND CONTROLLER.
# Change these names to match your files and PLC identifier.
folder = Path(__file__).resolve().parent
old_file = folder / "LANLOGIX.ACD"
new_file = folder / "LANLogixNew.acd"
controller_name = "LANLOGIX"

# STEP 2A: CONFIGURE THE LOCAL DEVELOPMENT SQL SERVER.
# TrustServerCertificate is for local development only.
connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


# STEP 3: READ LADDER RUNGS FROM AN L5X EXPORT.
# Only rung instruction text is extracted. Tag values are ignored.
def extract_l5x_rungs(filename):
    root = ET.parse(filename).getroot()
    rungs = {}

    # Strip XML namespaces if the export contains them.
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]

    for program in root.findall("./Controller/Programs/Program"):
        program_name = program.get("Name", "")
        for routine in program.findall("./Routines/Routine"):
            routine_name = routine.get("Name", "")
            for rung in routine.findall("./RLLContent/Rung"):
                rung_number = rung.get("Number", "")
                logic = rung.findtext("Text", default="").strip()
                rungs[(program_name, routine_name, rung_number)] = logic

    return rungs


# STEP 4: READ LADDER RUNGS FROM A NATIVE ACD FILE.
# The third-party acd-tools parser is incomplete for some versions.
def extract_acd_rungs(filename):
    try:
        from acd.api import ImportProjectFromFile
    except ImportError as error:
        raise RuntimeError(
            "ACD parser unavailable. Install acd-tools and its dependencies."
        ) from error

    project = ImportProjectFromFile(str(filename)).import_project()
    rungs = {}

    for program in project.controller.programs:
        program_name = getattr(program, "_name", None) or getattr(program, "name", None)
        if program_name is None:
            raise RuntimeError("ACD parser did not provide a program name.")

        for routine in program.routines:
            routine_name = getattr(routine, "_name", None) or getattr(routine, "name", None)
            if routine_name is None:
                raise RuntimeError("ACD parser did not provide a routine name.")

            # Rung numbers are positional here; verify against L5X.
            for index, rung in enumerate(routine.rungs):
                logic = str(rung).strip()
                rungs[(str(program_name), str(routine_name), str(index))] = logic

    return rungs


# STEP 5: SELECT THE CORRECT READER FOR EACH FILE.
def extract_rungs(filename):
    if not filename.is_file():
        raise FileNotFoundError(f"Project file not found: {filename}")

    extension = filename.suffix.lower()
    if extension == ".l5x":
        return extract_l5x_rungs(filename)
    if extension == ".acd":
        return extract_acd_rungs(filename)
    raise ValueError(f"Unsupported file type: {filename.suffix}")


# STEP 6: COMPARE ALL RUNG LOCATIONS.
# Runtime tag values are never loaded into the comparison.
def compare_rungs(old_rungs, new_rungs):
    changes = []
    for key in sorted(set(old_rungs) | set(new_rungs)):
        original = old_rungs.get(key)
        modified = new_rungs.get(key)

        if original == modified:
            continue
        if original is None:
            change_type = "RUNG ADDED"
        elif modified is None:
            change_type = "RUNG REMOVED"
        else:
            change_type = "RUNG MODIFIED"

        changes.append((key, change_type, original, modified))
    return changes


# STEP 7: IDENTIFY POSSIBLY INCOMPLETE NATIVE ACD DECODING.
# '?' is a conservative warning, not definitive proof of missing data.
def find_uncertain_rungs(old_rungs, new_rungs):
    return sorted(
        key for key in set(old_rungs) | set(new_rungs)
        if (old_file.suffix.lower() == ".acd" and "?" in old_rungs.get(key, ""))
        or (new_file.suffix.lower() == ".acd" and "?" in new_rungs.get(key, ""))
    )


# STEP 8: CALCULATE A SHA-256 FILE HASH FOR BACKUP IDENTIFICATION.
# The hash identifies exact file bytes, not whether ladder logic changed.
def calculate_file_hash(filename):
    digest = hashlib.sha256()
    with filename.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# STEP 9: SAVE THE CONTROLLER, NEW FILE RECORD, AND RUNG CHANGES.
# One transaction ensures all records save together or none do.
# Re-running the same comparison creates a new audit event intentionally.
def save_comparison(changes, uncertain):
    connection = pyodbc.connect(connection_string, autocommit=False)
    cursor = connection.cursor()
    try:
        # STEP 9A: FIND OR CREATE THE CONTROLLER RECORD.
        # ControllerName is a human-assigned identifier for this demonstration.
        cursor.execute(
            "SELECT TOP (1) ControllerID FROM dbo.Controllers "
            "WHERE ControllerName = ? ORDER BY ControllerID",
            controller_name,
        )
        row = cursor.fetchone()
        if row:
            controller_id = row[0]
        else:
            cursor.execute(
                "INSERT INTO dbo.Controllers (ControllerName) "
                "OUTPUT INSERTED.ControllerID VALUES (?)",
                controller_name,
            )
            controller_id = cursor.fetchone()[0]

        # STEP 9B: REGISTER THE MODIFIED PROJECT FILE AS A BACKUP RECORD.
        # This records an existing local file; it does NOT create/upload a backup.
        cursor.execute(
            "INSERT INTO dbo.Backups (ControllerID, FilePath, FileHash) "
            "OUTPUT INSERTED.BackupID VALUES (?, ?, ?)",
            controller_id,
            str(new_file.resolve()),
            calculate_file_hash(new_file),
        )
        backup_id = cursor.fetchone()[0]

        # STEP 9C: RECORD EACH ADDED, REMOVED, OR MODIFIED RUNG.
        uncertain_set = set(uncertain)
        for key, change_type, original, modified in changes:
            program, routine, rung_number = key
            status = "UNVERIFIED" if key in uncertain_set else "VERIFIED"
            cursor.execute(
                "INSERT INTO dbo.RungChanges "
                "(BackupID, ProgramName, RoutineName, RungNumber, "
                "ChangeType, OldLogic, NewLogic, VerificationStatus) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                backup_id, program, routine, rung_number,
                change_type, original, modified, status,
            )

        # STEP 9D: COMMIT ONLY AFTER ALL INSERTS SUCCEED.
        connection.commit()
        return backup_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# STEP 10: RUN THE COMPARISON, PRINT RESULTS, AND SAVE TO SQL.
def main():
    print("TRACE - PLC VERSION MANAGER - v0.010")
    print("Original:", old_file.name, f"({old_file.suffix.upper()})")
    print("Modified:", new_file.name, f"({new_file.suffix.upper()})")
    print("Controller:", controller_name)

    original_rungs = extract_rungs(old_file)
    modified_rungs = extract_rungs(new_file)
    changes = compare_rungs(original_rungs, modified_rungs)
    uncertain = find_uncertain_rungs(original_rungs, modified_rungs)

    for key, change_type, original, modified in changes:
        program, routine, rung_number = key
        print("\n" + "=" * 60)
        print(f"LOCATION: {program} / {routine} / Rung {rung_number}")
        print("CHANGE:", change_type)
        print("ORIGINAL:", original if original is not None else "[RUNG MISSING]")
        print("MODIFIED:", modified if modified is not None else "[RUNG MISSING]")
        if key in uncertain:
            print("VERIFICATION: UNVERIFIED (possible incomplete ACD decoding)")

    print("\n" + "=" * 60)
    print("COMPARISON COMPLETE")
    print("Original rungs:", len(original_rungs))
    print("Modified rungs:", len(modified_rungs))
    print("Changed rung locations:", len(changes))
    print("Runtime variable values: NOT COMPARED")
    print("Rungs with possible incomplete ACD decoding:", len(uncertain))
    if uncertain:
        print("WARNING: Native ACD results are PARTIALLY VERIFIED.")
        print("Differences may be missed where instruction operands are undecoded.")
        for program, routine, rung_number in uncertain[:20]:
            print(f"  UNVERIFIED: {program} / {routine} / Rung {rung_number}")
        if len(uncertain) > 20:
            print(f"  ...and {len(uncertain) - 20} more unverified rungs.")

    # STEP 10A: SAVE RESULTS ONLY AFTER FILE COMPARISON COMPLETES.
    backup_id = save_comparison(changes, uncertain)
    print("\nSQL SERVER SAVE COMPLETE")
    print("Controller:", controller_name)
    print("BackupID:", backup_id)
    print("Rung change records saved:", len(changes))
    if uncertain:
        print("NOTE: Comparison is PARTIALLY VERIFIED; do not treat as clean audit.")


# STEP 11: REPORT ERRORS WITHOUT CLAIMING A SUCCESSFUL SAVE.
if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nTRACE v0.010 FAILED: {error}", file=sys.stderr)
        sys.exit(1)
