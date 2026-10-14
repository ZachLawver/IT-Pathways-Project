# PLC Version Manager - Version 0.006
# Automatic Backup and Local Git Version Control

from pathlib import Path
from datetime import datetime
import shutil
import subprocess

# Identify controller and the runtime values that should
# not trigger a new backup or Git revision

plc_name = "Conveyor_01"

ignored_tags = [
    "EncoderPosition",
    "MotorRunning"
]

# Create folders for full backups and normalized Git data
 
backup_folder = Path("backups")
backup_folder.mkdir(exist_ok=True)

git_data_folder = Path("git_data")
git_data_folder.mkdir(exist_ok=True)

# Read PLC text snapshot and convert its tag/value pairs
# into a Python dictionary for comparison

def read_plc_file(filename):
    plc_data = {}
    with open(filename, "r") as file:
        for line in file:
            line = line.strip()
            if "=" in line:
                tag, value = line.split("=", 1)
                plc_data[tag] = value
    return plc_data

# Remove ignored runtime tags and produce a consistent
# representation of meaningful PLC values.

def normalize_plc_data(plc_data):
    normalized = {}
    for tag in sorted(plc_data):
        if tag not in ignored_tags:
            normalized[tag] = plc_data[tag]
    return normalized

#Stage the normalized PLC file and create a Git commit.
#Git only receives the filtered data not raw snapshots.

def commit_to_git(file_path, message):
    subprocess.run(
        ["git", "add", str(file_path)],
        check=True
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        check=True
    )

#Find the latest saved backup for this PLC
backup_files = sorted(backup_folder.glob(f"{plc_name}_*.txt"))
new_file = Path("new_plc.txt")
if not new_file.exists():
    raise
FileNotFoundError("new_plc.txt was not found")
new_data = read_plc_file(new_file)
if backup_files:
    old_data = read_plc_file(backup_files[-1])
else:
    old_data = None

# Ignore runtime values and detect additions, deletions, 
# or modifications to the remaining tag values.

new_normalized = normalize_plc_data(new_data)
changes = []
if old_data is None:
    changes.append("Initial backup")
else:
    old_normalized = normalize_plc_data(old_data)
    for tag in sorted(set(old_normalized) | set(new_normalized)):
        old_value = old_normalized.get(tag)
        new_value = new_normalized.get(tag)
        if old_value != new_value:
            changes.append(f"{tag}: {old_value} -> {new_value}")

# Create a timestamped full snapshot and update the
# normalized file that Git will track

if changes:
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Generate backup filename
    backup_path = backup_folder / f"{plc_name}_{timestamp}.txt"
    shutil.copy2(new_file, backup_path)
    normalized_path = git_data_folder / f"{plc_name}.txt"
    with open(normalized_path, "w") as file:
        for tag, value in new_normalized.items():
            file.write(f"{tag}={value}\n")
    print("MENAINGFUL CHANGES DETECTED")
    for change in changes:
        print(change)

    # Save the meaningful PLC state in local Git history
    commit_message = (
        f"{plc_name} backup {timestamp} - "
        f"{len(changes)} change(s)"
    )
    commit_to_git(normalized_path, commit_message)
    print("BACKUP SAVED:", backup_path)
    print("GIT COMMIT CREATED")
else:
    print("NO MEANINGFUL CHANGES")
    print("DECISION: NO NEW BACKUP")