# master_queue_v6.ps1 - champion catalogue rerun with the symmetric delivery
# guarantee (Bible 30.16). Waits for the v5 queue (knee, stock) to release the
# solver, then reruns the champion's seven events. One solver at a time.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v6.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v6 armed (champion rerun, r_max guarantee); waiting for a free solver"
$quiet = 0
while ($quiet -lt 6) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
foreach ($ev in 'sweep_tipin_ladder','sweep_driveaway_20','sweep_driveaway_40','sweep_driveaway_70','sweep_driveaway_100','sweep_coast','sweep_brake') {
  Run "V6 champion $ev" @((Join-Path $gym 'sweep_run.py'), 'champion', $ev)
}
# knee coast on the 22.5 km/h coast end (its first pass relaunched from 3 km/h)
Run 'V6 knee_v2 sweep_coast' @((Join-Path $gym 'sweep_run.py'), 'knee_v2', 'sweep_coast')
Log "QUEUE V6 COMPLETE"
