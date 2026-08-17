"""train_jerk.py — the jerk-vision knee (Bible Ch.29 policy #1 v2).
Same knee recipe (w_c=1, George Demand cycle) but the policy now SEES jerk:
obs = [v, T_dem, SOC, jerk]. Two seeds; each scored on the standard referee
env and compared against the blind knee (587.2 Wh/km / 47.72 discomfort)."""
import os

import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO

from gym_env import DemoSplitEnv

HERE = os.path.dirname(os.path.abspath(__file__))
CYCLE = "george_demand.txt"


class JerkWrapper(gym.Env):
    def __init__(self):
        self.env = DemoSplitEnv(cycle=CYCLE, w_comfort=1.0, obs_jerk=True)
        self.observation_space = gym.spaces.Box(
            low=np.array([0, -1.2, 0, -1.6]), high=np.array([1.2, 1.2, 1, 1.6]),
            dtype=np.float64)
        self.action_space = gym.spaces.Box(low=0.0, high=1.0, shape=(1,),
                                           dtype=np.float64)

    def reset(self, seed=None, options=None):
        return self.env.reset(), {}

    def step(self, a):
        obs, r, done, info = self.env.step(float(a[0]))
        return obs, r, done, False, info


def score(model):
    env = DemoSplitEnv(cycle=CYCLE, obs_jerk=True)   # referee weights default
    obs = env.reset(); done = False
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, _, done, _ = env.step(float(np.clip(a[0], 0, 1)))
    return env.summary()


best = None
for seed in (1, 2):
    print(f"### jerk-vision knee, seed {seed}")
    model = PPO("MlpPolicy", JerkWrapper(), verbose=0, seed=seed,
                policy_kwargs=dict(net_arch=[64, 64]))
    model.learn(total_timesteps=200_000)
    s = score(model)
    print(f"   -> {s['wh_per_km']:.1f} Wh/km | discomfort {s['discomfort']:.2f} "
          f"| jerkRMS {s['jerk_rms']:.3f} | engage/min {s['engage_per_min']:.2f}")
    model.save(os.path.join(HERE, f"ppo_jerk_s{seed}"))
    if best is None or s["discomfort"] < best[1]["discomfort"]:
        best = (seed, s)

print(f"\nBEST jerk-vision: seed {best[0]} -> {best[1]}")
print("blind knee reference: 587.2 Wh/km / 47.72 discomfort / 3.25 jerkRMS")
