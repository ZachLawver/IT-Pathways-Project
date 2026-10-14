# STEP 200: VERIFY CONTROLLER BACKUP HISTORY.
# Read-only SQL query. No PLC communication.

import importlib.util

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
            b.BackupSource,
            b.FilePath,
            bc.ComparisonResult,
            bc.RetentionDecision
        FROM dbo.Backups AS b
        LEFT JOIN dbo.BackupComparisons AS bc
            ON bc.BackupID = b.BackupID
        WHERE b.ControllerID = ?
        ORDER BY b.BackupID
        """,
        1,
    )

    rows = cursor.fetchall()

    for row in rows:
        print("-" * 60)
        print("BackupID:", row[0])
        print("ControllerID:", row[1])
        print("ProjectID:", row[2])
        print("Source:", row[3])
        print("File:", row[4])
        print("Comparison:", row[5])
        print("Retention:", row[6])

    backup_ids = {row[0] for row in rows}

    assert 1 in backup_ids, "Original backup missing."
    assert 2 in backup_ids, "New backup missing."

    print("-" * 60)
    print("PASS: Both registered backups are present.")

finally:
    connection.close()