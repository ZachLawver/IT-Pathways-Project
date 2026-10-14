# STEP 171: VERIFY BACKUP FILE INTEGRITY.
# Read-only. Does not modify backups, SQL, or the PLC.

import hashlib
from pathlib import Path
import pyodbc

connection = pyodbc.connect(
    r"DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=TRACE;"
    r"Trusted_Connection=yes;"
)

try:
    cursor = connection.cursor()

    cursor.execute("""
        SELECT FilePath, FileHash
        FROM dbo.Backups
        WHERE BackupID = 1
          AND ControllerID = 1
          AND ProjectID = 1
    """)

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Backup registration not found.")

    archive = Path(row.FilePath)

    if not archive.is_file():
        raise FileNotFoundError(archive)

    actual_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    stored_hash = row.FileHash

    print("Archive:", archive)
    print("Stored SHA-256:", stored_hash)
    print("Actual SHA-256:", actual_hash)

    if actual_hash.lower() == stored_hash.lower():
        print("PASS: Archived backup integrity verified.")
    else:
        print("FAIL: Archived file does not match SQL record.")

finally:
    connection.close()
    