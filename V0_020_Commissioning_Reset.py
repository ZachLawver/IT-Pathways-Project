# STEP 1: Import filesystem and SQL connectivity libraries.
from pathlib import Path
import pyodbc



# STEP 2: Define the operational SQL tables cleared during commissioning reset.
RESET_TABLES = (
    "BackupComparisons",
    "RungChanges",
    "HardwareEvents",
    "Backups",
    "ControllerHardware",
    "Controllers",
)


# STEP 3: Validate reset targets without deleting records or files.
def validate_reset_targets(connection_string, backup_root):
    """
    Validate commissioning reset targets.
    READ-ONLY: Does not delete SQL records or files.
    """

    # STEP 4: Resolve the backup directory to its absolute filesystem path.
    backup_root = Path(backup_root).resolve()

    if backup_root != Path(r"C:\TRACE_Backups"):
        raise ValueError(
            f"Unexpected backup directory: {backup_root}"
        )

    if not backup_root.is_dir():
        raise FileNotFoundError(
            f"TRACE backup directory does not exist: {backup_root}"
        )

    # STEP 5: Connect to SQL Server and verify the TRACE database.
    connection = pyodbc.connect(
        connection_string,
        timeout=5
    )

    try:
        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME()")
        database_name = cursor.fetchone()[0]

        if database_name != "TRACE":
            raise ValueError(
                f"Unexpected SQL database: {database_name}"
            )

        # STEP 6: Count existing operational records before allowing reset.
        counts = {}

        for table in RESET_TABLES:
            cursor.execute(
                f"SELECT COUNT(*) FROM dbo.{table}"
            )
            counts[table] = cursor.fetchone()[0]

        return {
            "database": database_name,
            "backup_root": str(backup_root),
            "table_counts": counts,
        }

    finally:
        connection.close()


# STEP 7: Begin the destructive reset only after explicit confirmation.
def execute_commissioning_reset(connection_string, backup_root):
    """
    Reset TRACE's operational SQL records and backup storage.
    Destructive: call only after explicit user confirmation.
    Never communicates with a physical PLC.
    """
    import shutil

    validate_reset_targets(connection_string, backup_root)

    backup_root = Path(backup_root).resolve()

    # STEP 8: Reject symbolic links before starting destructive operations.
    for item in backup_root.iterdir():
        if item.is_symlink():
            raise ValueError(
                f"Refusing to reset symbolic link: {item}"
            )

    connection = pyodbc.connect(
        connection_string,
        timeout=5,
        autocommit=False
    )

    try:
        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME()")
        if cursor.fetchone()[0] != "TRACE":
            raise ValueError("Database changed before reset.")

        # STEP 9: Delete operational SQL records in dependency order.
        for table in RESET_TABLES:
            cursor.execute(f"DELETE FROM dbo.{table}")

        for table in RESET_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM dbo.{table}")
            if cursor.fetchone()[0] != 0:
                raise RuntimeError(
                    f"SQL reset verification failed: {table}"
                )

        # STEP 10: Commit verified SQL deletions or roll back on failure.
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    try:
        for item in backup_root.iterdir():
            if item.is_symlink():
                raise ValueError(
                    f"Refusing to remove symbolic link: {item}"
                )

            if item.is_dir():
                # STEP 11: Remove stored backup files after the SQL transaction succeeds.
                shutil.rmtree(item)
            else:
                item.unlink()

    except Exception as error:
        raise RuntimeError(
            "SQL reset completed, but backup cleanup failed. "
            f"Manual inspection required: {error}"
        ) from error

    # STEP 12: Verify SQL tables and backup storage are empty after reset.
    result = validate_reset_targets(
        connection_string,
        backup_root
    )

    if any(result["table_counts"].values()):
        raise RuntimeError(
            "Reset verification failed: SQL records remain."
        )

    if any(backup_root.iterdir()):
        raise RuntimeError(
            "Reset verification failed: backup files remain."
        )

    return result
