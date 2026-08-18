"""first_drive_figs.py — stock vs knee, same deck, same scenario, overlaid.
Produces figs/9_first_drive_overlay.png + printed verdict stats."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from asammdf import MDF

STOCK = DATA_ROOT + r"\avl_regenoff_runs\AVLlit_tipin_50pct_20260726_075106\AVLlit_tipin_50pct_avldrive.mf4"
KNEE = r"C:\Users\George\AppData\Local\Temp\knee_ms_run\AVLlit_tipin_50pct_avldrive.mf4"
HERE = os.path.dirname(os.path.abspath(__file__))


def pick(mdf, *needles):
    for ch in mdf.channels_db:
        low = ch.lower()
        if all(n.lower() in low for n in needles):
            return ch
    return None


def sig(mdf, name):
    s = mdf.get(name)
    return np.asarray(s.timestamps), np.asarray(s.samples, dtype=float)


ms, mk = MDF(STOCK), MDF(KNEE)
print("stock channels:", sorted(ms.channels_db)[:30])
rows = []
for label, needles in (("speed", ("vehiclespeed",)), ("front torque", ("em1", "torque")),
                       ("rear torque", ("em2", "torque")), ("soc", ("soc",)),
                       ("accel", ("accel",)), ("pedal", ("pdl",))):
    a, b = pick(ms, *needles), pick(mk, *needles)
    rows.append((label, a, b))
    print(f"{label:14s} stock={a}  knee={b}")

fig, axes = plt.subplots(3, 1, figsize=(11.5, 9), sharex=True)
panels = [("speed", "vehicle speed [km/h]", 1.0),
          ("front torque", "front motor torque [Nm]", 1.0),
          ("rear torque", "rear motor torque [Nm]", 1.0)]
stats = {}
for ax, (label, ylab, scale) in zip(axes, panels):
    row = next(r for r in rows if r[0] == label)
    for src, name, color, tag in ((ms, row[1], "#8a5a2b", "stock EMS"),
                                  (mk, row[2], "#1f6fe0", "knee EMS")):
        if name is None:
            continue
        t, v = sig(src, name)
        ax.plot(t, v*scale, color=color, lw=1.3, label=tag, alpha=0.9)
        stats[(label, tag)] = (t, v)
    ax.set_ylabel(ylab); ax.grid(alpha=0.3); ax.legend(fontsize=9)
axes[0].set_title("First drive: stock EMS vs GeorgeEMS knee — same deck, same "
                  "driver, same scenario (AVLlit tip-in 50%)")
axes[-1].set_xlabel("time [s]")
fig.tight_layout()
out = os.path.join(HERE, "figs", "9_first_drive_overlay.png")
fig.savefig(out, dpi=140)
print("fig ->", out)

# verdict numbers
def interp_common(a, b):
    t0 = max(a[0][0], b[0][0]); t1 = min(a[0][-1], b[0][-1])
    tt = np.arange(t0, t1, 0.01)
    return tt, np.interp(tt, *a), np.interp(tt, *b)

if ("speed", "stock EMS") in stats and ("speed", "knee EMS") in stats:
    tt, vs, vk = interp_common(stats[("speed", "stock EMS")],
                               stats[("speed", "knee EMS")])
    print(f"SPEED: rmse {np.sqrt(np.mean((vs-vk)**2)):.2f}, "
          f"stock max {vs.max():.1f}, knee max {vk.max():.1f}")
for lab in ("front torque", "rear torque"):
    for tag in ("stock EMS", "knee EMS"):
        if (lab, tag) in stats:
            t, v = stats[(lab, tag)]
            print(f"{lab}/{tag}: min {v.min():.1f} max {v.max():.1f} "
                  f"mean|x| {np.abs(v).mean():.1f}")
