# master_queue_v5.ps1 - sweep catalogue v5: every event starts from a STATIC
# standstill (driveaway family = four short events; coast and brake events
# end at the stop). Learned pair first, then stock. One solver at a time.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v5.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v5 armed; waiting for a free solver"
$quiet = 0
while ($quiet -lt 3) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
$events = 'sweep_driveaway_20','sweep_driveaway_40','sweep_driveaway_70','sweep_driveaway_100','sweep_coast','sweep_brake'
foreach ($ev in $events) { Run "V5 champion $ev" @((Join-Path $gym 'sweep_run.py'), 'champion', $ev) }
Run 'V5 knee_v2 sweep_tipin_ladder' @((Join-Path $gym 'sweep_run.py'), 'knee_v2', 'sweep_tipin_ladder')
foreach ($ev in $events) { Run "V5 knee_v2 $ev" @((Join-Path $gym 'sweep_run.py'), 'knee_v2', $ev) }
foreach ($ev in $events) { Run "V5 stock $ev" @((Join-Path $gym 'sweep_run.py'), 'stock', $ev) }
Log "QUEUE V5 COMPLETE"
