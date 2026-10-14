# STEP 297: TRACE COMPARISON ENGINE
# Read-only comparison of PLC project files.

from pathlib import Path
import hashlib
# STEP 362: EXTRACT LADDER RUNGS FROM AN L5X PROJECT.
# Organizes each rung by task, program, routine, and rung number.
# Preserves the complete instruction text, including nested parentheses
# and parallel branches.

import xml.etree.ElementTree as ET


def extract_l5x_rungs(file_path):
    root = ET.parse(file_path).getroot()

    # Map programs to the tasks that schedule them.
    program_tasks = {}

    for task in root.findall(".//Tasks/Task"):
        task_name = task.get("Name", "Unknown Task")

        for scheduled in task.findall("./ScheduledPrograms/ScheduledProgram"):
            program_name = scheduled.get("Name")
            if program_name:
                program_tasks.setdefault(program_name, []).append(task_name)

    rungs = {}

    for program in root.findall(".//Programs/Program"):
        program_name = program.get("Name", "Unknown Program")
        task_names = program_tasks.get(program_name, ["Unscheduled"])

        for routine in program.findall("./Routines/Routine"):
            if routine.get("Type") != "RLL":
                continue

            routine_name = routine.get("Name", "Unknown Routine")

            for rung in routine.findall("./RLLContent/Rung"):
                rung_number = rung.get("Number")
                logic = rung.findtext("./Text", default="").strip()

                for task_name in task_names:
                    key = (
                        task_name,
                        program_name,
                        routine_name,
                        rung_number
                    )

                    rungs[key] = logic

    return rungs

# STEP 363: COMPARE TWO L5X PROJECTS AT THE RUNG LEVEL.
#
# PURPOSE:
# Identify ladder logic changes without comparing unrelated XML metadata.
#
# INPUTS:
# baseline_path - Previously accepted L5X backup.
# uploaded_path - New L5X project awaiting review.
#
# OUTPUT:
# A list of changes containing:
# - Task
# - Program
# - Routine
# - Rung number
# - Change type (Added, Removed, Modified)
# - Previous rung logic
# - New rung logic
#
# All instruction parentheses, operands, and parallel branches
# are preserved exactly as extracted from the L5X files.


def compare_l5x_rungs(baseline_path, uploaded_path):

    baseline_rungs = extract_l5x_rungs(baseline_path)
    uploaded_rungs = extract_l5x_rungs(uploaded_path)

    changes = []

    all_rung_keys = sorted(
        set(baseline_rungs) | set(uploaded_rungs),
        key=lambda key: (
            key[0],
            key[1],
            key[2],
            int(key[3]) if str(key[3]).isdigit() else -1
        )
    )

    for key in all_rung_keys:

        task_name, program_name, routine_name, rung_number = key

        previous_logic = baseline_rungs.get(key)
        new_logic = uploaded_rungs.get(key)

        if previous_logic == new_logic:
            continue

        if previous_logic is None:
            change_type = "Added"

        elif new_logic is None:
            change_type = "Removed"

        else:
            change_type = "Modified"

        changes.append({
            "task": task_name,
            "program": program_name,
            "routine": routine_name,
            "rung": rung_number,
            "change_type": change_type,
            "previous_logic": previous_logic or "",
            "new_logic": new_logic or ""
        })

    return changes

# STEP 381: IDENTIFY EXACT CHANGED SPANS WITHIN A RUNG.

import difflib


def highlight_rung_changes(previous_logic, new_logic):
    matcher = difflib.SequenceMatcher(
        None,
        previous_logic,
        new_logic,
        autojunk=False
    )

    previous_parts = []
    new_parts = []

    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        previous_text = previous_logic[old_start:old_end]
        new_text = new_logic[new_start:new_end]

        if operation == "equal":
            previous_parts.append((previous_text, False))
            new_parts.append((new_text, False))
        else:
            if previous_text:
                previous_parts.append((previous_text, True))
            if new_text:
                new_parts.append((new_text, True))

    return previous_parts, new_parts

def calculate_file_hash(file_path):
    """Calculate a SHA-256 hash of a project file."""

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def compare_project_files(file_a, file_b):
    """Determine whether two project files are identical."""

    file_a = Path(file_a)
    file_b = Path(file_b)

    if not file_a.is_file():
        raise FileNotFoundError(f"File not found: {file_a}")

    if not file_b.is_file():
        raise FileNotFoundError(f"File not found: {file_b}")

    hash_a = calculate_file_hash(file_a)
    hash_b = calculate_file_hash(file_b)

    return {
        "result": "IDENTICAL" if hash_a == hash_b else "DIFFERENT",
        "hash_a": hash_a,
        "hash_b": hash_b,
    }