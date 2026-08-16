"""picture_book.py — one-page cartoon of every moving part in the RL-EMS rig."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BOXES = [  # (x, y, w, color, title, lines)
    (0.02, 0.66, 0.20, "#dbeafe", "1. THE TRACK",
     ["A speed trace to follow.", "Sweep 2 uses 'George", "Demand': launches, WOT", "passes, stop-go."]),
    (0.27, 0.66, 0.20, "#e0e7ff", "2. ROBOT DRIVER",
     ["Presses the pedal to", "hold the trace. Never", "learns - just converts", "speed error to demand."]),
    (0.52, 0.66, 0.20, "#fef3c7", "3. THE BRAIN (policy)",
     ["Sees 3 numbers: speed,", "demand, battery %.", "Picks ONE number r:", "share sent to REAR."]),
    (0.77, 0.66, 0.21, "#dcfce7", "4. THE CAR (gym)",
     ["Your demo EV's math: real", "motor maps, 2710 kg,", "real battery losses.", "2000x faster than the", "full 3D sim."]),
    (0.77, 0.30, 0.21, "#fee2e2", "5. THE SCORECARD",
     ["Charges the brain for:", "battery burned (Wh) +", "rough riding (jerk,", "clunky rear wake-ups)."]),
    (0.52, 0.30, 0.20, "#fce7f3", "6. THE COACH (PPO)",
     ["Every ~2000 steps:", "nudge the brain toward", "choices that scored", "better. Repeat x100."]),
    (0.27, 0.30, 0.20, "#f3e8ff", "7. THE MENU (Pareto)",
     ["Train 5 brains, each", "valuing comfort", "differently -> the", "comfort-vs-range menu."]),
    (0.02, 0.30, 0.20, "#ccfbf1", "8. THE MAP PRINTER",
     ["Quiz a brain at all", "151x198 situations,", "write answers into a", "stock-shaped table."]),
    (0.02, 0.02, 0.45, "#e5e7eb", "9. THE REAL TEST (SimBuilder + MotionSolve)",
     ["The table drops into the FMU like any EMS map. Judged by Wh/km,",
      "Drive Quality scores, and the real-vs-virtual Calibration overlay."]),
    (0.52, 0.02, 0.46, "#fff7ed", "THE LOOP, IN ONE BREATH",
     ["Driver follows the track -> brain splits the torque -> car burns",
      "battery -> scorecard bills it -> coach tunes the brain. A brain",
      "is just a calibration that tuned itself."]),
]

fig, ax = plt.subplots(figsize=(13.5, 8.2))
ax.axis("off")
ax.set_title("How the RL-EMS rig works - every moving part",
             fontsize=15, fontweight="bold", pad=14)
for x, y, w, c, title, lines in BOXES:
    h = 0.055 + 0.033*len(lines) + 0.04
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                fc=c, ec="#334155", lw=1.4,
                                transform=ax.transAxes, zorder=2))
    ax.text(x + w/2, y + h - 0.035, title, transform=ax.transAxes,
            ha="center", fontsize=10.5, fontweight="bold", zorder=3)
    for i, ln in enumerate(lines):
        ax.text(x + w/2, y + h - 0.072 - 0.033*i, ln, transform=ax.transAxes,
                ha="center", fontsize=9, zorder=3)

ARROWS = [  # (x1,y1,x2,y2, label)
    (0.22, 0.78, 0.27, 0.78, "target\nspeed"),
    (0.47, 0.78, 0.52, 0.78, "torque\ndemand"),
    (0.72, 0.78, 0.77, 0.78, "front / rear\ntorques"),
    (0.875, 0.66, 0.875, 0.50, "what happened\n(energy, jerk)"),
    (0.77, 0.40, 0.72, 0.40, "the bill"),
    (0.52, 0.40, 0.47, 0.40, "5 trained\nbrains"),
    (0.27, 0.40, 0.22, 0.40, "best\nbrain"),
    (0.12, 0.30, 0.12, 0.145, "the .mat\nmap"),
    (0.62, 0.44, 0.62, 0.655, "updated brain, next lap"),
]
for x1, y1, x2, y2, lab in ARROWS:
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), transform=ax.transAxes,
                                 arrowstyle="-|>", mutation_scale=16,
                                 lw=1.6, color="#0f172a", zorder=4))
    ax.text((x1+x2)/2 + 0.012, (y1+y2)/2 + 0.012, lab, transform=ax.transAxes,
            fontsize=7.5, color="#0f172a", ha="left", zorder=4)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs",
                   "0_picture_book.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
fig.savefig(out, dpi=150, bbox_inches="tight")
print("wrote", out)
