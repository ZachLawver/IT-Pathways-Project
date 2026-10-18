from pathlib import Path
import pyodbc


# TRACE COMMISSIONING RESET
# This module must never communicate with a physical PLC.

RESET_TABLES = (
    "BackupComparisons",
    "RungChanges",
    "HardwareEvents",
    "Backups",
    "ControllerHardware",
    "Controllers",
)


def validate_reset_targets(connection_string, backup_root):
    """
    Validate commissioning reset targets.
    READ-ONLY: Does not delete SQL records or files.
    """

    backup_root = Path(backup_root).resolve()

    if backup_root != Path(r"C:\TRACE_Backups"):
        raise ValueError(
            f"Unexpected backup directory: {backup_root}"
        )

    if not backup_root.is_dir():
        raise FileNotFoundError(
            f"TRACE backup directory does not exist: {backup_root}"
        )

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


def execute_commissioning_reset(connection_string, backup_root):
    """
    Reset TRACE's operational SQL records and backup storage.
    Destructive: call only after explicit user confirmation.
    Never communicates with a physical PLC.
    """
    import shutil

    # Validate both targets before modifying anything.
    validate_reset_targets(connection_string, backup_root)

    backup_root = Path(backup_root).resolve()

    # Reject unexpected filesystem entries before starting.
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

        # SQL deletion order preserves foreign-key dependencies.
        for table in RESET_TABLES:
            cursor.execute(f"DELETE FROM dbo.{table}")

        # Verify every operational table is empty before commit.
        for table in RESET_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM dbo.{table}")
            if cursor.fetchone()[0] != 0:
                raise RuntimeError(
                    f"SQL reset verification failed: {table}"
                )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    # SQL is committed before filesystem cleanup.
    # A filesystem error must be reported as an incomplete reset.
    try:
        for item in backup_root.iterdir():
            if item.is_symlink():
                raise ValueError(
                    f"Refusing to remove symbolic link: {item}"
                )

            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    except Exception as error:
        raise RuntimeError(
            "SQL reset completed, but backup cleanup failed. "
            f"Manual inspection required: {error}"
        ) from error

    # Final verification.
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
