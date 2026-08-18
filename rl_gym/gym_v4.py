"""gym_v4.py — pedal steps + creep demand in the gym (Bible 29.8).
Two modes inside one 124 s event schedule, per George's order:
- 'pedal' windows: OPEN-LOOP pedal steps (instant input, like the deck ADF);
  demand = measured factory map at (pedal, v) -> 50 ms filter. AVL-style
  tip-ins/outs with named pedal levels.
- 'speed' windows: the closed-loop driver, including CREEP HOLDS at 0.25 m/s
  - the crawl regime that killed the champion in the deck, now trainable.
Same referee, same reward, same delivery guarantee as v3."""
import os

import numpy as np

from train_v3 import MeasuredEnv, PEDS, SPDS, TMAP, ALPHA

HERE = os.path.dirname(os.path.abspath(__file__))

# (t_end, mode, value): pedal % (open loop) or target speed m/s (closed loop)
SCHEDULE = [
    (6,  "speed", 0.25),   # creep hold (driveaway prep)
    (11, "pedal", 30),     # tip-in 30
    (14, "pedal", 10),     # tip-out
    (19, "pedal", 50),     # tip-in 50
    (22, "pedal", 10),
    (27, "pedal", 70),     # tip-in 70
    (30, "pedal", 0),      # full lift -> regen
    (36, "speed", 0.25),   # brake down to creep, hold
    (41, "pedal", 100),    # WOT launch
    (44, "pedal", 20),
    (54, "speed", 16.7),   # settle to 60 km/h cruise
    (59, "pedal", 80),     # passing tip-in
    (62, "pedal", 15),
    (70, "speed", 8.0),    # city pace
    (76, "speed", 0.25),   # decel to creep, hold
    (81, "pedal", 60),     # tip-in 60 from crawl
    (84, "pedal", 5),      # deep lift
    (94, "speed", 25.0),   # build to 90 km/h
    (99, "pedal", 90),     # high-speed punch
    (102, "pedal", 10),
    (112, "speed", 0.25),  # long decel to creep hold
    (118, "pedal", 40),    # moderate tip-in
    (124, "speed", 0.0),   # stop
]


class PedalCreepEnv(MeasuredEnv):
    """v4: schedule-driven mix of open-loop pedal events and speed targets."""

    def __init__(self, **kw):
        kw.setdefault("cycle", "george_demand.txt")   # reused only for length
        super().__init__(**kw)
        self.t_grid = np.arange(0.0, SCHEDULE[-1][0], 0.1)
        self.v_tgt = np.zeros_like(self.t_grid)       # rebuilt for speed mode

    def _sched(self):
        t = self.k*0.1
        for t_end, mode, val in SCHEDULE:
            if t < t_end:
                return mode, val
        return "speed", 0.0

    def _demand(self):
        mode, val = self._sched()
        if mode == "pedal":
            raw = float(np.interp(val, PEDS,
                        [np.interp(self.v, SPDS, TMAP[i, :]) for i in range(len(PEDS))]))
        else:
            vt = val
            # v4.1: gentle creep driver - crawl targets get a soft accel
            # clamp so the driver eases to 0.25 m/s instead of bang-banging
            amax = 0.6 if vt < 1.0 else 5.0
            a_des = np.clip((vt - self.v)/0.5, -amax, amax)
            from gym_env import MASS, R_WHEEL, ETA_DRIVELINE, G_F, G_R
            f = MASS*a_des + self._road_load(self.v)
            raw = float(np.clip(f*R_WHEEL/(self.g_mix*ETA_DRIVELINE), -591, 591))
            raw = float(np.clip(raw, float(np.interp(self.v, SPDS, TMAP[0, :])),
                                float(np.interp(self.v, SPDS, TMAP[-1, :]))))
        self._fdem = ALPHA*getattr(self, "_fdem", 0.0) + (1 - ALPHA)*raw
        return self._fdem


if __name__ == "__main__":
    import gymnasium as gym
    from stable_baselines3 import PPO

    class W(gym.Env):
        def __init__(self, wc):
            self.env = PedalCreepEnv(w_comfort=wc)
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
        e = PedalCreepEnv()
        obs = e.reset(); done = False
        while not done:
            obs, _, done, _ = e.step(fn(obs))
        return e.summary()

    from policies import StockMapPolicy
    sp = StockMapPolicy()
    s = score(lambda o: sp(o))
    print(f"{'stock map':14s} {s['wh_per_km']:7.1f} Wh/km | disc {s['discomfort']:6.2f} "
          f"| jerk {s['jerk_rms']:.3f} | wakes/min {s['engage_per_min']:.2f}", flush=True)
    for wc in (0.0, 1.0):
        for seed in (1, 2):
            m = PPO("MlpPolicy", W(wc), verbose=0, seed=seed,
                    policy_kwargs=dict(net_arch=[64, 64]))
            m.learn(total_timesteps=200_000)
            s = score(lambda o: float(np.clip(m.predict(o, deterministic=True)[0][0], 0, 1)))
            print(f"v4 wc{wc:g} s{seed:d}    {s['wh_per_km']:7.1f} Wh/km | disc "
                  f"{s['discomfort']:6.2f} | jerk {s['jerk_rms']:.3f} "
                  f"| wakes/min {s['engage_per_min']:.2f}", flush=True)
            m.save(os.path.join(HERE, f"ppo_v4_wc{wc:g}_s{seed}"))
    print("v4 done")
