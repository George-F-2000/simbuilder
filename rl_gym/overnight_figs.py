"""overnight_figs.py — merge 3 seeds -> measured frontier + knee (fig 6),
and launch time-traces of the current personalities (fig 7)."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, "figs")

# ---- fig 6: pooled frontier -------------------------------------------------
pool = []
for tag in ("A", "B", "C"):
    with open(os.path.join(HERE, f"pareto_seed{tag}.json")) as f:
        for s in json.load(f):
            s["seed"] = tag
            pool.append(s)
nd = [p for p in pool
      if not any(q["wh_per_km"] < p["wh_per_km"] - 1e-9 and
                 q["discomfort"] < p["discomfort"] - 1e-9 for q in pool)]
nd.sort(key=lambda s: s["wh_per_km"])
fig, ax = plt.subplots(figsize=(9.5, 6.2))
for p in pool:
    on = p in nd
    ax.scatter(p["wh_per_km"], p["discomfort"], s=130 if on else 45,
               c="tab:blue" if on else "silver", zorder=3 if on else 2)
ax.plot([p["wh_per_km"] for p in nd], [p["discomfort"] for p in nd],
        "b-", lw=2, zorder=2, label="measured frontier (15 graduates, 3 seeds)")
for p in nd:
    ax.annotate(f"w_c={p['w_comfort']:g} seed {p['seed']}",
                (p["wh_per_km"], p["discomfort"]), xytext=(7, 6),
                textcoords="offset points", fontsize=8.5)
knee = min(nd, key=lambda s: (s["wh_per_km"] - nd[0]["wh_per_km"])
           + 12*(s["discomfort"] - nd[-1]["discomfort"]))
ax.annotate("THE KNEE: +5 Wh/km buys 5 comfort pts;\nthe next point costs 47 Wh/km for 0.9",
            (knee["wh_per_km"], knee["discomfort"]),
            xytext=(knee["wh_per_km"] + 15, knee["discomfort"] + 3.5),
            fontsize=10, fontweight="bold", color="green",
            arrowprops=dict(arrowstyle="->", color="green"))
ax.set_xlabel("energy [Wh/km]  (left = goes further)")
ax.set_ylabel("discomfort  (down = rides nicer)")
ax.set_title("George Demand cycle, 3-seed pooled Pareto frontier\n"
             "grey = dominated graduates, blue = the menu")
ax.grid(alpha=0.3); ax.legend(fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(FIGS, "6_frontier_3seed.png"), dpi=140)
print("fig6 knee:", {k: round(v, 2) for k, v in knee.items() if k != "seed"},
      "seed", knee["seed"])

# ---- fig 7: launch traces ---------------------------------------------------
from stable_baselines3 import PPO
from gym_env import DemoSplitEnv

fig, (av, ar) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
for wc, color in ((0, "tab:red"), (0.3, "tab:orange"), (1, "tab:green"),
                  (10, "tab:blue")):
    model = PPO.load(os.path.join(HERE, f"ppo_wc{wc:g}"), device="cpu")
    env = DemoSplitEnv(cycle="george_demand.txt")
    obs = env.reset(); done = False
    ts, vs, rs = [], [], []
    while not done and env.k < 400:          # first 40 s: launch 1 + stop
        a, _ = model.predict(obs, deterministic=True)
        obs, _, done, info = env.step(float(np.clip(a[0], 0, 1)))
        ts.append(env.k*0.1); vs.append(info["v"]*3.6)
        tot = abs(info["tf"]) + abs(info["tr"])
        rs.append(abs(info["tr"])/tot if tot > 1 else 0.0)
    av.plot(ts, vs, color=color, label=f"w_c={wc:g}")
    ar.plot(ts, rs, color=color, label=f"w_c={wc:g}")
env2 = DemoSplitEnv(cycle="george_demand.txt")
av.plot(np.arange(len(env2.v_tgt[:400]))*0.1, env2.v_tgt[:400]*3.6, "k--",
        alpha=0.5, label="target")
av.set_ylabel("vehicle speed [km/h]"); av.legend(fontsize=8); av.grid(alpha=0.3)
av.set_title("Same green light, four personalities (seed-C graduates)")
ar.set_ylabel("share of torque on REAR axle"); ar.set_xlabel("time [s]")
ar.set_ylim(-0.05, 1.05); ar.legend(fontsize=8); ar.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(os.path.join(FIGS, "7_launch_traces.png"), dpi=140)
print("fig7 done")
