"""
train_rl.py — Step 3 of Bible Ch.28: train the 'George EMS' with PPO.
Needs the (one-time, ~2 GB) extras:  pip install gymnasium stable-baselines3
Then:  python train_rl.py [--steps 300000] [--cycle hwycol.txt]
Output: george_ems_ppo.zip (the trained brain) + george_rl_opt_trq_ratio.mat
(the brain flattened into a stock-shaped r_ch map, ready for SimBuilder's
EMS injection) + a baseline-style evaluation so you instantly see the score.
"""

import argparse
import os

import numpy as np

from gym_env import DemoSplitEnv
from policy_to_rch import flatten_to_rch

try:
    import gymnasium as gym
    from stable_baselines3 import PPO
except ImportError as e:
    raise SystemExit("Missing RL extras. Run:  pip install gymnasium "
                     "stable-baselines3   (one-time, ~2 GB)") from e


class GymWrapper(gym.Env):
    """Adapts DemoSplitEnv to the Gymnasium API SB3 expects."""

    def __init__(self, cycle, w_smooth):
        self.env = DemoSplitEnv(cycle=cycle, w_smooth=w_smooth)
        self.observation_space = gym.spaces.Box(low=np.array([0, -1.2, 0]),
                                                high=np.array([1.2, 1.2, 1]),
                                                dtype=np.float64)
        self.action_space = gym.spaces.Box(low=0.0, high=1.0, shape=(1,),
                                           dtype=np.float64)

    def reset(self, seed=None, options=None):
        return self.env.reset(), {}

    def step(self, action):
        obs, r, done, info = self.env.step(float(action[0]))
        return obs, r, done, False, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=300_000)
    ap.add_argument("--cycle", default="hwycol.txt")
    ap.add_argument("--w_smooth", type=float, default=0.05)
    args = ap.parse_args()

    env = GymWrapper(args.cycle, args.w_smooth)
    model = PPO("MlpPolicy", env, verbose=1,
                policy_kwargs=dict(net_arch=[64, 64]))
    model.learn(total_timesteps=args.steps)

    here = os.path.dirname(os.path.abspath(__file__))
    model.save(os.path.join(here, "george_ems_ppo"))

    def policy(v_mps, t_dem_nm, soc=0.75):
        obs = np.array([v_mps/55.55, t_dem_nm/591.0, soc])
        a, _ = model.predict(obs, deterministic=True)
        return float(np.clip(a[0], 0, 1))

    mat = flatten_to_rch(policy, os.path.join(here, "george_rl_opt_trq_ratio.mat"))
    print(f"trained brain saved; flattened map -> {mat}")

    # instant scorecard vs the same gym
    e = DemoSplitEnv(cycle=args.cycle)
    obs = e.reset(); done = False
    while not done:
        obs, _, done, _ = e.step(policy(obs[0]*55.55, obs[1]*591.0, obs[2]))
    print("george_rl on", args.cycle, "->", e.summary())


if __name__ == "__main__":
    main()
