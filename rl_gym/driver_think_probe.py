"""driver_think_probe.py — Siemens experiment #1 (Bible Ch.30 item 4):
'give the driver more chances to think'. Clone the proven stock AVLlit run,
change ONLY the ADF maneuver h_max 0.01 -> 0.001 (10x the driver's thinking
rate), rerun, and compare dwell-phase chassis-accel chaos vs the original.
Stock FMU, stock everything - one variable."""
import json as _j, os as _o
_lc = {}
try:
    _lc = _j.load(open(_o.path.join(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))), 'vehicle_local.json')))
except Exception:
    pass
DATA_ROOT = _lc.get('data_root', 'C:/demo_data')

import os
import re
import shutil
import subprocess

SRC = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"
RUN = os.path.join(os.environ["TEMP"], "driver_think_run")

os.makedirs(RUN, exist_ok=True)
for f in (DECK, "custom_event_tipout_10.adf", "AVLlit_tipin_50pct.nam"):
    shutil.copy(os.path.join(SRC, f), RUN)

adf_path = os.path.join(RUN, "custom_event_tipout_10.adf")
adf = open(adf_path, encoding="utf-8", errors="replace").read()
# maneuvers list rows: 'MANEUVER_N'  <time>  <h_max>  <print_interval>
adf2, n = re.subn(r"(\'MANEUVER_\d+\'\s+\S+\s+)0\.01(\s+0\.01)", r"\g<1>0.001\g<2>", adf)
open(adf_path, "w", encoding="utf-8").write(adf2)
print(f"h_max 0.01 -> 0.001 in {n} maneuver rows")

deck_path = os.path.join(RUN, DECK)
text = open(deck_path, encoding="utf-8", errors="replace").read()
text, n1 = re.subn(r'"[^"]*custom_event_tipout_10\.adf"',
                   '"' + (RUN + "/custom_event_tipout_10.adf").replace("\\", "/") + '"', text)
open(deck_path, "w", encoding="utf-8").write(text)
print(f"adf re-pointed x{n1}")

env = os.environ.copy()
dirs = []
for m in re.finditer(r'"([A-Za-z]:[^"]+?\.dll)"', text, re.IGNORECASE):
    d = os.path.dirname(m.group(1).replace("/", os.sep))
    if os.path.isdir(d) and d not in dirs:
        dirs.append(d)
env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])

proc = subprocess.Popen([BAT, DECK], cwd=RUN, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, errors="replace", bufsize=1)
for line in proc.stdout:
    line = line.rstrip()
    if line and ("Time=" in line or "ERROR" in line):
        print(line, flush=True)
rc = proc.wait()
print("solver exit:", rc, "| run dir:", RUN)
