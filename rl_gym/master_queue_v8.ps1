# master_queue_v8.ps1 - after v7: champion coast rerun on the 3 km/h stop end
# (its v7 pass was clean through the lift and relaunch but failed in the final
# second of the stop, Bible 30.19e). Waits for a free solver.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v8.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v8 armed; waiting for a free solver (behind v7)"
$quiet = 0
while ($quiet -lt 6) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
Run 'V8 champion sweep_coast (clean stop end)' @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_coast')
Run 'V8 parity table' @((Join-Path $gym 'parity_table.py'))
Log "QUEUE V8 COMPLETE"
