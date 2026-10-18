# TRACE - DATABASE INSTALLER - VERSION 0.013
# Sequential study annotations explain the database initialization process.
# Existing database records are preserved.



# STEP 1: Import the libraries used for SQL Server connections and configuration.
import pyodbc
import os


# STEP 2: Configure the SQL Server instance and TRACE database name.
SERVER = os.environ.get("TRACE_SQL_SERVER", r"localhost\SQLEXPRESS")
DATABASE = "TRACE"

# STEP 3: Build the ODBC connection string using Windows authentication.
def connection_string(database):
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )


# STEP 4: Create the TRACE database if it does not already exist.
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


# STEP 5: Connect to TRACE and verify the application database schema.
def create_tables():
    connection = pyodbc.connect(
        connection_string(DATABASE),
        timeout=5
    )

    try:
        cursor = connection.cursor()

        # STEP 6: Create the controller inventory table.
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

        # STEP 7: Create the backup inventory and retention history table.
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

        # STEP 8: Create the comparison results and audit history table.
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

        # STEP 9: Create the ladder logic change history table.
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


        # STEP 10: Add monitoring columns required by older database versions.
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

        

        # STEP 11: Create the physical processor installation history table.
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


        # STEP 12: Enforce one active processor per installation.
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


        # STEP 13: Prevent a processor from being active in multiple installations.
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

        print("TRACE hardware history table verified.")
             

        # STEP 14: Create the hardware detection and resolution event table.
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


        # STEP 15: Add technician attribution to older hardware event tables.
        cursor.execute("""
            IF OBJECT_ID('dbo.HardwareEvents', 'U') IS NOT NULL
            AND COL_LENGTH('dbo.HardwareEvents', 'ResolvedBy') IS NULL
            BEGIN
                ALTER TABLE dbo.HardwareEvents
                ADD ResolvedBy NVARCHAR(150) NULL;
            END
        """)

        connection.commit()

        print("PASS: HardwareEvents technician attribution schema verified.")

        print("TRACE hardware events table verified.")

        # STEP 16: Commit the final schema updates.
        connection.commit()
        print("TRACE database tables verified.")
        
    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# STEP 17: Initialize the database and verify its application tables.
def initialize_database():
    create_database()
    create_tables()
    print("TRACE database initialization complete.")


# STEP 18: Run the database installer when executed directly.
if __name__ == "__main__":
    try:
        initialize_database()
    except pyodbc.Error as error:
        print(f"TRACE database setup failed: {error}")
        raise SystemExit(1)



