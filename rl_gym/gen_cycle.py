"""
gen_cycle.py — build 'George Demand', the high-demand training cycle
(Bible 28.9 next-experiments list, item 2). EPA cycle file format so
load_cycle reads it unchanged. Content: standstill launches, WOT tip-ins,
50->120 km/h passes, aggressive urban stop-go — the parts of the split map
(Fig.1) that UDDS/HWFET never visit.
"""

import os

import numpy as np

SEGS = [   # (duration s, start km/h, end km/h) — linear ramps
    (8, 0, 0), (9, 0, 97), (10, 97, 97), (8, 97, 0), (5, 0, 0),      # launch 1 + stop
    (7, 0, 97), (8, 97, 97), (10, 97, 129), (8, 129, 129),           # launch 2 + WOT pass
    (10, 129, 0), (5, 0, 0),                                         # hard stop
    (6, 0, 60), (4, 60, 60), (5, 60, 0), (4, 0, 0),                  # urban sprint x3
    (6, 0, 60), (4, 60, 60), (5, 60, 0), (4, 0, 0),
    (6, 0, 60), (4, 60, 60), (5, 60, 0), (4, 0, 0),
    (8, 0, 80), (12, 80, 80), (6, 80, 120), (10, 120, 120),          # 80->120 punch
    (10, 120, 40), (6, 40, 90), (8, 90, 90), (10, 90, 0), (6, 0, 0), # churn + stop
]

t, v = [0.0], [SEGS[0][1]]
for dur, v0, v1 in SEGS:
    steps = int(dur)
    for s in range(1, steps + 1):
        t.append(t[-1] + 1.0)
        v.append(v0 + (v1 - v0)*s/steps)

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "cycles", "george_demand.txt")
with open(out, "w") as f:
    f.write("GEORGE_DEMAND.TXT\tHigh-demand split-training cycle (launches, WOT, stop-go)\n")
    f.write("Test Time, secs\tTarget Speed, mph\n")
    for ti, vi in zip(t, v):
        f.write(f"{ti:.0f}\t{vi/1.60934:.2f}\n")
print(f"wrote {out}: {t[-1]:.0f} s, vmax {max(v):.0f} km/h")
