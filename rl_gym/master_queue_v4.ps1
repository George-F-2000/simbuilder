# master_queue_v4.ps1 - learned pair on the RE-MEASURED demand law (Bible 30.13),
# then stock's driveaway family. One solver at a time; failure-tolerant.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v4.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v4 armed (re-measured law); waiting for a free solver"
$quiet = 0
while ($quiet -lt 3) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
Run 'V4-1 champion tip-in (tournament)'  @((Join-Path $gym 'regen_run.py'), 'champion')
Run 'V4-2 knee_v2 tip-in (tournament)'   @((Join-Path $gym 'regen_run.py'), 'knee_v2')
Run 'V4-3 parity table'                  @((Join-Path $gym 'parity_table.py'))
foreach ($ev in 'sweep_driveaway','sweep_tipin_ladder','sweep_coast_brake') {
  Run "V4 champion $ev" @((Join-Path $gym 'sweep_run.py'), 'champion', $ev)
}
foreach ($ev in 'sweep_driveaway','sweep_tipin_ladder','sweep_coast_brake') {
  Run "V4 knee_v2 $ev" @((Join-Path $gym 'sweep_run.py'), 'knee_v2', $ev)
}
Run 'V4-10 stock sweep_driveaway (15 h cap)' @((Join-Path $gym 'sweep_run.py'), 'stock', 'sweep_driveaway')
Log "QUEUE V4 COMPLETE"
