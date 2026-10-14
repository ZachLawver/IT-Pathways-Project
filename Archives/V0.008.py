
# ==========================================================
# PLC VERSION MANAGER - VERSION 0.008
# Offline comparison of two Studio 5000 L5X files
# ==========================================================

# STEP 1: IMPORT LIBRARIES
# pathlib handles file locations.
# ElementTree reads Rockwell XML.
# re identifies AFI instructions.

from pathlib import Path
import xml.etree.ElementTree as ET
import re


# STEP 2: CONFIGURE PROJECT FILES
# These are offline exports, not live PLC connections.
# Neither original nor modified file will be changed.

folder = Path(__file__).resolve().parent

old_file = folder / "VPIII_PLC.L5X"
new_file = folder / "VPIII_PLC_Modified.L5X"


# STEP 3: EXTRACT LADDER LOGIC
# Build a dictionary containing each rung's location
# and its ladder instruction text.
# A unique key combines program, routine, and rung number.

def extract_rungs(filename):
    root = ET.parse(filename).getroot()
    rungs = {}

    for program in root.findall("./Controller/Programs/Program"):
        program_name = program.get("Name")

        for routine in program.findall("./Routines/Routine"):
            routine_name = routine.get("Name")

            for rung in routine.findall("./RLLContent/Rung"):
                rung_number = rung.get("Number")
                logic = rung.findtext("Text", default="").strip()

                key = (program_name, routine_name, rung_number)
                rungs[key] = logic

    return rungs


# STEP 4: LOAD BOTH PROJECT REVISIONS
# Convert each XML file into a dictionary of rungs.

old_rungs = extract_rungs(old_file)
new_rungs = extract_rungs(new_file)

# STEP 5: COMPARE EVERY RUNG
# Compare all locations in either revision.
# Report added, deleted, and modified rungs.

changes = []

for key in sorted(set(old_rungs) | set(new_rungs)):
    old_logic = old_rungs.get(key)
    new_logic = new_rungs.get(key)

    if old_logic == new_logic:
        continue

    if old_logic is None:
        change_type = "RUNG ADDED"
    elif new_logic is None:
        change_type = "RUNG REMOVED"
    else:
        change_type = "RUNG MODIFIED"

    changes.append((key, change_type, old_logic, new_logic))


# STEP 6: DISPLAY ALL CHANGED RUNG LOCATIONS
# Identify each modified rung and count AFI instructions.
# Report the exact program, routine, and rung number.

afi_added_locations = []
afi_removed_locations = []

for key, change_type, old_logic, new_logic in changes:
    program, routine, rung = key

    old_afi = len(re.findall(r"\bAFI\s*\(", old_logic or "", re.I))
    new_afi = len(re.findall(r"\bAFI\s*\(", new_logic or "", re.I))

    print("\n" + "=" * 60)
    print(f"LOCATION: {program} / {routine} / Rung {rung}")
    print("CHANGE:", change_type)

    print("\nORIGINAL:")
    print(old_logic if old_logic is not None else "[RUNG MISSING]")

    print("\nMODIFIED:")
    print(new_logic if new_logic is not None else "[RUNG MISSING]")

    if new_afi > old_afi:
        afi_added_locations.append((program, routine, rung))
        print("\nALERT: AFI ADDED")

    elif new_afi < old_afi:
        afi_removed_locations.append((program, routine, rung))
        print("\nALERT: AFI REMOVED")


# STEP 6A: DISPLAY AFI CHANGE SUMMARY
# List all locations containing newly added or removed AFIs.

print("\n" + "=" * 60)
print("AFI CHANGE SUMMARY")

print("\nAFI ADDED:", len(afi_added_locations))
for program, routine, rung in afi_added_locations:
    print(f"  {program} / {routine} / Rung {rung}")

print("\nAFI REMOVED:", len(afi_removed_locations))
for program, routine, rung in afi_removed_locations:
    print(f"  {program} / {routine} / Rung {rung}")


# STEP 6: DISPLAY CHANGES
# Show the exact program, routine, and rung.
# Identify whether AFI instructions were added or removed.

print("\nPLC VERSION MANAGER - v0.008")
print("Old project:", old_file.name)
print("New project:", new_file.name)
print("Rungs changed:", len(changes))

for key, change_type, old_logic, new_logic in changes:
    program, routine, rung = key

    print("\n" + "=" * 60)
    print("PROGRAM:", program)
    print("ROUTINE:", routine)
    print("RUNG:", rung)
    print("CHANGE:", change_type)

    print("\nORIGINAL:")
    print(old_logic if old_logic is not None else "[RUNG MISSING]")

    print("\nMODIFIED:")
    print(new_logic if new_logic is not None else "[RUNG MISSING]")

    old_afi = len(re.findall(r"\bAFI\s*\(", old_logic or "", re.I))
    new_afi = len(re.findall(r"\bAFI\s*\(", new_logic or "", re.I))

    if new_afi > old_afi:
        print("\nALERT: AFI ADDED")
    elif new_afi < old_afi:
        print("\nALERT: AFI REMOVED")


# STEP 7: DISPLAY FINAL SUMMARY
# Give a clear result even if no differences exist.

print("\n" + "=" * 60)
print("COMPARISON COMPLETE")
print("Total changed rung locations:", len(changes))

