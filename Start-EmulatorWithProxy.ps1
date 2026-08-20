param(
    [string]$AVD = ''
)

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $ProjectDir 'app.py'
$Python = (Get-Command python -ErrorAction Stop).Source

function Write-ProxyLog([string]$Message) {
    $LogDir = Join-Path $ProjectDir 'logs'
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $LogFile = Join-Path $LogDir 'startup.log'
    $Line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
}

if ($AVD) {
    Write-ProxyLog "Boot request for AVD '$AVD'."
    & $Python $App boot $AVD
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to boot AVD '$AVD' (exit code $LASTEXITCODE)."
    }
}

$Existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($App) -and $_.CommandLine.Contains('supervisor') }

if ($Existing) {
    Write-ProxyLog "Supervisor is already running (PID $($Existing.ProcessId -join ','))."
    exit 0
}

$OutLog = Join-Path $ProjectDir 'logs\supervisor.out.log'
$ErrLog = Join-Path $ProjectDir 'logs\supervisor.err.log'
Write-ProxyLog 'Starting tools-proxy supervisor.'
Start-Process -FilePath $Python `
    -ArgumentList @($App, 'supervisor') `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog
