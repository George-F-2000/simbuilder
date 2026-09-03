# master_queue_v3.ps1 - finish the sweep program (2026-09-03 evening).
# Ladders are valid for all entrants and the tournament is banked; this runs
# the v3 driveaway + coast/brake events for the learned pair, then stock's
# driveaway family (1 ms driver step, ~11 h, 15 h timeout). One solver at a time.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v3.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v3 armed; waiting for a free solver"
$quiet = 0
while ($quiet -lt 3) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
Run 'V3-1 champion sweep_driveaway'   @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_driveaway')
Run 'V3-2 champion sweep_coast_brake' @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_coast_brake')
Run 'V3-3 knee_v2 sweep_driveaway'    @((Join-Path $gym 'sweep_run.py'), 'knee_v2', 'sweep_driveaway')
Run 'V3-4 knee_v2 sweep_coast_brake'  @((Join-Path $gym 'sweep_run.py'), 'knee_v2', 'sweep_coast_brake')
Run 'V3-5 stock sweep_driveaway'      @((Join-Path $gym 'sweep_run.py'), 'stock', 'sweep_driveaway')
Log "QUEUE V3 COMPLETE"
