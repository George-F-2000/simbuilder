"""driveaway_run.py — TRUE driveaway event on the healed deck (Bible 30.5).
The AVLlit event never stands still (VX0=250 mm/s crawl dwell - a pre-creep
workaround), so AVL-Drive correctly finds no driveaway. This variant:
  M1: brake held 0.35 at (near-)standstill (VX0=10 mm/s, avoids the tire
      zero-speed singularity the 250 was dodging; reads 0.04 km/h)
  M2: brake release at maneuver switch (native CONSTANT 0 + 10 Hz
      smoothing) -> ~1 s of pure creep-roll -> 40% pedal at 1.0 s,
      run to 50 km/h (production driveaway signature)
  M3/M4: unchanged tip-out / final tip-in.
Usage: python driveaway_run.py stock|knee_v2|champion"""
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
import sys
import time

sys.path.insert(0, r"C:\Users\George\OneDrive\Desktop\PhD Thesis\CSV to MDF Converter\plt-to-mf4-app")

SRC = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"
FMUS = {
    "stock": None,
    "knee_v2": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Knee_v2.fmu",
    "champion": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu",
}

ADF_EDITS = [
    ("VX0               = 250",
     "VX0               = 10"),
    ("""[OL_BRAKE_1]
TAG                    = 'OPENLOOP'
TYPE                   = 'CONSTANT'
VALUE                  = 0""",
     """[OL_BRAKE_1]
TAG                    = 'OPENLOOP'
TYPE                   = 'CONSTANT'
VALUE                  = 0.35"""),
    ("EXPRESSION             = 'STEP({%TIME},0,{THROTTLE_0},0.3,0.5000)'\nSIGNAL_CHANNEL         = 0\n$---------------------------------------------------------------------------OL_BRAKE_2",
     "EXPRESSION             = 'STEP({%TIME},1.0,0,1.3,0.4000)'\nSIGNAL_CHANNEL         = 0\n$---------------------------------------------------------------------------OL_BRAKE_2"),
]
# OL_BRAKE_2 stays the file's native CONSTANT 0: an EXPRESSION brake block
# with SIGNAL_CHANNEL=0 hijacks the THROTTLE channel (channel 0 - learned
# the hard way, run 213053). Maneuver switch + 10 Hz brake smoothing gives
# the foot-off ramp for free.

tag = sys.argv[1]
fmu = FMUS[tag]
stamp = time.strftime("%Y%m%d_%H%M%S")
run = os.path.join(DATA_ROOT, "healed_runs", f"{tag}_driveaway_{stamp}")
os.makedirs(run, exist_ok=True)
for f in (DECK, "custom_event_tipout_10.adf", "AVLlit_tipin_50pct.nam"):
    shutil.copy(os.path.join(SRC, f), run)
if fmu:
    shutil.copy(fmu, os.path.join(run, os.path.basename(fmu)))

adf_path = os.path.join(run, "custom_event_tipout_10.adf")
adf = open(adf_path, encoding="utf-8", errors="replace").read()
for old, new in ADF_EDITS:
    assert adf.count(old) == 1, f"ADF anchor not unique/found: {old[:60]!r}"
    adf = adf.replace(old, new)
open(adf_path, "w", encoding="utf-8").write(adf)
print("ADF: driveaway edits applied (VX0=10, brake hold/release, 25% pedal)",
      flush=True)

deck_path = os.path.join(run, DECK)
text = open(deck_path, encoding="utf-8", errors="replace").read()
text, nb = re.subn(r'(ct[xyz]\s+=\s+")([\d.]+)"',
                   lambda m: m.group(1) + str(float(m.group(2))*30.0) + '"',
                   text)
n1 = n2 = 1
if fmu:
    new_fmu = os.path.join(run, os.path.basename(fmu)).replace("\\", "/")
    text, n1 = re.subn(r'"[^"]*Motor_PSM_dual\.fmu"'.replace("PSM", "PMSM"),
                       '"' + new_fmu + '"', text)
    text, n2 = re.subn(
        r'(id\s+=\s+"-535050562"\s*\n\s*string\s+=\s+")ModelExchange(")',
        r"\g<1>CoSimulation\g<2>", text)
text, _ = re.subn(r'"[^"]*custom_event_tipout_10\.adf"',
                  '"' + (run + "/custom_event_tipout_10.adf").replace("\\", "/") + '"',
                  text)
open(deck_path, "w", encoding="utf-8").write(text)
print(f"{tag}: damping x30 ({nb} fields), fmu swap x{n1}, mode x{n2}", flush=True)
if n1 != 1 or n2 != 1:
    raise SystemExit(f"{tag}: PATCH COUNTS WRONG")

env = os.environ.copy()
dirs = []
for m in re.finditer(r'"([A-Za-z]:[^"]+?\.dll)"', text, re.IGNORECASE):
    d = os.path.dirname(m.group(1).replace("/", os.sep))
    if os.path.isdir(d) and d not in dirs:
        dirs.append(d)
env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
t0 = time.time()
proc = subprocess.Popen([BAT, DECK], cwd=run, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    rc = proc.wait(timeout=3*3600)
except subprocess.TimeoutExpired:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
    rc = "KILLED@3h"
print(f"{tag}: solver exit {rc} in {(time.time()-t0)/60:.1f} min", flush=True)

from converter import convert
p = convert(os.path.join(run, "AVLlit_tipin_50pct.plt"))
from score_mf4 import score
s = score(p)
print(f"{tag}: {s['km']:.2f} km | {s['wh_per_km']:.1f} Wh/km | "
      f"jerk {s['jerk_rms']:.3f} | distRMS {s['disturb_rms']:.3f} | "
      f"distPk {s['disturb_peak']:.2f} | {s['eng_per_min']:.2f} wakes/min",
      flush=True)
print("MF4 banked ->", p, flush=True)
