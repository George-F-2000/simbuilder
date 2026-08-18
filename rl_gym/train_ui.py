"""train_ui.py — the RL Gym tab's training runner (Bible 29.9).
Reads ui_train_config.json (written by SimBuilder's Gym tab), applies the
comfort knobs, trains the requested personalities, scores each on the fixed
referee, and appends rows to gym_history.json. Everything prints to stdout,
which the tab tails live."""
import json
import os
import time

import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO

HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, "ui_train_config.json")))

import gym_env
gym_env.DemoSplitEnv.C_JERK = float(cfg.get("c_jerk", 0.02))
gym_env.DemoSplitEnv.C_ENGAGE = float(cfg.get("c_engage", 0.05))
gym_env.DemoSplitEnv.C_RATE = float(cfg.get("c_rate", 0.02))

if cfg.get("workout") == "pedal_creep":
    from gym_v4 import PedalCreepEnv as Env
    env_kw = {}
else:
    from train_v3 import MeasuredEnv as Env
    env_kw = {"cycle": "george_demand.txt"}

STEPS = int(cfg.get("steps", 200_000))
print(f"GYM SESSION: workout={cfg.get('workout')} steps={STEPS} "
      f"knobs jerk={gym_env.DemoSplitEnv.C_JERK} "
      f"engage={gym_env.DemoSplitEnv.C_ENGAGE} "
      f"rate={gym_env.DemoSplitEnv.C_RATE}", flush=True)


class W(gym.Env):
    def __init__(self, wc):
        self.env = Env(w_comfort=wc, **env_kw)
        self.observation_space = gym.spaces.Box(
            low=np.array([0, -1.2, 0]), high=np.array([1.2, 1.2, 1]),
            dtype=np.float64)
        self.action_space = gym.spaces.Box(0.0, 1.0, (1,), np.float64)

    def reset(self, seed=None, options=None):
        return self.env.reset(), {}

    def step(self, a):
        o, r, dn, i = self.env.step(float(a[0]))
        return o, r, dn, False, i


def score(fn):
    e = Env(**env_kw)
    obs = e.reset(); done = False
    while not done:
        obs, _, done, _ = e.step(fn(obs))
    return e.summary()


hist_path = os.path.join(HERE, "gym_history.json")
hist = json.load(open(hist_path)) if os.path.exists(hist_path) else []

from policies import StockMapPolicy
sp = StockMapPolicy()
s = score(lambda o: sp(o))
print(f"BASELINE stock map: {s['wh_per_km']:.1f} Wh/km, "
      f"discomfort {s['discomfort']:.1f}", flush=True)
baseline = {k: float(v) for k, v in s.items()}

n_total = len(cfg.get("weights", [1.0])) * int(cfg.get("seeds", 1))
n_done = 0
for wc in cfg.get("weights", [1.0]):
    for seed in range(1, int(cfg.get("seeds", 1)) + 1):
        n_done += 1
        print(f"TRAINING {n_done}/{n_total}: comfort weight {wc}, "
              f"seed {seed} ... (this takes a while - watch the chart "
              f"of laps below)", flush=True)
        m = PPO("MlpPolicy", W(float(wc)), verbose=0, seed=seed,
                policy_kwargs=dict(net_arch=[64, 64]))
        m.learn(total_timesteps=STEPS)
        s = score(lambda o: float(np.clip(
            m.predict(o, deterministic=True)[0][0], 0, 1)))
        tag = f"ui_wc{wc:g}_s{seed}_{time.strftime('%m%d_%H%M')}"
        m.save(os.path.join(HERE, "ppo_" + tag))
        row = {k: float(v) for k, v in s.items()}
        row.update({"tag": tag, "wc": float(wc), "seed": seed,
                    "workout": cfg.get("workout", "george_demand"),
                    "when": time.strftime("%Y-%m-%d %H:%M"),
                    "baseline_wh": baseline["wh_per_km"],
                    "baseline_disc": baseline["discomfort"]})
        hist.append(row)
        json.dump(hist, open(hist_path, "w"), indent=2)
        print(f"GRADUATED {tag}: {s['wh_per_km']:.1f} Wh/km "
              f"(stock {baseline['wh_per_km']:.1f}), discomfort "
              f"{s['discomfort']:.1f} (stock {baseline['discomfort']:.1f})",
              flush=True)
print("SESSION COMPLETE", flush=True)
