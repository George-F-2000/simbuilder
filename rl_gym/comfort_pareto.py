"""
comfort_pareto.py — the "comfort AND range, TOGETHER" experiment (Bible 28.8).
Trains one RL EMS per comfort weight and plots the Pareto frontier: x = Wh/km
(range), y = discomfort (comfort). Every trained point is a different
personality of the same car — from range-obsessed to chauffeur-smooth — and
the frontier's SHAPE is the thesis result: how much range does a unit of
comfort cost, and where is the knee?
Needs the RL extras once:  pip install gymnasium stable-baselines3
Usage:  python comfort_pareto.py [--steps 200000] [--cycle uddscol.txt]
"""

import argparse
import json
import os

import numpy as np

from gym_env import DemoSplitEnv
from policy_to_rch import flatten_to_rch

W_COMFORT_GRID = [0.0, 0.3, 1.0, 3.0, 10.0]


def evaluate(policy, cycle):
    env = DemoSplitEnv(cycle=cycle)          # scoring env: fixed weights
    obs = env.reset(); done = False
    while not done:
        obs, _, done, _ = env.step(policy(obs))
    return env.summary()


def main():
    from stable_baselines3 import PPO         # hard requirement here
    from train_rl import GymWrapper

    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200_000)
    ap.add_argument("--cycle", default="uddscol.txt")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    frontier = []
    for wc in W_COMFORT_GRID:
        print(f"\n### training w_comfort = {wc}")
        model = PPO("MlpPolicy", GymWrapper(args.cycle, wc), verbose=0,
                    policy_kwargs=dict(net_arch=[64, 64]))
        model.learn(total_timesteps=args.steps)

        def pol(obs, m=model):
            a, _ = m.predict(obs, deterministic=True)
            return float(np.clip(a[0], 0, 1))

        s = evaluate(pol, args.cycle)
        s["w_comfort"] = wc
        frontier.append(s)
        print(f"   -> {s['wh_per_km']:.1f} Wh/km | discomfort {s['discomfort']:.2f} "
              f"| jerkRMS {s['jerk_rms']:.3f} | engage/min {s['engage_per_min']:.2f}")
        model.save(os.path.join(here, f"ppo_wc{wc:g}"))
        flatten_to_rch(lambda v, t, soc=0.75, m=model: float(np.clip(
            m.predict(np.array([v/55.55, t/591.0, soc]),
                      deterministic=True)[0][0], 0, 1)),
            os.path.join(here, f"george_rl_wc{wc:g}_opt_trq_ratio.mat"))

    out = os.path.join(here, "pareto_frontier.json")
    with open(out, "w") as f:
        json.dump(frontier, f, indent=2)
    print(f"\nfrontier saved -> {out}  (plot Wh/km vs discomfort; pick the knee)")


if __name__ == "__main__":
    main()
