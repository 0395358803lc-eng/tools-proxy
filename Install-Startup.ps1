# =====================================================================
#  Install-Startup.ps1
#  Dang ky Start-EmulatorWithProxy.ps1 chay tu dong khi dang nhap Windows.
#  Cach dung:  powershell -ExecutionPolicy Bypass -File Install-Startup.ps1
# =====================================================================
$ErrorActionPreference = 'Stop'

$scriptDir   = 'D:\doithontinthietbi\New folder'
$targetScript= Join-Path $scriptDir 'Start-EmulatorWithProxy.ps1'
$startupDir  = [Environment]::GetFolderPath('Startup')
$lnkPath     = Join-Path $startupDir 'Start-EmulatorWithProxy.lnk'

if (-not (Test-Path $targetScript)) {
    throw "Khong tim thay $targetScript"
}

# Tao shortcut (.lnk) trong Startup folder: khi dang nhap, chay bang powershell
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments  = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$targetScript`""
$lnk.WorkingDirectory = $scriptDir
$lnk.Description = 'Auto start Android emulator proxy bridge + Rooted_Phone'
$lnk.Save()

Write-Host "Da tao startup shortcut tai:"
Write-Host "  $lnkPath"
Write-Host ""
Write-Host "Lan dang nhap Windows TOI THI, emulator + bridge se tu dong chay."
Write-Host "De chay NGAY bay gio ma khong can dang nhap lai:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$targetScript`""
