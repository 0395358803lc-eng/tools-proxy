$ErrorActionPreference = 'Stop'
$StartupDir = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupDir 'Tools-Proxy-Supervisor.lnk'
if (Test-Path $ShortcutPath) {
    Remove-Item -Force $ShortcutPath
    Write-Host "Removed $ShortcutPath"
} else {
    Write-Host 'Startup shortcut is not installed.'
}
