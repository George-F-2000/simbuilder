"""remeasure_demand_law.py - the stock demand law from the DECK FMU (Bible 30.13).
The Aug-18 law was measured on the Altair library FMU (generic motor maps);
the law is g(pedal, v) x sum of motor max-torque envelopes, so it must be
re-measured on the FMU the deck actually runs (real AAM/SRM maps).
One pass over the coarse grid (0..55 m/s by 2.5) plus the fine low-speed
columns (0.25..2.0 by 0.25) that fine_patch.py added, 3 s per point.
Writes stock_demand_law_realmaps.npz, backs up the old .mat, and exports
Simulink EMS/stock_demand_law.mat for the v2/champion builds."""
import json
import os
import shutil
import sys
import time

import numpy as np
from fmpy import extract, read_model_description, simulate_fmu
from scipy.io import loadmat, savemat

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gym_env import R_WHEEL, G_F, G_R

_lc = {}
try:
    _lc = json.load(open(os.path.join(os.path.dirname(HERE), "vehicle_local.json")))
except Exception:
    pass
DATA_ROOT = _lc.get("data_root", "C:/demo_data")
FMU = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106/Motor_PMSM_dual.fmu"
MAT = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\stock_demand_law.mat"
W_MAX = 2461.0     # real front map grid end (rad/s)
OUT = ["front motor torque", "rear motor torque", "combined motor torque demand", "torque ratio rear"]

unzip = extract(FMU)
md = read_model_description(FMU)


def run_point(pedal, v, stop=3.0):
    sv = {"throttle": float(pedal), "vehicle speed": float(v),
          "motor speed front": float(min(v/R_WHEEL*G_F, W_MAX)),
          "motor speed rear": float(min(v/R_WHEEL*G_R, W_MAX)),
          "vcu_type": 4.0}
    res = simulate_fmu(unzip, model_description=md, fmi_type="CoSimulation",
                       start_time=0, stop_time=stop, output_interval=0.01,
                       start_values=sv, output=OUT)
    tail = res[res["time"] > stop - 0.5]
    return {k: float(np.mean(tail[k])) for k in OUT}


pedals = np.arange(0, 101, 5)
speeds = np.unique(np.concatenate([np.arange(0, 55.1, 2.5), np.arange(0.25, 2.01, 0.25)]))
TF = np.zeros((len(pedals), len(speeds))); TR = np.zeros_like(TF); TD = np.zeros_like(TF); RS = np.zeros_like(TF)
t0 = time.time()
for i, p in enumerate(pedals):
    for j, v in enumerate(speeds):
        r = run_point(p, v)
        TF[i, j], TR[i, j], TD[i, j], RS[i, j] = (r["front motor torque"], r["rear motor torque"],
                                                  r["combined motor torque demand"], r["torque ratio rear"])
    print(f"pedal {p:3.0f}%: T @0.5 m/s {TF[i, 2]+TR[i, 2]:7.1f}  @15 m/s {TF[i, np.argmin(abs(speeds-15))]+TR[i, np.argmin(abs(speeds-15))]:7.1f} Nm"
          f"   ({(time.time()-t0)/60:.1f} min)", flush=True)

T = TF + TR
np.savez(os.path.join(HERE, "stock_demand_law_realmaps.npz"), pedals=pedals, speeds=speeds, TF=TF, TR=TR, TD=TD, RS=RS)
# cross-check against the analytical rescale of the old law
old = loadmat(MAT); po, so, To = np.asarray(old["ped_bp"]).ravel(), np.asarray(old["spd_bp"]).ravel(), np.asarray(old["Tmap"], float)
print("\nold law max %.1f -> new law max %.1f Nm; regen floor old %.1f -> new %.1f" % (To.max(), T.max(), To.min(), T.min()))
for v in (0.5, 5, 14, 20, 28):
    j = np.argmin(abs(speeds - v)); jo = np.argmin(abs(so - v))
    print(f"  v {v:4.1f}: T100 old {To[-1, jo]:6.1f} new {T[-1, j]:6.1f} | T50 old {To[np.argmin(abs(po-50)), jo]:6.1f} new {T[np.argmin(abs(pedals-50)), j]:6.1f} | T0 old {To[0, jo]:7.1f} new {T[0, j]:7.1f}")
bak = MAT.replace(".mat", "_genericmaps_20260818.mat")
if not os.path.exists(bak):
    shutil.copy(MAT, bak)
savemat(MAT, {"ped_bp": pedals.astype(float), "spd_bp": speeds.astype(float), "Tmap": T})
print("exported ->", MAT, "| backup ->", bak)
