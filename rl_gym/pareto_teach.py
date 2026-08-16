"""pareto_teach.py — how to read a Pareto curve, next to our real sweep-1 dots."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 5.6))

# left: the textbook shape
t = np.linspace(0, 1, 100)
x, y = 175 + 22*t**2.2, 44 - 26*t**0.55
a1.plot(x, y, "b-", lw=2.5, label="the frontier (the menu)")
a1.scatter([176.2, 179, 189], [43, 30.5, 22.5], c="b", s=90, zorder=3)
a1.annotate("range miser\n(harsh but thrifty)", (176.2, 43), xytext=(178, 45),
            fontsize=9, arrowprops=dict(arrowstyle="->"))
a1.annotate("THE KNEE: most of the\ncomfort, tiny range cost\n= what you'd ship",
            (179, 30.5), xytext=(182, 36), fontsize=9, fontweight="bold",
            color="green", arrowprops=dict(arrowstyle="->", color="green"))
a1.annotate("chauffeur\n(smooth, thirsty)", (189, 22.5), xytext=(191, 27),
            fontsize=9, arrowprops=dict(arrowstyle="->"))
a1.scatter([193], [40], c="r", marker="x", s=110, zorder=3)
a1.annotate("DOMINATED: worse at both\n(throw it out - our loss-greedy\nlives here)",
            (193, 40), xytext=(183, 46.5), fontsize=9, color="r",
            arrowprops=dict(arrowstyle="->", color="r"))
a1.set_title("How to read one (textbook shape)")

# right: sweep 1, the real degenerate case
with open(os.path.join(HERE, "pareto_frontier.json")) as f:
    fr = json.load(f)
for s in fr:
    a2.scatter(s["wh_per_km"], s["discomfort"], s=130, zorder=3,
               c="tab:orange" if s["w_comfort"] == 0 else "tab:blue")
    a2.annotate(f"w_c={s['w_comfort']:g}", (s["wh_per_km"], s["discomfort"]),
                xytext=(6, 4 + 10*(s["w_comfort"] in (1, 10))),
                textcoords="offset points", fontsize=9)
a2.annotate("4 personalities landed on THE SAME DOT\n= no trade-off found on gentle UDDS\n"
            "(comfort & range were allies down there)",
            (175.7, 39.47), xytext=(175.9, 41.5), fontsize=9.5, fontweight="bold",
            arrowprops=dict(arrowstyle="->"))
a2.set_title("Sweep 1 on UDDS (city): the collapsed frontier\n"
             "sweep 2 (high demand) is where a real curve should appear")
for a in (a1, a2):
    a.set_xlabel("energy [Wh/km]  (left = goes further)")
    a.set_ylabel("discomfort  (down = rides nicer)")
    a.grid(alpha=0.3)
a1.legend(loc="lower left", fontsize=9)
fig.tight_layout()
out = os.path.join(HERE, "figs", "4_pareto_reading.png")
fig.savefig(out, dpi=140)
print("wrote", out)
