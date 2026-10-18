
# STEP 1: Import file handling, hashing, XML parsing, and comparison libraries.
from pathlib import Path
import hashlib

import xml.etree.ElementTree as ET


# STEP 2: Parse an L5X file and extract its ladder logic.
def extract_l5x_rungs(file_path):
    root = ET.parse(file_path).getroot()

# STEP 3: Associate each program with the tasks that schedule it.
    program_tasks = {}

    for task in root.findall(".//Tasks/Task"):
        task_name = task.get("Name", "Unknown Task")

        for scheduled in task.findall("./ScheduledPrograms/ScheduledProgram"):
            program_name = scheduled.get("Name")
            if program_name:
                program_tasks.setdefault(program_name, []).append(task_name)

# STEP 4: Identify ladder routines and index their rungs by location.
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



# STEP 5: Extract and compare rung dictionaries from two L5X projects.
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

# STEP 6: Classify each rung as added, removed, modified, or unchanged.
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


import difflib


# STEP 7: Identify changed character spans for visual highlighting.
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

# STEP 8: Calculate a SHA-256 fingerprint using one-megabyte file chunks.
def calculate_file_hash(file_path):
    """Calculate a SHA-256 hash of a project file."""

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


# STEP 9: Validate both project paths before comparing file hashes.
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

# STEP 10: Return the file comparison result and both SHA-256 hashes.
    return {
        "result": "IDENTICAL" if hash_a == hash_b else "DIFFERENT",
        "hash_a": hash_a,
        "hash_b": hash_b,
    }
