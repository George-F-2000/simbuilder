"""rescore_all.py — EVERYTHING at equal footing (Bible 29.5).
One referee world: the measured-reality gym (factory demand law + 50 ms
filter + delivery guarantee), George Demand cycle, fixed referee weights.
Scored: 4 baselines + all 6 v3 graduates. Output: table, json, Pareto fig."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from stable_baselines3 import PPO

from gym_env import DemoSplitEnv, DT
from policies import StockMapPolicy, LossGreedy, single_motor, even_split

HERE = os.path.dirname(os.path.abspath(__file__))
d = np.load(os.path.join(HERE, "stock_demand_law_fine.npz"))
SPDS, TMAP = d["speeds"], d["T"]
TMAX_V, TMIN_V = TMAP[-1, :], TMAP[0, :]
ALPHA = float(np.exp(-DT/0.05))


class MeasuredEnv(DemoSplitEnv):
    """Same reality patch as train_v3: measured law + filter + r_min."""

    def reset(self):
        self._fdem = 0.0
        return super().reset()

    def _demand(self):
        raw = super()._demand()
        raw = float(np.clip(raw, float(np.interp(self.v, SPDS, TMIN_V)),
                            float(np.interp(self.v, SPDS, TMAX_V))))
        self._fdem = ALPHA*getattr(self, "_fdem", 0.0) + (1 - ALPHA)*raw
        return self._fdem

    def step(self, r):
        t_dem = getattr(self, "_fdem", 0.0)
        env_f = self.front.max_trq(min(self.v/[RADIUS]*18.0, 1571.0))
        r_min = max(0.0, (abs(t_dem) - env_f)/max(abs(t_dem), 1.0))
        return super().step(max(float(r), min(r_min, 1.0)))


def run(policy):
    env = MeasuredEnv(cycle="george_demand.txt")
    obs = env.reset(); done = False
    while not done:
        obs, _, done, _ = env.step(policy(obs, env))
    return env.summary()


entrants = [("stock demo EV map", lambda: (lambda o, e, p=StockMapPolicy(): p(o))),
            ("single_motor", lambda: (lambda o, e: 0.0)),
            ("even 50/50", lambda: (lambda o, e: 0.5)),
            ("loss-greedy", lambda: None)]  # special: needs env instance
rows = []
for name, mk in entrants:
    if name == "loss-greedy":
        env = MeasuredEnv(cycle="george_demand.txt")
        pol = LossGreedy(env)
        obs = env.reset(); done = False
        while not done:
            obs, _, done, _ = env.step(pol(obs))
        s = env.summary()
    else:
        s = run(mk())
    s["name"] = name
    rows.append(s)
    print(f"{name:22s} {s['wh_per_km']:7.1f} Wh/km | disc {s['discomfort']:6.2f} "
          f"| jerk {s['jerk_rms']:.3f} | wakes/min {s['engage_per_min']:.2f}", flush=True)

import glob
for z in sorted(glob.glob(os.path.join(HERE, "ppo_v3_wc*_s*.zip"))):
    tag = os.path.basename(z).replace("ppo_v3_", "").replace(".zip", "")
    m = PPO.load(z, device="cpu")
    s = run(lambda o, e, m=m: float(np.clip(m.predict(o, deterministic=True)[0][0], 0, 1)))
    s["name"] = "v3 " + tag
    rows.append(s)
    print(f"{'v3 ' + tag:22s} {s['wh_per_km']:7.1f} Wh/km | disc {s['discomfort']:6.2f} "
          f"| jerk {s['jerk_rms']:.3f} | wakes/min {s['engage_per_min']:.2f}", flush=True)

json.dump(rows, open(os.path.join(HERE, "equal_footing.json"), "w"),
          default=float, indent=2)

nd = [r for r in rows
      if not any(q["wh_per_km"] < r["wh_per_km"] - 1e-9 and
                 q["discomfort"] < r["discomfort"] - 1e-9 for q in rows)]
fig, ax = plt.subplots(figsize=(10, 6.5))
for r in rows:
    on = r in nd
    rl = r["name"].startswith("v3")
    ax.scatter(r["wh_per_km"], r["discomfort"], s=150 if on else 60,
               marker="*" if rl else "o",
               c=("tab:blue" if rl else "tab:brown") if on else "silver", zorder=3)
    ax.annotate(r["name"], (r["wh_per_km"], r["discomfort"]),
                xytext=(7, 5), textcoords="offset points", fontsize=8)
nds = sorted(nd, key=lambda r: r["wh_per_km"])
ax.plot([r["wh_per_km"] for r in nds], [r["discomfort"] for r in nds],
        "k--", alpha=0.5, lw=1.5, label="equal-footing frontier")
ax.set_xlabel("energy [Wh/km]  (left = goes further)")
ax.set_ylabel("discomfort  (down = rides nicer)")
ax.set_title("EQUAL FOOTING: baselines (dots) vs v3 graduates (stars)\n"
             "measured-reality gym, George Demand cycle, one referee")
ax.grid(alpha=0.3); ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(HERE, "figs", "13_equal_footing.png"), dpi=140)
print("frontier:", [r["name"] for r in nds])
