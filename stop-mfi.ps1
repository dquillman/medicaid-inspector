# stop-mfi.ps1 — stop the whole local Medicaid Inspector stack.
# Kills whatever is listening on the three dev ports (HAL/qcode, backend,
# frontend) by PID — never by process name, so it can't touch anything else.

param([int[]]$Ports = @(3000, 8001, 5200))

Write-Host "Stopping the Medicaid Inspector stack..."
foreach ($p in $Ports) {
  $line = netstat -ano | Select-String ":$p\s" | Select-String "LISTENING" | Select-Object -First 1
  if ($line) {
    $procId = ($line.ToString().Trim() -split '\s+')[-1]
    Write-Host ("  stopping port {0} (pid {1})" -f $p, $procId)
    taskkill /F /PID $procId /T 2>$null | Out-Null
  } else {
    Write-Host ("  port {0} already free" -f $p)
  }
}
Write-Host "Done."
