"""coast_check.py - plant-health check of one sweep run from the deck's PLT and
the AVL MF4: airborne front episodes, bump-stop loading, lift-off wheel
behaviour, relaunch accel band, spikes under drive (Bible 30.19-30.21).
Usage: python coast_check.py <run_dir> [wheel_radius_m]"""
import os
import sys

import numpy as np
from asammdf import MDF

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import plt_reader

d = sys.argv[1]
R = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35
log = open(os.path.join(d, "AVLlit_tipin_50pct.log"), encoding="utf-8", errors="replace").read()
print("%s: maneuvers %d | integrator failures %d" % (os.path.basename(d), log.count(" loaded."), log.count("integrator failed")))
t, data, ids = plt_reader.read_plt(os.path.join(d, "AVLlit_tipin_50pct.plt"))[:3]
fz = data[:, 123, 2]; lo = fz < 100
ed = np.diff(np.r_[0, lo.astype(int), 0]); eps = list(zip(np.where(ed == 1)[0], np.where(ed == -1)[0]))
print("front-left airborne episodes: %d" % len(eps), " ".join("%.1fs(%.0fms)" % (t[a], (t[b-1]-t[a]+0.01)*1000) for a, b in eps[:8]))
rb = np.abs(data[:, 56, :3]).max(axis=1); fb = np.abs(data[:, 48, :3]).max(axis=1)
print("bump stops loaded: rear %.0f%% of the run (max %.1f kN) | front %.0f%% (max %.1f kN)" % (100*(rb > 50).mean(), rb.max()/1000, 100*(fb > 50).mean(), fb.max()/1000))
print("front tyre Fz range %.1f..%.1f kN | rear %.1f..%.1f kN" % (fz.min()/1000, fz.max()/1000, data[:, 137, 2].min()/1000, data[:, 137, 2].max()/1000))
m = MDF(os.path.join(d, "AVLlit_tipin_50pct_avldrive.mf4"))
g = lambda ch: (np.asarray(m.get(ch).timestamps), np.asarray(m.get(ch).samples, float))
tm, v = g("VehicleSpeed"); _, fl = g("WheelSpeed_FL"); _, t1 = g("EM1Torque"); _, a = g("AccelerationChassis"); _, ped = g("AcceleratorPedal"); _, br = g("Brake")
veh = v/3.6/R*60/(2*np.pi)
lift = (ped < 1.0) & (v > 20)
e2 = np.diff(np.r_[0, lift.astype(int), 0])
for s, e in zip(np.where(e2 == 1)[0], np.where(e2 == -1)[0]):
    if tm[e-1]-tm[s] < 0.5:
        continue
    w = slice(s, e); post = (tm > tm[e-1]) & (tm < tm[e-1] + 3)
    print("lift %6.1f-%6.1f s v %5.1f->%5.1f | FL min %4.0f rpm ratio %.2f | EM1 min %4.0f mean %4.0f | accel min %5.2f | after: accel %5.2f..%5.2f" % (
        tm[s], tm[e-1], v[s], v[e-1], fl[w].min(), (fl[w]/np.maximum(veh[w], 1)).min(), t1[w].min(), t1[w].mean(), a[w].min(),
        a[post].min() if post.any() else 0, a[post].max() if post.any() else 0))
nib = (a < -3.0) & (ped > 15) & (br < 0.01) & (v > 5)
e3 = np.diff(np.r_[0, nib.astype(int), 0])
ev = [(tm[s], a[s:e].min(), v[s]) for s, e in zip(np.where(e3 == 1)[0], np.where(e3 == -1)[0])]
print("spikes under drive (accel < -3 with pedal > 15%%, no brake): %d" % len(ev), " ".join("t=%.1f a=%.1f v=%.0f" % x for x in ev[:6]))
