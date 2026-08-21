"""titrate_damping.py — find the honest bushing-damping dose (Bible 30.3).
Known points: x1 -> 31.5 mm/s2 ringing at 8.03 Hz; x100 -> 0.0 (killed, but
~1 h runs). This chain runs x10 and x30, scores each (7-9 Hz cruise lateral
amplitude + wall time), and prints the dose-response table."""
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
import numpy as np

SRC = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"


def one_dose(factor):
    run = os.path.join(os.environ["TEMP"], f"titrate_x{factor}")
    os.makedirs(run, exist_ok=True)
    for f in (DECK, "custom_event_tipout_10.adf", "AVLlit_tipin_50pct.nam"):
        shutil.copy(os.path.join(SRC, f), run)
    adf_path = os.path.join(run, "custom_event_tipout_10.adf")
    adf = open(adf_path, encoding="utf-8", errors="replace").read()
    adf, _ = re.subn(r"(\'MANEUVER_\d+\'\s+\S+\s+)0\.01(\s+0\.01)",
                     r"\g<1>0.001\g<2>", adf)
    open(adf_path, "w", encoding="utf-8").write(adf)
    deck_path = os.path.join(run, DECK)
    text = open(deck_path, encoding="utf-8", errors="replace").read()
    text, nb = re.subn(r'(ct[xyz]\s+=\s+")([\d.]+)"',
                       lambda m: m.group(1) + str(float(m.group(2))*factor) + '"',
                       text)
    text, _ = re.subn(r'"[^"]*custom_event_tipout_10\.adf"',
                      '"' + (run + "/custom_event_tipout_10.adf").replace("\\", "/") + '"',
                      text)
    open(deck_path, "w", encoding="utf-8").write(text)
    print(f"x{factor}: damping scaled in {nb} fields, launching...", flush=True)

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
    rc = proc.wait()
    mins = (time.time() - t0)/60.0
    print(f"x{factor}: solver exit {rc} in {mins:.1f} min", flush=True)

    from converter import convert
    from asammdf import MDF
    from scipy.signal import welch
    p = convert(os.path.join(run, "AVLlit_tipin_50pct.plt"))
    m = MDF(p)
    s = m.get("AccelerationLateral")
    t, a = np.asarray(s.timestamps), np.asarray(s.samples, float)
    w = (t > 40) & (t < 100)
    fs = 1/np.median(np.diff(t[w]))
    f, P = welch(a[w] - a[w].mean(), fs=fs, nperseg=4096)
    band = (f > 7) & (f < 9)
    amp = float(np.sqrt(2*np.trapezoid(P[band], f[band])))*1000
    dur = float(t[-1])
    print(f"x{factor}: 7-9 Hz lateral {amp:.1f} mm/s2 | sim duration {dur:.1f} s "
          f"| wall {mins:.1f} min", flush=True)
    return factor, amp, mins, dur


print("DOSE-RESPONSE (known: x1 = 31.5 mm/s2 @ ~15 min, x100 = 0.0 @ ~60 min)",
      flush=True)
rows = [one_dose(10), one_dose(30)]
print("\nTITRATION TABLE:", flush=True)
print("  x1    31.5 mm/s2   ~15 min   (undamped baseline)")
for fct, amp, mins, dur in rows:
    ok = "FULL RUN" if dur > 100 else "SHORT RUN - CHECK"
    print(f"  x{fct:<4} {amp:5.1f} mm/s2   {mins:4.1f} min   {ok}")
print("  x100   0.0 mm/s2   ~60 min   (sledgehammer)")
