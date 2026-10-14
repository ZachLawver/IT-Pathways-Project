# STEP 199: VERIFY BACKUP COMPARISON AND RETENTION.
# Read-only SQL verification.

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
            BackupSource,
            ComparisonResult,
            RetentionDecision,
            FullProjectVerified,
            AuditRequired
        FROM dbo.BackupComparisons
        WHERE BackupID = ?
        """,
        2,
    )

    row = cursor.fetchone()

    if row is None:
        raise ValueError("Comparison record not found.")

    labels = [
        "BackupSource",
        "ComparisonResult",
        "RetentionDecision",
        "FullProjectVerified",
        "AuditRequired",
    ]

    for label, value in zip(labels, row):
        print(f"{label}: {value}")

    assert tuple(row) == (
        "Manual",
        "Incomplete",
        "Retain",
        False,
        True,
    )

    print("PASS: Backup comparison and retention verified.")

finally:
    connection.close()