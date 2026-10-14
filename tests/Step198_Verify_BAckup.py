# STEP 198: VERIFY ARCHIVED BACKUP AND SQL REGISTRATION.
# Read-only. No PLC communication.

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backup_manager",
    "V0_019_Backup_Manager.py",
)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

connection = manager.connect_trace_database()

try:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            b.BackupID,
            b.ControllerID,
            b.ProjectID,
            b.FilePath,
            b.FileHash,
            bc.ComparisonID
        FROM dbo.Backups AS b
        LEFT JOIN dbo.BackupComparisons AS bc
            ON bc.BackupID = b.BackupID
        WHERE b.BackupID = ?
        """,
        2,
    )

    row = cursor.fetchone()

    if row is None:
        raise ValueError("BackupID 2 not found.")

    backup_id, controller_id, project_id, path, stored_hash, comparison_id = row

    archived = Path(path)

    print("BackupID:", backup_id)
    print("ControllerID:", controller_id)
    print("ProjectID:", project_id)
    print("ComparisonID:", comparison_id)
    print("Archived file:", archived)
    print("File exists:", archived.is_file())

    if not archived.is_file():
        raise FileNotFoundError(archived)

    hash_matches = (
        manager.calculate_file_hash(archived).lower()
        == stored_hash.lower()
    )

    print("SHA-256 matches SQL:", hash_matches)

    assert controller_id == 1
    assert project_id == 1
    assert comparison_id == 2
    assert hash_matches

    print("PASS: BackupID 2 verified.")

finally:
    connection.close()