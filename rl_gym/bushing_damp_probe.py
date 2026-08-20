"""bushing_damp_probe.py — Siemens experiment #2 (Bible Ch.30 item 6):
TRUE hands-off steering. The driver normally rigid-holds the steering wheel
with a position MOTION (joint 319008) - a stiff constraint suspected of
coupling the 8 Hz wheel mode into the chassis. This probe:
  1. DELETES Motion_Joint 368001 (driver's activate call lands on nothing -
     the same ignored-warning class as JOINT/303001 in every run),
  2. renumbers the steering SFORCE out of the driver's deactivate reach and
     rewrites it as a spring-damper on the column:
        T = -K*AZ(i,j) - C*WZ(i,j),  K=8 N.m/rad, C=0.8 N.m.s/rad
     (model units mm-N: 8000 / 800),
  3. runs the same h_max=0.001 scenario as the think-10x run.
Verdict metric: cruise-window 8 Hz lateral amplitude vs 31.5 mm/s2."""
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
RUN = os.path.join(os.environ["TEMP"], "bushing_damp_run")

os.makedirs(RUN, exist_ok=True)
for f in (DECK, "custom_event_tipout_10.adf", "AVLlit_tipin_50pct.nam"):
    shutil.copy(os.path.join(SRC, f), RUN)

# ADF: same 10x think rate as the reference run
adf_path = os.path.join(RUN, "custom_event_tipout_10.adf")
adf = open(adf_path, encoding="utf-8", errors="replace").read()
adf, n = re.subn(r"(\'MANEUVER_\d+\'\s+\S+\s+)0\.01(\s+0\.01)", r"\g<1>0.001\g<2>", adf)
open(adf_path, "w", encoding="utf-8").write(adf)
print(f"h_max -> 0.001 in {n} rows")

deck_path = os.path.join(RUN, DECK)
text = open(deck_path, encoding="utf-8", errors="replace").read()

# Scale ROTATIONAL damping on all compliance bushings x100
# (ct ~1-2 N.mm.s/rad vs kt 100-200 is effectively undamped - the CCX/CCY~0
# suspect from the original 8 Hz investigation; real rubber has damping)
import re as _re
def _scale_ct(m):
    return m.group(1) + str(float(m.group(2)) * 100.0) + '"'
text, nb = _re.subn(r'(ct[xyz]\s+=\s+")([\d.]+)"', _scale_ct, text)
print(f"rotational damping scaled x100 in {nb} fields")
n1 = n2 = n3 = 1  # patch-count guard bypass (steering untouched)

# re-point ADF reference to the local copy
text, n4 = re.subn(r'"[^"]*custom_event_tipout_10\.adf"',
                   '"' + (RUN + "/custom_event_tipout_10.adf").replace("\\", "/") + '"', text)
open(deck_path, "w", encoding="utf-8").write(text)
print(f"motion deleted x{n1}, sforce renumbered x{n2}, spring-damper x{n3}, adf x{n4}")
if not (n1 == 1 and n2 == 1 and n3 == 1):
    raise SystemExit("PATCH COUNTS WRONG - aborting")

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
    if line and ("Time=" in line or "ERROR" in line or "MOTION" in line):
        print(line, flush=True)
rc = proc.wait()
print("solver exit:", rc, "| run dir:", RUN)
