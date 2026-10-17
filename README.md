# TRACE — Installation and Demonstration Guide

## Overview

TRACE is a local Flask-based demonstration application for PLC discovery, controller auditing, L5X comparison, and manual backup retention decisions.

## Requirements

- Windows 10 or 11
- Python 3 with the Windows `py` launcher
- SQL Server Express
- Microsoft ODBC Driver 18 for SQL Server
- Network access to PLCs for live discovery and auditing
- VS Code (optional)

## Installation

1. Copy the TRACE project folder to the new computer.
2. Install Python, SQL Server Express, and ODBC Driver 18.
3. Open PowerShell in the TRACE project folder.
4. Run:

   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -CheckSqlConnection

5. Initialize the database:

   .\.venv\Scripts\python.exe .\V0_013_Database_Setup.py

The database installer creates missing database objects without dropping existing tables or deleting existing records.

## Configuration

Default SQL Server: localhost\SQLEXPRESS

Default backup directory: C:\TRACE_Backups

For a different SQL Server, set the environment variable in the PowerShell session before launching TRACE:

   $env:TRACE_SQL_SERVER = 'SERVERNAME\INSTANCE'

For a different backup directory:

   $env:TRACE_BACKUP_ROOT = 'D:\TRACE_Backups'

These settings must be applied to each new PowerShell session unless configured persistently in Windows.

## Launch TRACE

Run:

   .\.venv\Scripts\python.exe .\V0.011_Web.py

Open:

   http://127.0.0.1:5000/demo

Press Ctrl+C in PowerShell to stop the server.

## Demonstration Features

- Network discovery and controller selection
- Initial controller audit registration and checking
- Manual L5X upload and comparison
- Changed-rung highlighting and ladder visualization
- Manual retention or discard of pending backups

Live discovery and auditing require access to compatible PLC hardware.

## Backup Safety

TRACE keeps pending files separate from accepted backups.

Manual discard removes only the selected pending file.

Automatic backup deletion remains disabled because complete PLC project equivalence has not been verified.

## Important Limitations

- The Flask server is intended for local development and demonstration, not production hosting.
- SQL Server Express and ODBC Driver 18 must be installed separately.
- PLC communication requires suitable network connectivity and controller compatibility.
- The database installer does not install SQL Server itself.
- Keep an independent copy of the original project and PLC backups.
