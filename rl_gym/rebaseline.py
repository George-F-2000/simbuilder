"""rebaseline.py — Stage 3: the tournament on the HEALED car (Bible 30.4).
Healed = bushing rotational damping x30 + driver h_max 0.001. Stock entrant
already exists (the titrate_x30 run). This chain runs knee v2 and champion
on identical healed decks (FMU seat swap included), then scores all three
with the standard referee. One notification = the final table."""
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
    "knee_v2": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Knee_v2.fmu",
    "champion": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu",
}


def one_entrant(tag, fmu):
    run = os.path.join(os.environ["TEMP"], f"rebase_{tag}")
    os.makedirs(run, exist_ok=True)
    for f in (DECK, "custom_event_tipout_10.adf", "AVLlit_tipin_50pct.nam"):
        shutil.copy(os.path.join(SRC, f), run)
    if fmu:
        shutil.copy(fmu, os.path.join(run, os.path.basename(fmu)))

    # ADF stays at its native h_max 0.01 - the learned FMUs stall the
    # 1 kHz-thinking driver at creep (Bible 30.4 finding); equal footing
    # for all entrants at the proven rate.
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
    print(f"{tag}: damping x{30:g} ({nb} fields), fmu swap x{n1}, mode x{n2}",
          flush=True)
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
        rc = proc.wait(timeout=3*3600)  # 12-h-hang lesson: no solver runs >3 h
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
        rc = "KILLED@3h"
    print(f"{tag}: solver exit {rc} in {(time.time()-t0)/60:.1f} min", flush=True)

    from converter import convert
    return convert(os.path.join(run, "AVLlit_tipin_50pct.plt"))


# stock healed entry = the completed titrate_x30 run (h_max 0.001 - the
# ME-type stock FMU HANGS at 0.01 on the damped deck; the CS-type learned
# FMUs run at 0.01. Internal solver caps differ; OUTPUT sampling is 100 Hz
# for all, so referee metrics stay comparable. Documented asymmetry.
mf4s = {"stock": os.path.join(os.environ["TEMP"], "titrate_x30",
                              "AVLlit_tipin_50pct_avldrive.mf4")}
for tag, fmu in FMUS.items():
    mf4s[tag] = one_entrant(tag, fmu)

from score_mf4 import score
print("\nHEALED-CAR TOURNAMENT:", flush=True)
hdr = f"{'entrant':10s}{'km':>7}{'Wh/km':>8}{'jerkRMS':>9}{'distRMS':>9}{'distPk':>8}{'wakes/min':>10}"
print(hdr); print("-"*len(hdr))
rows = {}
for tag, p in mf4s.items():
    s = score(p); rows[tag] = s
    print(f"{tag:10s}{s['km']:7.2f}{s['wh_per_km']:8.1f}{s['jerk_rms']:9.3f}"
          f"{s['disturb_rms']:9.3f}{s['disturb_peak']:8.2f}{s['eng_per_min']:10.2f}",
          flush=True)
import json
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "healed_tournament.json"), "w"),
          default=float, indent=2)
print("saved -> healed_tournament.json", flush=True)
