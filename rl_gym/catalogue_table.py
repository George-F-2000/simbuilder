"""catalogue_table.py - one row per sweep run under healed_runs: entrant, event,
maneuvers completed, solver errors, duration, final speed and the common-loss
score. Appends the table to the lab README's run list (or prints it with --print).
Usage: python catalogue_table.py [--print]"""
import glob
import json
import os
import re
import sys

import numpy as np
from asammdf import MDF

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_mf4 import score

_lc = {}
try:
    _lc = json.load(open(os.path.join(os.path.dirname(HERE), "vehicle_local.json")))
except Exception:
    pass
ROOT = _lc.get("data_root", "C:/demo_data") + "/healed_runs"
README = os.path.join(ROOT, "README_AVL_sweep.md")
# only the final generation (protected learned FMUs, 3 km/h stop ends, queue v7+);
# earlier stamps are superseded event definitions kept for the record
GEN_START = "20260904_110000"


def row(d):
    name = os.path.basename(d)
    m = re.match(r"(stock|knee_v2|champion)_sweep_(\w+?)_(\d{8}_\d{6})$", name)
    if not m:
        return None
    tag, ev, stamp = m.groups()
    if stamp < GEN_START:
        return None
    mf4 = os.path.join(d, "AVLlit_tipin_50pct_avldrive.mf4")
    log = os.path.join(d, "AVLlit_tipin_50pct.log")
    if not (os.path.exists(mf4) and os.path.exists(log)):
        return None
    txt = open(log, encoding="utf-8", errors="replace").read()
    man = len(re.findall(r"Maneuver \d+ loaded", txt))
    err = len(re.findall(r"ERROR", txt))
    mdf = MDF(mf4)
    v = np.asarray(mdf.get("VehicleSpeed").samples, float)
    t = np.asarray(mdf.get("VehicleSpeed").timestamps)
    s = score(mf4)
    return (tag, ev, stamp, man, err, t[-1], v[-1], v.max(), s["wh_per_km"], s["jerk_rms"], s["disturb_peak"])


rows = [r for r in (row(d) for d in sorted(glob.glob(ROOT + "/*_sweep_*"))) if r]
order = {"stock": 0, "knee_v2": 1, "champion": 2}
rows.sort(key=lambda r: (r[1], order[r[0]], r[2]))
lines = ["| entrant | event | run | maneuvers | errors | duration s | final km/h | max km/h | Wh/km* | jerk | dist.pk |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append("| %s | %s | %s | %d | %d | %.1f | %.1f | %.1f | %.0f | %.2f | %.2f |" % r)
table = "\n".join(lines)
if "--print" in sys.argv:
    print(table)
else:
    txt = open(README, encoding="utf-8").read()
    head = txt[:txt.index("## Run list")]
    open(README, "w", encoding="utf-8").write(head + "## Run list\n" + table + "\n")
    print("README run list: %d rows" % len(rows))
