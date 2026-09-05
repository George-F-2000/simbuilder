# master_queue_v10.ps1 - after v9: rerun the knee tournament run (its v9 attempt
# failed in the analysis setup and hung to the 3 h kill), then the parity and
# catalogue tables. Waits for a free solver.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v10.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v10 armed; waiting for a free solver (behind v9)"
$quiet = 0
while ($quiet -lt 3) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
Run 'V10 tournament knee_v2 (rerun)' @((Join-Path $gym 'regen_run.py'), 'knee_v2')
Run 'V10 parity table' @((Join-Path $gym 'parity_table.py'))
Run 'V10 catalogue table' @((Join-Path $gym 'catalogue_table.py'))
Log "QUEUE V10 COMPLETE"
