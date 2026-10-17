
# ==========================================================
# TRACE - AUTOMATIC DATABASE INSTALLER - VERSION 0.013
# Creates the database and initial tables when missing.
# Does not delete existing data.
# ==========================================================

# STEP 1: IMPORT REQUIRED LIBRARIES.
import pyodbc
import os


# STEP 2: CONFIGURE SQL SERVER.
SERVER = os.environ.get("TRACE_SQL_SERVER", r"localhost\SQLEXPRESS")
DATABASE = "TRACE"

def connection_string(database):
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )


# STEP 3: CREATE THE DATABASE IF IT DOES NOT EXIST.
def create_database():
    connection = pyodbc.connect(
        connection_string("master"),
        timeout=5,
        autocommit=True
    )

    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM sys.databases WHERE name = ?",
            DATABASE
        )

        if cursor.fetchone():
            print("TRACE database already exists.")
        else:
            cursor.execute(f"CREATE DATABASE [{DATABASE}]")
            print("TRACE database created.")
    finally:
        connection.close()


# STEP 4: CREATE THE APPLICATION TABLES IF MISSING.
def create_tables():
    connection = pyodbc.connect(
        connection_string(DATABASE),
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 4A: CONTROLLER INVENTORY.
        cursor.execute("""
            IF OBJECT_ID(N'dbo.Controllers', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.Controllers (
                    ControllerID INT IDENTITY(1,1) PRIMARY KEY,
                    ControllerName NVARCHAR(100) NOT NULL,
                    IPAddress VARCHAR(45) NULL,
                    PLCModel NVARCHAR(100) NULL,
                    CreatedAt DATETIME2 NOT NULL
                        DEFAULT SYSDATETIME(),
                    ControllerFamily NVARCHAR(100) NULL,
                    FirmwareMajor INT NULL,
                    FirmwareMinor INT NULL,
                    SerialNumber NVARCHAR(100) NULL,
                    LastSeen DATETIME2 NULL,
                    CommunicationStatus NVARCHAR(30) NOT NULL
                        DEFAULT 'Not checked'
                )
            END
        """)

        # STEP 4B: BACKUP INVENTORY.
        cursor.execute("""
            IF OBJECT_ID(N'dbo.Backups', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.Backups (
                    BackupID INT IDENTITY(1,1) PRIMARY KEY,
                    ControllerID INT NOT NULL,
                    FilePath NVARCHAR(1000) NOT NULL,
                    FileHash CHAR(64) NULL,
                    BackupTime DATETIME2 NOT NULL
                        DEFAULT SYSDATETIME(),
                    BackupStatus NVARCHAR(30) NOT NULL
                        DEFAULT 'Pending',
                    BackupSource NVARCHAR(50) NOT NULL
                        DEFAULT 'ManualUpload',
                    OriginalFileName NVARCHAR(255) NULL,
                    FileType NVARCHAR(10) NULL,
                    ReviewedAt DATETIME2 NULL,
                    ReviewedBy NVARCHAR(150) NULL,
                    ReviewNotes NVARCHAR(1000) NULL,

                    CONSTRAINT FK_Backups_Controllers
                        FOREIGN KEY (ControllerID)
                        REFERENCES dbo.Controllers(ControllerID)
                )
            END
        """)

        cursor.execute("""
            IF OBJECT_ID(N'dbo.BackupComparisons', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.BackupComparisons (
                    ComparisonID INT IDENTITY(1,1) PRIMARY KEY,
                    ControllerID INT NOT NULL,
                    BackupID INT NULL,
                    BackupSource NVARCHAR(50) NOT NULL,
                    ComparisonResult NVARCHAR(30) NOT NULL,
                    RetentionDecision NVARCHAR(20) NOT NULL,
                    TotalChanges INT NULL,
                    FullProjectVerified BIT NOT NULL
                        DEFAULT 0,
                    AuditRequired BIT NOT NULL
                        DEFAULT 0,
                    PossibleMonitorMiss BIT NOT NULL
                        DEFAULT 0,
                    ComparedAt DATETIME2 NOT NULL
                        DEFAULT SYSUTCDATETIME(),
                    ComparisonNotes NVARCHAR(2000) NULL,

                    CONSTRAINT FK_BackupComparisons_Controller
                        FOREIGN KEY (ControllerID)
                        REFERENCES dbo.Controllers(ControllerID),

                    CONSTRAINT FK_BackupComparisons_Backup
                        FOREIGN KEY (BackupID)
                        REFERENCES dbo.Backups(BackupID)
                )
            END
        """)

        # STEP 4C: RUNG CHANGE HISTORY.
        cursor.execute("""
            IF OBJECT_ID(N'dbo.RungChanges', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.RungChanges (
                    ChangeID INT IDENTITY(1,1) PRIMARY KEY,
                    BackupID INT NOT NULL,
                    ProgramName NVARCHAR(255) NOT NULL,
                    RoutineName NVARCHAR(255) NOT NULL,
                    RungNumber NVARCHAR(50) NOT NULL,
                    ChangeType NVARCHAR(30) NOT NULL,
                    OldLogic NVARCHAR(MAX) NULL,
                    NewLogic NVARCHAR(MAX) NULL,
                    VerificationStatus NVARCHAR(30) NOT NULL
                        DEFAULT 'VERIFIED',
                    DetectedAt DATETIME2 NOT NULL
                        DEFAULT SYSDATETIME(),

                    CONSTRAINT FK_RungChanges_Backups
                        FOREIGN KEY (BackupID)
                        REFERENCES dbo.Backups(BackupID)
                )
            END
        """)

        # STEP 4D: ADD LIVE CONTROLLER MONITORING COLUMNS.
        # These statements update existing TRACE databases.
        # New databases receive the same columns automatically.

        cursor.execute("""
            IF COL_LENGTH('dbo.Controllers', 'FirmwareMajor') IS NULL
                ALTER TABLE dbo.Controllers
                ADD FirmwareMajor INT NULL;
        """)

        cursor.execute("""
            IF COL_LENGTH('dbo.Controllers', 'FirmwareMinor') IS NULL
                ALTER TABLE dbo.Controllers
                ADD FirmwareMinor INT NULL;
        """)

        cursor.execute("""
            IF COL_LENGTH('dbo.Controllers', 'SerialNumber') IS NULL
                ALTER TABLE dbo.Controllers
                ADD SerialNumber NVARCHAR(100) NULL;
        """)

        cursor.execute("""
            IF COL_LENGTH('dbo.Controllers', 'LastSeen') IS NULL
                ALTER TABLE dbo.Controllers
                ADD LastSeen DATETIME2 NULL;
        """)

        cursor.execute("""
            IF COL_LENGTH('dbo.Controllers', 'CommunicationStatus') IS NULL
                ALTER TABLE dbo.Controllers
                ADD CommunicationStatus NVARCHAR(30) NOT NULL
                    CONSTRAINT DF_Controllers_CommunicationStatus
                    DEFAULT 'Not checked';
        """)

        print("TRACE controller monitoring columns verified.")

        
        # STEP 4B: CREATE THE CONTROLLER HARDWARE HISTORY TABLE.
        # The Controllers table represents the machine or installation.
        # ControllerHardware represents physical PLC processors.
        # Replacing a processor creates a new hardware record without
        # deleting the previous processor or its equipment history.

        cursor.execute("""
            IF OBJECT_ID(N'dbo.ControllerHardware', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.ControllerHardware (
                    HardwareID INT IDENTITY(1,1) PRIMARY KEY,
                    ControllerID INT NOT NULL,
                    SerialNumber NVARCHAR(100) NOT NULL,
                    PLCModel NVARCHAR(100) NULL,
                    FirmwareMajor INT NULL,
                    FirmwareMinor INT NULL,
                    InstalledAt DATETIME2 NOT NULL
                        DEFAULT SYSUTCDATETIME(),
                    RemovedAt DATETIME2 NULL,
                    LastSeen DATETIME2 NULL,
                    InitialAuditValue NVARCHAR(255) NULL,

                    CONSTRAINT FK_ControllerHardware_Controllers
                        FOREIGN KEY (ControllerID)
                        REFERENCES dbo.Controllers(ControllerID)
                )
            END
        """)

        # STEP 4C: PREVENT MULTIPLE ACTIVE PROCESSORS
        # FROM BEING ASSIGNED TO THE SAME INSTALLATION.
        # A NULL RemovedAt means the processor is still installed.

        cursor.execute("""
            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE name = 'UX_ControllerHardware_ActiveInstallation'
                  AND object_id = OBJECT_ID('dbo.ControllerHardware')
            )
            BEGIN
                CREATE UNIQUE INDEX
                    UX_ControllerHardware_ActiveInstallation
                ON dbo.ControllerHardware (ControllerID)
                WHERE RemovedAt IS NULL
            END
        """)

        # STEP 4D: PREVENT ONE PHYSICAL PROCESSOR
        # FROM BEING ACTIVE IN MULTIPLE INSTALLATIONS.

        cursor.execute("""
            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE name = 'UX_ControllerHardware_ActiveSerial'
                  AND object_id = OBJECT_ID('dbo.ControllerHardware')
            )
            BEGIN
                CREATE UNIQUE INDEX
                    UX_ControllerHardware_ActiveSerial
                ON dbo.ControllerHardware (SerialNumber)
                WHERE RemovedAt IS NULL
            END
        """)

        # STEP 4E: CONFIRM HARDWARE TABLE SETUP.
        print("TRACE hardware history table verified.")
             
        # STEP 4F: CREATE THE HARDWARE EVENT HISTORY TABLE.
        # Stores processor replacement warnings and other
        # hardware events without changing equipment identity.

        cursor.execute("""
            IF OBJECT_ID(N'dbo.HardwareEvents', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.HardwareEvents (
                    EventID INT IDENTITY(1,1) PRIMARY KEY,
                    ControllerID INT NOT NULL,
                    EventType NVARCHAR(50) NOT NULL,
                    DetectedSerialNumber NVARCHAR(100) NULL,
                    DetectedIPAddress NVARCHAR(45) NULL,
                    EventStatus NVARCHAR(30) NOT NULL
                        DEFAULT 'Pending',
                    DetectedAt DATETIME2 NOT NULL
                        DEFAULT SYSUTCDATETIME(),
                    ResolvedAt DATETIME2 NULL,
                    ResolutionNotes NVARCHAR(1000) NULL,
                    ResolvedBy NVARCHAR(150) NULL,

                    CONSTRAINT FK_HardwareEvents_Controllers
                        FOREIGN KEY (ControllerID)
                        REFERENCES dbo.Controllers(ControllerID)
                )
            END
        """)

        # STEP 1: CHECK WHETHER THE RESOLVEDBY COLUMN EXISTS.
        # This allows older TRACE databases to be updated automatically.

        cursor.execute("""
            IF OBJECT_ID('dbo.HardwareEvents', 'U') IS NOT NULL
            AND COL_LENGTH('dbo.HardwareEvents', 'ResolvedBy') IS NULL
            BEGIN
                ALTER TABLE dbo.HardwareEvents
                ADD ResolvedBy NVARCHAR(150) NULL;
            END
        """)

        # STEP 2: SAVE THE DATABASE SCHEMA UPDATE.
        connection.commit()

        print("PASS: HardwareEvents technician attribution schema verified.")

        # STEP 4G: VERIFY THE HARDWARE EVENTS TABLE.
        print("TRACE hardware events table verified.")

        connection.commit()
        print("TRACE database tables verified.")
        
    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 5: INITIALIZE THE COMPLETE DATABASE.
def initialize_database():
    create_database()
    create_tables()
    print("TRACE database initialization complete.")


# STEP 6: RUN AS A STANDALONE INSTALLER.
if __name__ == "__main__":
    try:
        initialize_database()
    except pyodbc.Error as error:
        print(f"TRACE database setup failed: {error}")
        raise SystemExit(1)



