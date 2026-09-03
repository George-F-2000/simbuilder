# master_queue.ps1 - "DO everything" (George, 2026-09-02). One solver at a time.
# Waits for the running champion sweep to finish, then:
#   B) three-entrant tournament rerun on the repaired road load (knee, champion, stock)
#   C) knee v2 sweeps (3 events)
#   D) stock sweeps (3 events, 1 ms driver step, slow)
# Every run is tolerant: a failure is logged and the queue continues.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
Log "master queue armed; waiting for the champion sweep chain to release the solver"
$quiet = 0
while ($quiet -lt 5) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
Log "solver free for 5 min - stage A2: champion driveaway family rerun (gentler stops)"
function Run($label, $args) {
  Log "--- $label"
  try {
    & $py -u @args 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Run 'A2 champion sweep_driveaway' @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_driveaway')
Run 'A3 champion sweep_tipin_ladder' @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_tipin_ladder')
Run 'A4 champion sweep_coast_brake' @((Join-Path $gym 'sweep_run.py'), 'champion', 'sweep_coast_brake')
Log "stage B (tournament rerun on repaired road load)"
Run 'B1 knee_v2 tip-in'   @((Join-Path $gym 'regen_run.py'), 'knee_v2')
Run 'B2 champion tip-in'  @((Join-Path $gym 'regen_run.py'), 'champion')
Run 'B3 stock tip-in'     @((Join-Path $gym 'regen_run.py'), 'stock')
Run 'B4 parity table'     @((Join-Path $gym 'parity_table.py'))
Log "stage C (knee v2 sweeps)"
foreach ($ev in 'sweep_driveaway','sweep_tipin_ladder','sweep_coast_brake') {
  Run "C knee_v2 $ev" @((Join-Path $gym 'sweep_run.py'), 'knee_v2', $ev)
}
Log "stage D (stock sweeps, 1 ms driver step)"
foreach ($ev in 'sweep_driveaway','sweep_tipin_ladder','sweep_coast_brake') {
  Run "D stock $ev" @((Join-Path $gym 'sweep_run.py'), 'stock', $ev)
}
Log "MASTER QUEUE COMPLETE"
