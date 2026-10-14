# ==========================================================
# TRACE - PLC VERSION MANAGER - VERSION 0.009
# Compare ladder rung logic in Studio 5000 L5X or ACD files.
# Runtime tag values are not compared.
# ==========================================================

# STEP 1: IMPORT STANDARD PYTHON LIBRARIES.
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


# STEP 2: CONFIGURE THE TWO PROJECT FILES.
# Place files in the same folder as this script, or use full paths.
# Supported file types: .L5X and .ACD (when acd-tools supports the version).
# Change the two filenames below to select any supported combination.
# Examples: sample.ACD vs LANLOGIX.ACD, or sample.ACD vs sample.L5X.
folder = Path(__file__).resolve().parent
old_file = folder / "LANLOGIX.ACD"
new_file = folder / "LANLOGIXNEW.ACD"


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
# This uses the third-party acd-tools parser. Its results must be
# validated against L5X exports before relying on them for audits.
def extract_acd_rungs(filename):
    try:
        from acd.api import ImportProjectFromFile
    except ImportError as error:
        raise RuntimeError(
            "ACD parser unavailable. Install acd-tools and its dependencies."
        ) from error

    project = ImportProjectFromFile(str(filename)).import_project()
    rungs = {}

    # Some ACD parser versions expose names using private _name fields.
    for program in project.controller.programs:
        program_name = getattr(program, "_name", None) or getattr(program, "name", None)
        if program_name is None:
            raise RuntimeError("ACD parser did not provide a program name.")

        for routine in program.routines:
            routine_name = getattr(routine, "_name", None) or getattr(routine, "name", None)
            if routine_name is None:
                raise RuntimeError("ACD parser did not provide a routine name.")

            # Rung numbers are positional here; verify numbering against L5X.
            for index, rung in enumerate(routine.rungs):
                # String conversion reflects the parser's decoded representation.
                # If operands are shown as '?', comparison is incomplete.
                logic = str(rung).strip()
                if "?" in logic:
                    raise RuntimeError(
                        f"Incomplete ACD rung decoding: "
                        f"{program_name} / {routine_name} / rung {index}: {logic}"
                    )
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


# STEP 7: RUN THE COMPARISON AND PRINT RESULTS.
def main():
    print("TRACE - PLC VERSION MANAGER - v0.009")
    print("Original:", old_file.name, f"({old_file.suffix.upper()})")
    print("Modified:", new_file.name, f"({new_file.suffix.upper()})")

    original_rungs = extract_rungs(old_file)
    modified_rungs = extract_rungs(new_file)
    changes = compare_rungs(original_rungs, modified_rungs)

    for key, change_type, original, modified in changes:
        program, routine, rung_number = key
        print("\n" + "=" * 60)
        print(f"LOCATION: {program} / {routine} / Rung {rung_number}")
        print("CHANGE:", change_type)
        print("ORIGINAL:", original if original is not None else "[RUNG MISSING]")
        print("MODIFIED:", modified if modified is not None else "[RUNG MISSING]")

    print("\n" + "=" * 60)
    print("COMPARISON COMPLETE")
    print("Original rungs:", len(original_rungs))
    print("Modified rungs:", len(modified_rungs))
    print("Changed rung locations:", len(changes))
    print("Runtime variable values: NOT COMPARED")


# STEP 8: REPORT ERRORS WITHOUT CLAIMING A SUCCESSFUL COMPARISON.
if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nCOMPARISON FAILED: {error}", file=sys.stderr)
        sys.exit(1)
