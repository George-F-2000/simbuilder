"""soc_range_demo.py — the 'go farther' demonstration (Bible 29.6).
Drive repeated George Demand laps from SOC 0.75 down to the 0.30 floor in
the measured-reality gym. The stock map cannot see SOC; the champion can -
and may adapt its split as charge falls. Scorecard: km to the floor, Wh/km,
discomfort over the whole drive."""
import numpy as np
from stable_baselines3 import PPO

from rescore_all import MeasuredEnv
from policies import StockMapPolicy

FLOOR = 0.30


def drive_to_floor(policy_fn, tag):
    total_km = 0.0; total_wh = 0.0; disc = 0.0; laps = 0
    soc = 0.75
    while soc > FLOOR and laps < 12:
        env = MeasuredEnv(cycle="george_demand.txt", soc0=soc)
        obs = env.reset(); done = False
        while not done and env.soc > FLOOR:
            obs, _, done, _ = env.step(policy_fn(obs))
        s = env.summary()
        total_km += s["dist_km"]; total_wh += s["energy_wh"]
        disc += s["discomfort"]; soc = env.soc; laps += 1
    print(f"{tag:14s} floor reached after {total_km:6.2f} km | "
          f"{total_wh/max(total_km,1e-9):6.1f} Wh/km | discomfort sum {disc:6.1f} "
          f"| laps {laps}", flush=True)
    return total_km, total_wh, disc


stock = StockMapPolicy()
drive_to_floor(lambda o: stock(o), "stock map")
champ = PPO.load("ppo_v3_wc1_s1", device="cpu")
drive_to_floor(lambda o: float(np.clip(champ.predict(o, deterministic=True)[0][0], 0, 1)),
               "champion")
