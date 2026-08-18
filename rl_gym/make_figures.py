"""
make_figures.py — the visuals for Bible Ch.28: where AWD actually lives.
Outputs (rl_gym/figs/):
  1_stock_split_map.png   GM's r_ch as a heatmap in vehicle terms, with the
                          demand points our cycles actually visited overlaid
  2_motor_maps.png        front vs rear efficiency maps + torque envelopes
  3_comfort_vs_energy.png the UDDS comfort-range scatter (baselines + RL)
"""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import loadmat

from gym_env import STOCK, DemoSplitEnv, G_R, R_WHEEL
from policies import StockMapPolicy

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, "figs")
os.makedirs(FIGS, exist_ok=True)


def cycle_points(cycle_file):
    """(v km/h, traction T_dem Nm) visited by the gym under the stock map."""
    env = DemoSplitEnv(cycle=cycle_file)
    pol = StockMapPolicy()
    obs = env.reset(); done = False
    vs, ts = [], []
    while not done:
        obs, _, done, info = env.step(pol(obs))
        if info["t_dem"] > 0:
            vs.append(info["v"]*3.6); ts.append(info["t_dem"])
    return np.array(vs), np.array(ts)


def fig1():
    m = loadmat(os.path.join(STOCK, "one_strlineacc_0_opt_trq_ratio.mat"))
    w, T, r = m["w"].ravel(), m["T_dem"].ravel(), m["r_ch"]
    v_kmh = w*R_WHEEL/G_R*3.6
    fig, ax = plt.subplots(figsize=(10, 6.2))
    pc = ax.pcolormesh(T, v_kmh, r, cmap="RdYlBu_r", vmin=0, vmax=1,
                       shading="auto")
    fig.colorbar(pc, ax=ax, label="fraction of torque sent to REAR axle (r)")
    for cyc, color, lab in (("uddscol.txt", "k", "UDDS (city) demand"),
                            ("hwycol.txt", "lime", "HWFET (highway) demand")):
        v, t = cycle_points(cyc)
        ax.scatter(t, v, s=3, c=color, alpha=0.25, label=lab)
    ax.set_xlabel("combined torque demand [Nm]")
    ax.set_ylabel("vehicle speed [km/h]")
    ax.set_title("The stock split map: when the rear axle earns its keep\n"
                 "(blue = front does it all, red = rear takes over)")
    ax.legend(loc="upper right")
    stats = (f"map avg rear share {r.mean():.2f} | "
             f"{(r > 0.05).mean()*100:.0f}% of map uses the rear")
    ax.text(0.99, 0.02, stats, transform=ax.transAxes, ha="right",
            fontsize=9, bbox=dict(fc="w", alpha=0.8, ec="none"))
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "1_stock_split_map.png"), dpi=140)
    print("fig1:", stats)


def fig2():
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=False)
    for ax, mat, name in (
            (axes[0], "one_strlineacc_0_frnt_motor_data.mat",
             "FRONT unit"),
            (axes[1], "one_strlineacc_0_rear_motor_data.mat",
             "REAR unit")):
        d = loadmat(os.path.join(STOCK, mat))
        s, t = d["m_map_eff_spd"].ravel(), d["m_map_eff_trq"].ravel()
        pc = ax.pcolormesh(s*9.549/1000, t, d["m_eff_map"].T*100,
                           cmap="viridis", vmin=20, vmax=97, shading="auto")
        ax.plot(d["m_spd_data"].ravel()*9.549/1000, d["m_max_trq"].ravel(),
                "r-", lw=2, label="max torque envelope")
        ax.set_xlabel("motor speed [krpm]")
        ax.set_title(name)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylabel("motor torque [Nm]")
    fig.colorbar(pc, ax=axes, label="efficiency [%]", shrink=0.85)
    fig.suptitle("Why the split matters: the two motors are good in different places")
    fig.savefig(os.path.join(FIGS, "2_motor_maps.png"), dpi=140,
                bbox_inches="tight")
    print("fig2 done")


def fig3():
    with open(os.path.join(HERE, "baselines.json")) as f:
        b = json.load(f)
    pts = {k.split("/", 1)[1]: v for k, v in b.items() if k.startswith("UDDS")}
    pts["RL (all comfort weights)"] = {"wh_per_km": 175.7, "discomfort": 39.47}
    fig, ax = plt.subplots(figsize=(9, 6))
    for name, s in pts.items():
        ax.scatter(s["wh_per_km"], s["discomfort"], s=140,
                   marker="*" if name.startswith("RL") else "o",
                   label=name, zorder=3)
        ax.annotate(name, (s["wh_per_km"], s["discomfort"]),
                    textcoords="offset points", xytext=(8, 6), fontsize=9)
    ax.annotate("IDEAL: cheap AND smooth", xy=(0.03, 0.05),
                xycoords="axes fraction", fontsize=11, color="green",
                fontweight="bold")
    ax.set_xlabel("energy [Wh/km]  (left = goes further)")
    ax.set_ylabel("discomfort score  (down = rides nicer)")
    ax.set_title("UDDS city cycle: comfort vs range — every strategy is a dot\n"
                 "(no dot in the green corner yet = the open research gap)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "3_comfort_vs_energy.png"), dpi=140)
    print("fig3 done")


if __name__ == "__main__":
    fig1(); fig2(); fig3()
    print("figures ->", FIGS)
