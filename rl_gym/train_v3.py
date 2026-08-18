"""train_v3.py — retrain personalities against the MEASURED demand desk.
Gym v3 = gym v2 + reality patch (Bible 29.4): demand capped by the measured
factory law (incl. regen depth), 50 ms demand filter, and the v2 delivery
guarantee (r_min rear assist) so training authority == deck authority.
3 comfort weights x 2 seeds, George Demand cycle, 200k steps each."""
import os

import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO

from gym_env import DemoSplitEnv, DT, T_DEM_MAX

HERE = os.path.dirname(os.path.abspath(__file__))
d = np.load(os.path.join(HERE, "stock_demand_law_fine.npz"))
PEDS, SPDS, TMAP = d["pedals"], d["speeds"], d["T"]
TMAX_V = TMAP[-1, :]          # measured 100%-pedal law vs speed
TMIN_V = TMAP[0, :]           # measured 0%-pedal (regen) law vs speed
ALPHA = float(np.exp(-DT/0.05))   # 50 ms filter at gym step


class MeasuredEnv(DemoSplitEnv):
    """Demand shaped by the measured factory law + delivery guarantee."""

    def reset(self):
        self._fdem = 0.0
        return super().reset()

    def _demand(self):
        raw = super()._demand()
        tmax = float(np.interp(self.v, SPDS, TMAX_V))
        tmin = float(np.interp(self.v, SPDS, TMIN_V))
        raw = float(np.clip(raw, tmin, tmax))
        self._fdem = ALPHA*getattr(self, '_fdem', 0.0) + (1 - ALPHA)*raw
        return self._fdem

    def step(self, r):
        t_dem = self._fdem if hasattr(self, "_fdem") else 0.0
        env_f = self.front.max_trq(min(self.v/[RADIUS]*18.0, 1571.0))
        r_min = max(0.0, (abs(t_dem) - env_f)/max(abs(t_dem), 1.0))
        return super().step(max(float(r), min(r_min, 1.0)))


class W(gym.Env):
    def __init__(self, wc):
        self.env = MeasuredEnv(cycle="george_demand.txt", w_comfort=wc)
        self.observation_space = gym.spaces.Box(
            low=np.array([0, -1.2, 0]), high=np.array([1.2, 1.2, 1]), dtype=np.float64)
        self.action_space = gym.spaces.Box(0.0, 1.0, (1,), np.float64)

    def reset(self, seed=None, options=None):
        return self.env.reset(), {}

    def step(self, a):
        o, r, dn, i = self.env.step(float(a[0]))
        return o, r, dn, False, i


def score(model):
    e = MeasuredEnv(cycle="george_demand.txt")
    obs = e.reset(); done = False
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, _, done, _ = e.step(float(np.clip(a[0], 0, 1)))
    return e.summary()


if __name__ == "__main__":
    rows = []
    for wc in (0.0, 1.0, 10.0):
        for seed in (1, 2):
            m = PPO("MlpPolicy", W(wc), verbose=0, seed=seed,
                    policy_kwargs=dict(net_arch=[64, 64]))
            m.learn(total_timesteps=200_000)
            s = score(m); s["wc"], s["seed"] = wc, seed
            rows.append(s)
            m.save(os.path.join(HERE, f"ppo_v3_wc{wc:g}_s{seed}"))
            print(f"wc={wc:<4g} seed {seed}: {s['wh_per_km']:.1f} Wh/km | "
                  f"discomfort {s['discomfort']:.2f} | jerkRMS {s['jerk_rms']:.3f} | "
                  f"engage/min {s['engage_per_min']:.2f}", flush=True)
    import json
    json.dump(rows, open(os.path.join(HERE, "v3_results.json"), "w"), default=float, indent=2)
    print("done -> v3_results.json")
