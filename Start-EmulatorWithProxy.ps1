param(
    [string]$AVD = 'Rooted_Phone'
)

# =====================================================================
#  Start-EmulatorWithProxy.ps1
#  Tu dong hoa hoan toan: bat bridge + mo emulator + dat proxy SOCKS5.
#  Dung chung cho BAT KY AVD nao (mac dinh: Rooted_Phone).
#
#  Cach dung:
#    powershell -NoProfile -ExecutionPolicy Bypass -File Start-EmulatorWithProxy.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File Start-EmulatorWithProxy.ps1 -AVD Small_Phone
#    powershell -NoProfile -ExecutionPolicy Bypass -File Start-EmulatorWithProxy.ps1 -AVD Spoofed_Phone
# =====================================================================
$ErrorActionPreference = 'Continue'

$SDK          = 'C:\Users\Admin\AppData\Local\Android\Sdk'
$ADB          = Join-Path $SDK 'platform-tools\adb.exe'
$EMULATOR     = Join-Path $SDK 'emulator\emulator.exe'
$BRIDGE_SCRIPT= 'D:\doithontinthietbi\New folder\http2socks_bridge.py'
$BRIDGE_PORT  = 8080
$PROXY_STR    = '10.0.2.2:8080'   # host gateway -> bridge (giong nhau moi AVD)

$log = 'D:\doithontinthietbi\New folder\startup.log'

function Log($msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

# ---------- 1) Dam bao bridge dang chay ----------
function Ensure-Bridge {
    $listening = Get-NetTCPConnection -LocalPort $BRIDGE_PORT -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        Log "Bridge da chay (PID $($listening.OwningProcess)) tren port $BRIDGE_PORT."
        return
    }
    Log "Bridge chua chay -> dang khoi dong python $BRIDGE_SCRIPT port $BRIDGE_PORT..."
    try {
        Start-Process -FilePath 'python' `
            -ArgumentList $BRIDGE_SCRIPT, "$BRIDGE_PORT" `
            -WorkingDirectory (Split-Path $BRIDGE_SCRIPT) `
            -WindowStyle Hidden `
            -RedirectStandardOutput 'D:\doithontinthietbi\New folder\bridge_out.log' `
            -RedirectStandardError  'D:\doithontinthietbi\New folder\bridge_err.log'
        Start-Sleep -Seconds 3
        $listen2 = Get-NetTCPConnection -LocalPort $BRIDGE_PORT -State Listen -ErrorAction SilentlyContinue
        if ($listen2) { Log "Bridge da san sang (PID $($listen2.OwningProcess))." }
        else          { Log "WARNING: Bridge khong len duoc port $BRIDGE_PORT." }
    } catch {
        Log "ERROR khoi dong bridge: $($_.Exception.Message)"
    }
}

# ---------- 2) Dam bao emulator dang chay ----------
function Ensure-Emulator {
    $dev = & $ADB devices 2>$null | Select-String -Pattern '^\S+\s+device$'
    if ($dev) {
        Log "Emulator da dang chay: $($dev.Line.Trim())"
        return
    }
    Log "Emulator chua chay -> dang khoi dong AVD '$AVD'..."
    try {
        Start-Process -FilePath $EMULATOR -ArgumentList "-avd", $AVD -WindowStyle Minimized
        Log "Da gui lenh khoi dong emulator $AVD."
    } catch {
        Log "ERROR khoi dong emulator: $($_.Exception.Message)"
    }
}

# ---------- 3) Cho emulator boot xong va dam bao proxy ----------
function Wait-BootAndProxy {
    $timeout = 180  # seconds
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $timeout) {
        $devs = & $ADB devices 2>$null
        $deviceLine = ($devs | Select-String -Pattern 'emulator-\d+\s+device$' | Select-Object -First 1)
        if ($deviceLine) {
            $serial = ($deviceLine.Line -split '\s+')[0]
            $boot = (& $ADB -s $serial shell getprop sys.boot_completed 2>$null).Trim()
            if ($boot -eq '1') {
                Log "Emulator $serial da boot xong."
                # Dam bao proxy duoc set (du bi reset cung se set lai)
                & $ADB -s $serial shell settings put global http_proxy $PROXY_STR 2>$null | Out-Null
                Start-Sleep -Seconds 1
                $cur = (& $ADB -s $serial shell settings get global http_proxy 2>$null).Trim()
                Log "Proxy da dat: $cur"
                return $serial
            }
        }
        Start-Sleep -Seconds 5
    }
    Log "WARNING: Emulator khong boot xong trong $timeout giay."
    return $null
}

# ---------- MAIN ----------
Log '===== Start-EmulatorWithProxy ====='
Ensure-Bridge
Ensure-Emulator
$serial = Wait-BootAndProxy
if ($serial) {
    Log "SAN SANG: proxy $PROXY_STR tren $serial. Dung de bat/tat emulator bat ky luc nao."
} else {
    Log 'Ket thuc: emulator chua san sang (khoi dong lai de thu lai).'
}
