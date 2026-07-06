# start-mfi.ps1 — one-shot launcher for the full local Medicaid Inspector stack
# (MFI backend + MFI frontend + the HAL assistant, which lives in the qcode app).
#
# Double-click "Start MFI.bat" (which runs this) and everything comes up:
#   1. frees the three ports so you always run the CURRENT code — no stale
#      dev server showing an old version badge or serving old bundles,
#   2. launches each server in its own minimized window,
#   3. waits until each is actually answering (the backend's first load can
#      take a minute), then opens the app in your browser.
#
# To stop everything: run stop-mfi.ps1, or just close the three minimized windows.

param(
  [string]$QcodeDir    = $(if ($env:MFI_QCODE_DIR)   { $env:MFI_QCODE_DIR }   else { "G:\Users\daveq\qcode" }),
  [string]$BackendDir  = $(if ($env:MFI_BACKEND_DIR) { $env:MFI_BACKEND_DIR } else { "G:\Users\daveq\medicaid inspector\backend" }),
  [string]$FrontendDir = $(if ($env:MFI_FRONTEND_DIR){ $env:MFI_FRONTEND_DIR }else { "G:\Users\daveq\medicaid inspector\frontend" }),
  [string]$Python      = $(if ($env:MFI_PYTHON)      { $env:MFI_PYTHON }      else { "G:\Python311\python.exe" }),
  [int]$QcodePort = 3000,
  [int]$BackendPort = 8001,
  [int]$FrontendPort = 5200
)

$ErrorActionPreference = "Continue"

function Get-PortPid([int]$Port) {
  $line = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING" | Select-Object -First 1
  if ($line) { return ($line.ToString().Trim() -split '\s+')[-1] }
  return $null
}

function Stop-Port([int]$Port) {
  $procId = Get-PortPid $Port
  if ($procId) {
    Write-Host ("  freeing port {0} (pid {1})" -f $Port, $procId)
    taskkill /F /PID $procId /T 2>$null | Out-Null
    Start-Sleep -Milliseconds 400
  }
}

function Start-Server([string]$Title, [string]$Dir, [string]$Command) {
  # Each server runs in its own minimized cmd window titled for easy spotting.
  $inner = "title $Title & cd /d `"$Dir`" & $Command"
  Start-Process -WindowStyle Minimized -FilePath "cmd.exe" -ArgumentList "/c", $inner | Out-Null
}

function Wait-Url([string]$Label, [string]$Url, [int]$TimeoutSec) {
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $TimeoutSec) {
    try {
      Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop | Out-Null
      return $true
    } catch {
      # A 401/404 still means the server is UP and answering — good enough.
      if ($_.Exception.Response) { return $true }
      Start-Sleep -Seconds 2
    }
  }
  return $false
}

Write-Host ""
Write-Host "  MEDICAID INSPECTOR - starting the local stack" -ForegroundColor Cyan
Write-Host "  ---------------------------------------------"

# 1. Free the ports so we always run the current code.
Write-Host "Clearing old servers..."
Stop-Port $QcodePort
Stop-Port $BackendPort
Stop-Port $FrontendPort

# 2. Launch each server.
Write-Host "Launching servers..."
Start-Server "HAL (qcode)"  $QcodeDir    "npm run dev"
Start-Server "MFI backend"  $BackendDir  "`"$Python`" -m uvicorn main:app --port $BackendPort"
Start-Server "MFI frontend" $FrontendDir "npm run dev"

# 3. Wait for each to answer.
Write-Host "Waiting for servers to come up (the backend's first load can take a minute)..."
$okQ = Wait-Url "HAL/qcode"    ("http://localhost:{0}/"       -f $QcodePort)    90
$okB = Wait-Url "MFI backend"  ("http://localhost:{0}/health" -f $BackendPort)  240
$okF = Wait-Url "MFI frontend" ("http://localhost:{0}/"       -f $FrontendPort) 90

function StatusLine([string]$Label, [bool]$Ok) {
  if ($Ok) { Write-Host ("  [ OK ] {0}" -f $Label) -ForegroundColor Green }
  else     { Write-Host ("  [FAIL] {0}" -f $Label) -ForegroundColor Red }
}
Write-Host ""
StatusLine "HAL (qcode)    :$QcodePort"  $okQ
StatusLine "MFI backend    :$BackendPort" $okB
StatusLine "MFI frontend   :$FrontendPort" $okF
Write-Host ""

# 4. Open the app.
if ($okF) {
  Start-Process ("http://localhost:{0}" -f $FrontendPort)
  Write-Host ("  App is open at http://localhost:{0}" -f $FrontendPort) -ForegroundColor Green
  if (-not $okQ) {
    Write-Host "  NOTE: HAL (qcode) did not come up - Ask HAL will show 'offline' until it does." -ForegroundColor Yellow
  }
} else {
  Write-Host "  The frontend did not come up. Check the minimized 'MFI frontend' window for errors." -ForegroundColor Red
}

Write-Host ""
Write-Host "  To stop everything: run stop-mfi.ps1, or close the three minimized windows."
Write-Host ""
