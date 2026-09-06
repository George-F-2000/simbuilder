# master_queue_v11.ps1 - the catalogue on the plant with the 48/52 mass split, both axles at design height and the regularised brakes (Bible 30.28-30.29).
# front spring rate and both preloads; values recorded in plant_repairs.py and
# applied by sweep_run.py / regen_run.py). Learned pair first, then the
# driveaway families for all three, then stock's lift/brake events, then the
# tournament trio. Waits for a free solver. Failure-tolerant.
$py  = 'C:\Users\George\AppData\Local\Programs\Python\Python312\python.exe'
$gym = 'C:\Users\George\OneDrive\Desktop\PhD Thesis\pipeline-app\rl_gym'
$log = Join-Path $gym 'master_queue_v11.log'
function Log($s) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $s"; Add-Content $log $line -Encoding utf8; Write-Output $line }
function Run($label, $argv) {
  Log "--- $label"
  try {
    & $py -u @argv 2>&1 | ForEach-Object { Add-Content $log "    $_" -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "!!! $label exited $LASTEXITCODE" } else { Log "ok  $label" }
  } catch { Log "!!! $label threw: $_" }
}
Log "queue v11 armed; waiting for a free solver"
$quiet = 0
while ($quiet -lt 3) {
  if (Get-Process msolve -ErrorAction SilentlyContinue) { $quiet = 0 } else { $quiet++ }
  Start-Sleep -Seconds 60
}
$sweep = Join-Path $gym 'sweep_run.py'
foreach ($ent in @('champion', 'knee_v2')) {
  foreach ($ev in @('sweep_coast', 'sweep_tipin_ladder', 'sweep_brake')) { Run "V11 $ent $ev" @($sweep, $ent, $ev) }
}
foreach ($ev in @('sweep_driveaway_20', 'sweep_driveaway_40', 'sweep_driveaway_70', 'sweep_driveaway_100')) {
  foreach ($ent in @('champion', 'knee_v2', 'stock')) { Run "V11 $ent $ev" @($sweep, $ent, $ev) }
}
foreach ($ev in @('sweep_coast', 'sweep_tipin_ladder', 'sweep_brake')) { Run "V11 stock $ev" @($sweep, 'stock', $ev) }
Run 'V11 catalogue table' @((Join-Path $gym 'catalogue_table.py'))
foreach ($ent in @('champion', 'knee_v2', 'stock')) { Run "V11 tournament $ent" @((Join-Path $gym 'regen_run.py'), $ent) }
Run 'V11 parity table' @((Join-Path $gym 'parity_table.py'))
Log "QUEUE V11 COMPLETE"
