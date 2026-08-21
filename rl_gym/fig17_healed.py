"""fig17_healed.py — the healed-car tournament, one picture (Bible 30.4b).
Three entrants, identical damped deck: speed tracking, chassis acceleration
(the comfort story), rear-motor torque (the strategy story)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from asammdf import MDF

T = os.environ["TEMP"]
RUNS = {
    "stock":    os.path.join(T, "titrate_x30", "AVLlit_tipin_50pct_avldrive.mf4"),
    "knee_v2":  os.path.join(T, "rebase_knee_v2", "AVLlit_tipin_50pct_avldrive.mf4"),
    "champion": os.path.join(T, "rebase_champion", "AVLlit_tipin_50pct_avldrive.mf4"),
}
STYLE = {"stock": ("0.45", 1.2), "knee_v2": ("#1f77b4", 1.0),
         "champion": ("#d62728", 1.2)}

fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
for tag, path in RUNS.items():
    m = MDF(path)
    def g(ch):
        s = m.get(ch)
        return np.asarray(s.timestamps), np.asarray(s.samples, float)
    c, lw = STYLE[tag]
    t, v = g("VehicleSpeed")
    ax[0].plot(t, v, color=c, lw=lw, label=tag)
    t, a = g("AccelerationChassis")
    ax[1].plot(t, a, color=c, lw=0.8, label=tag)
    t, tr = g("EM2Torque")
    ax[2].plot(t, tr, color=c, lw=0.8, label=tag)
    dwell = v[(t > 5) & (t < 25)]
    print(f"{tag:9s} dur {t[-1]:6.1f} s | dwell speed {dwell.mean():.2f} km/h"
          f" | accel p2p {a.max()-a.min():.2f}")

ax[0].set_ylabel("vehicle speed [km/h]")
ax[0].set_title("Healed-car tournament — AVLlit tip-in 50%, bushing damping x30")
ax[0].legend(loc="upper left")
ax[1].set_ylabel("chassis accel [m/s$^2$]")
ax[1].annotate("jerk RMS: stock 3.80 | knee 0.66 | champion 0.61\n"
               "disturb pk: stock 0.89 | learned 0.32",
               xy=(0.99, 0.04), xycoords="axes fraction", ha="right",
               fontsize=9, bbox=dict(fc="w", ec="0.7", alpha=0.9))
ax[2].set_ylabel("rear motor torque [Nm]")
ax[2].set_xlabel("time [s]")
ax[2].annotate("Wh/km: stock 172.6 | knee 198.1 | champion 171.0\n"
               "rear wakes/min: stock 1.53 | knee 0.00 | champion 1.48",
               xy=(0.99, 0.96), xycoords="axes fraction", ha="right", va="top",
               fontsize=9, bbox=dict(fc="w", ec="0.7", alpha=0.9))
for a_ in ax:
    a_.grid(alpha=0.3)
fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs",
                   "17_healed_tournament.png")
fig.savefig(out, dpi=150)
print("saved ->", out)
