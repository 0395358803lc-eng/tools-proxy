$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetScript = Join-Path $ProjectDir 'Start-EmulatorWithProxy.ps1'
$StartupDir = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupDir 'Tools-Proxy-Supervisor.lnk'

if (-not (Test-Path $TargetScript)) {
    throw "Cannot find $TargetScript"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = 'powershell.exe'
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$TargetScript`""
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = 'Start tools-proxy supervisor at Windows logon'
$Shortcut.Save()

Write-Host "Startup shortcut created: $ShortcutPath"
Write-Host "Project directory: $ProjectDir"
