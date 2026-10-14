# TRACE Development Workstation Setup
# Run in PowerShell from the folder containing this script:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Optional: -SqlServer '.\SQLEXPRESS' -Database 'TRACE' -CheckSqlConnection
# This script does not install SQL Server, change network settings, or store credentials.

[CmdletBinding()]
param(
    [string]$SqlServer = '.\SQLEXPRESS',
    [string]$Database = 'TRACE',
    [switch]$CheckSqlConnection
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Show-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Show-Warn([string]$Message) { Write-Warning $Message }

Show-Step 'Checking prerequisites'
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonLauncher) {
    throw 'Python launcher (py) was not found. Install Python for Windows, then reopen PowerShell.'
}
& py -3 --version
if ($LASTEXITCODE -ne 0) { throw 'Python 3 is not available through the py launcher.' }

Show-Step 'Creating or reusing a local Python virtual environment (.venv)'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create Python virtual environment.' }
}
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

Show-Step 'Updating pip in the virtual environment'
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }

Show-Step 'Installing TRACE Python packages'
if (Test-Path -LiteralPath 'requirements.txt') {
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
} else {
    Show-Warn 'requirements.txt not found. Skipping package installation. Export dependencies from the original development environment and commit requirements.txt.'
}

Show-Step 'Restoring VS Code extensions'
$codeCommand = Get-Command code -ErrorAction SilentlyContinue
if (-not $codeCommand) {
    Show-Warn 'VS Code command (code) not found. Install VS Code and enable its command-line launcher, then rerun this script.'
} elseif (Test-Path -LiteralPath 'vscode-extensions.txt') {
    $extensions = Get-Content -LiteralPath 'vscode-extensions.txt' |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith('#') } |
        Select-Object -Unique
    foreach ($extension in $extensions) {
        Write-Host "Installing VS Code extension: $extension"
        & code --install-extension $extension --force
        if ($LASTEXITCODE -ne 0) { Show-Warn "Could not install extension: $extension" }
    }
} else {
    Show-Warn 'vscode-extensions.txt not found. Skipping extension installation.'
}

Show-Step 'Checking SQL Server connectivity prerequisites'
$drivers = @()
try {
    $drivers = @(Get-OdbcDriver -ErrorAction Stop |
        Where-Object { $_.Name -match '^ODBC Driver (17|18) for SQL Server$' } |
        Select-Object -ExpandProperty Name -Unique)
} catch {
    Show-Warn "Unable to query installed ODBC drivers: $($_.Exception.Message)"
}
if ($drivers.Count -gt 0) {
    Write-Host "SQL Server ODBC driver(s) detected: $($drivers -join ', ')" -ForegroundColor Green
} else {
    Show-Warn 'Microsoft ODBC Driver 17 or 18 for SQL Server was not detected. Install a supported Microsoft SQL Server ODBC driver if TRACE requires pyodbc.'
}

if ($CheckSqlConnection) {
    Show-Step "Testing SQL Server connection to $SqlServer / $Database"
    $connection = $null
    try {
        Add-Type -AssemblyName System.Data
        $connectionString = "Server=$SqlServer;Database=$Database;Integrated Security=True;Connect Timeout=5;Encrypt=True;TrustServerCertificate=True;"
        $connection = New-Object System.Data.SqlClient.SqlConnection($connectionString)
        $connection.Open()
        Write-Host 'SQL Server connection succeeded using Windows authentication.' -ForegroundColor Green
    } catch {
        Show-Warn "SQL Server connection failed: $($_.Exception.Message)"
        Show-Warn 'Verify SQL Server Express installation, instance name, database, permissions, and network access. This test does not create or change a database.'
    } finally {
        if ($null -ne $connection) { $connection.Dispose() }
    }
} else {
    Write-Host 'SQL connection test skipped. Use -CheckSqlConnection to test with Windows authentication.'
}

Show-Step 'TRACE workstation setup finished'
Write-Host 'Python environment: .venv\Scripts\python.exe'
Write-Host 'Activate with: .\.venv\Scripts\Activate.ps1'
Write-Host 'Or launch directly with: .\.venv\Scripts\python.exe .\V0.011_Web.py'
Write-Host 'Note: SQL Server Express, the TRACE database, backup files, and PLC network access must be configured separately.'
