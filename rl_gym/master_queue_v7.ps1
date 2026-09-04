# master_queue_v7.ps1 - the catalogue on the regen-slip-limited deck (Bible 30.19).
# Every lift-off event reruns for every entrant with the deck-level limiter;
# the tournament reruns as a control (expected unchanged); driveaways last.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v7.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v7 armed (regen slip limiter); waiting for a free solver"
$quiet = 0
while ($quiet -lt 6) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
foreach ($ev in 'sweep_coast','sweep_tipin_ladder','sweep_brake') { Run "V7 champion $ev" @((Join-Path $gym 'sweep_run.py'), 'champion', $ev) }
foreach ($ev in 'sweep_coast','sweep_tipin_ladder','sweep_brake') { Run "V7 knee_v2 $ev" @((Join-Path $gym 'sweep_run.py'), 'knee_v2', $ev) }
foreach ($ev in 'sweep_coast','sweep_tipin_ladder','sweep_brake') { Run "V7 stock $ev" @((Join-Path $gym 'sweep_run.py'), 'stock', $ev) }
foreach ($ent in 'champion','knee_v2','stock') { Run "V7 $ent tip-in (tournament control)" @((Join-Path $gym 'regen_run.py'), $ent) }
Run 'V7 parity table' @((Join-Path $gym 'parity_table.py'))
foreach ($ent in 'champion','knee_v2','stock') {
  foreach ($ev in 'sweep_driveaway_20','sweep_driveaway_40','sweep_driveaway_70','sweep_driveaway_100') { Run "V7 $ent $ev" @((Join-Path $gym 'sweep_run.py'), $ent, $ev) }
}
Log "QUEUE V7 COMPLETE"
