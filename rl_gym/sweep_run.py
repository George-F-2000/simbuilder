"""sweep_run.py - run one entrant on one sweep event, banked durably.
Same healed-deck recipe as regen_run.py (bushing damping x30, FMU seat swap,
30% SOC reconstruction on the vehicle-definition pack); the ADF comes from
rl_gym/sweep/<event>.adf and the deck's event reference is repointed to it.
Usage: python sweep_run.py stock|knee_v2|champion <event>"""
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # pipeline-app converter (SOC reconstruction)

SRC = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"
FMUS = {
    "stock": None,
    "knee_v2": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Knee_v2.fmu",
    "champion": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu",
}

tag, event = sys.argv[1], sys.argv[2]
fmu = FMUS[tag]
adf_src = os.path.join(HERE, "sweep", event + ".adf")
if not os.path.exists(adf_src):
    raise SystemExit("no such event: " + adf_src)
stamp = time.strftime("%Y%m%d_%H%M%S")
run = os.path.join(DATA_ROOT, "healed_runs", f"{tag}_{event}_{stamp}")
os.makedirs(run, exist_ok=True)
for f in (DECK, "AVLlit_tipin_50pct.nam"):
    shutil.copy(os.path.join(SRC, f), run)
shutil.copy(adf_src, os.path.join(run, event + ".adf"))
if fmu:
    shutil.copy(fmu, os.path.join(run, os.path.basename(fmu)))

deck_path = os.path.join(run, DECK)
text = open(deck_path, encoding="utf-8", errors="replace").read()
text, nb = re.subn(r'(ct[xyz]\s+=\s+")([\d.]+)"',
                   lambda m: m.group(1) + str(float(m.group(2))*30.0) + '"', text)
# (deck-level regen limiter withdrawn - it breaks the DAE in the brake-held
#  standstill in every formulation tried; the protection lives in the learned
#  FMUs now, Bible 30.19b/c)
n1 = n2 = 1
if fmu:
    new_fmu = os.path.join(run, os.path.basename(fmu)).replace("\\", "/")
    text, n1 = re.subn(r'"[^"]*Motor_PSM_dual\.fmu"'.replace("PSM", "PMSM"), '"' + new_fmu + '"', text)
    text, n2 = re.subn(r'(id\s+=\s+"-535050562"\s*\n\s*string\s+=\s+")ModelExchange(")',
                       r"\g<1>CoSimulation\g<2>", text)
else:
    # ME-type stock FMU deadlocks on the damped deck at h_max 0.01 (Bible 30.4)
    adf_p = os.path.join(run, event + ".adf")
    a = open(adf_p, encoding="utf-8", errors="replace").read()
    a, _ = re.subn(r"('MANEUVER_\d+'\s+\S+\s+)0\.01(\s+0\.01)", r"\g<1>0.001\g<2>", a)
    open(adf_p, "w", encoding="utf-8").write(a)
text, n3 = re.subn(r'"[^"]*custom_event_tipout_10\.adf"',
                   '"' + (run + "/" + event + ".adf").replace("\\", "/") + '"', text)
open(deck_path, "w", encoding="utf-8").write(text)
print(f"{tag}/{event}: damping x30 ({nb} fields), fmu swap x{n1}, mode x{n2}, adf x{n3}", flush=True)
if n1 != 1 or n2 != 1 or n3 != 1:
    raise SystemExit("PATCH COUNTS WRONG")

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
    rc = proc.wait(timeout=(15 if not fmu else 4)*3600)  # stock at 1 ms driver step: driveaway family needs ~11 h
except subprocess.TimeoutExpired:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
    rc = "KILLED@3h"
print(f"{tag}/{event}: solver exit {rc} in {(time.time()-t0)/60:.1f} min", flush=True)

from converter import convert
_spec = {}
try:
    _spec = _j.load(open(os.path.join(SRC, "vehicle.json")))
except Exception:
    pass
p = convert(os.path.join(run, "AVLlit_tipin_50pct.plt"),
            pack_kwh=float(_spec.get("packKWh") or 0) or None,
            soc_start=_spec.get("packSOCstart", 0.30))
from score_mf4 import score
s = score(p)
print(f"{tag}/{event}: {s['km']:.2f} km | {s['wh_per_km']:.1f} Wh/km | jerk {s['jerk_rms']:.3f} | "
      f"distRMS {s['disturb_rms']:.3f} | distPk {s['disturb_peak']:.2f} | {s['eng_per_min']:.2f} wakes/min",
      flush=True)
print("MF4 banked ->", p, flush=True)
