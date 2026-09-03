"""parity_table.py - tournament table from durable healed_runs MF4s.
Stock row: newest healed_runs/stock_* MF4 if one exists, else the banked
round-6 scores (healed_tournament.json; the temp MF4 was cleaned).
Learned rows: newest healed_runs/<tag>_<stamp>/ (plain runs, not driveaway)."""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_mf4 import score

_lc = {}
try:
    _lc = json.load(open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "vehicle_local.json")))
except Exception:
    pass
RUNS = os.path.join(_lc.get("data_root", "C:/demo_data"), "healed_runs")
MF4 = "AVLlit_tipin_50pct_avldrive.mf4"


def newest(tag):
    dirs = [d for d in glob.glob(os.path.join(RUNS, tag + "_*"))
            if re.fullmatch(tag + r"_\d{8}_\d{6}", os.path.basename(d))
            and os.path.exists(os.path.join(d, MF4))]
    return os.path.join(max(dirs), MF4) if dirs else None


rows, src = {}, {}
p = newest("stock")
if p:
    rows["stock"] = score(p); src["stock"] = os.path.basename(os.path.dirname(p))
else:
    rows["stock"] = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "healed_tournament.json")))["stock"]
    src["stock"] = "banked round-6 scores"
for tag in ("knee_v2", "champion"):
    p = newest(tag)
    if not p:
        raise SystemExit(f"no {tag} run in {RUNS}")
    rows[tag] = score(p); src[tag] = os.path.basename(os.path.dirname(p))

print("\nHEALED-CAR TOURNAMENT, real motor maps in every entrant:")
hdr = (f"{'entrant':10s}{'km':>7}{'Wh/km':>8}{'Wh/km*':>8}{'jerkRMS':>9}{'distRMS':>9}"
       f"{'distPk':>8}{'wakes/min':>10}  source   (* = net energy through ONE common loss model)")
print(hdr); print("-" * len(hdr))
for tag, s in rows.items():
    print(f"{tag:10s}{s['km']:7.2f}{s['wh_per_km']:8.1f}{s.get('wh_per_km_common', float('nan')):8.1f}"
          f"{s['jerk_rms']:9.3f}{s['disturb_rms']:9.3f}{s['disturb_peak']:8.2f}{s['eng_per_min']:10.2f}  {src[tag]}")
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "healed_tournament_realmaps.json")
json.dump({"rows": rows, "source": src}, open(out, "w"), default=float, indent=2)
print("saved ->", out)
