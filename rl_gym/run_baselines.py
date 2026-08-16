"""
run_baselines.py — the scoreboard, before any learning happens.
Runs every baseline strategy over HWFET + UDDS in the gym and prints
Wh/km, SOC drop, and cycle-tracking quality. These are the numbers any
'George EMS' has to beat. Results also saved to baselines.json.
"""

import json
import os
import time

from gym_env import DemoSplitEnv
from policies import StockMapPolicy, LossGreedy, single_motor, even_split

CYCLES = [("HWFET", "hwycol.txt"), ("UDDS", "uddscol.txt")]


def evaluate(policy_factory, cycle_file):
    env = DemoSplitEnv(cycle=cycle_file)
    pol = policy_factory(env)
    obs = env.reset()
    done = False
    while not done:
        obs, _, done, info = env.step(pol(obs))
    return env.summary()


def main():
    rows = {}
    strategies = [
        ("stock r_ch map", lambda e: StockMapPolicy()),
        ("single_motor (front only)", lambda e: single_motor),
        ("even 50/50", lambda e: even_split),
        ("loss-greedy (myopic optimum)", lambda e: LossGreedy(e)),
    ]
    for cyc_name, cyc_file in CYCLES:
        print(f"\n=== {cyc_name} ===")
        print(f"{'strategy':<30}{'Wh/km':>8}{'jerkRMS':>9}{'engage/min':>12}"
              f"{'discomfort':>12}{'trackRMSE':>11}")
        for name, factory in strategies:
            t0 = time.time()
            s = evaluate(factory, cyc_file)
            rows[f"{cyc_name}/{name}"] = s
            print(f"{name:<30}{s['wh_per_km']:>8.1f}{s['jerk_rms']:>9.3f}"
                  f"{s['engage_per_min']:>12.2f}{s['discomfort']:>12.2f}"
                  f"{s['track_rmse_kmh']:>11.2f}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baselines.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
