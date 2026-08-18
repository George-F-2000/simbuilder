"""fine_patch.py — fine low-speed re-sweep of the stock demand law, merged.
The 2.5 m/s grid linearized the near-standstill law into a regen cliff that
stalled the creep phase (Bible 29.3). Re-measure v = 0.25..2.0 m/s at every
pedal, insert the columns, re-export stock_demand_law.mat for the v2 build."""
import numpy as np
from fmpy import extract, read_model_description, simulate_fmu
from scipy.io import savemat

FMU = (r"C:\Program Files\Altair\2025\hwdesktop\hw\mdl\mdllib\Common"
       r"\FMU_Library\Motor\FMU_source\FMUs\win64\Motor_PMSM_dual.fmu")
from gym_env import R_WHEEL as R, G_F as GF, G_R as GR
WM = 1571.0
unzip = extract(FMU); md = read_model_description(FMU)
OUT = ["front motor torque", "rear motor torque"]

d = np.load("stock_demand_law.npz")
peds, spds, T = d["pedals"], d["speeds"], d["TF"] + d["TR"]

fine_v = np.array([0.25, 0.5, 0.75, 1.0, 1.5, 2.0])
cols = np.zeros((len(peds), len(fine_v)))
for j, v in enumerate(fine_v):
    for i, p in enumerate(peds):
        sv = {"throttle": float(p), "vehicle speed": float(v),
              "motor speed front": float(min(v/R*GF, WM)),
              "motor speed rear": float(min(v/R*GR, WM)), "vcu_type": 4.0}
        r = simulate_fmu(unzip, model_description=md, fmi_type="CoSimulation",
                         start_time=0, stop_time=2.0, output_interval=0.01,
                         start_values=sv, output=OUT)
        tail = r[r["time"] > 1.5]
        cols[i, j] = float(np.mean(tail["front motor torque"]
                                   + tail["rear motor torque"]))
    print(f"v={v:4.2f} m/s done: 0%-pedal T = {cols[0, j]:7.2f} Nm", flush=True)

spds_new = np.concatenate([[spds[0]], fine_v, spds[1:]])
T_new = np.concatenate([T[:, :1], cols, T[:, 1:]], axis=1)
order = np.argsort(spds_new)
spds_new, T_new = spds_new[order], T_new[:, order]
np.savez("stock_demand_law_fine.npz", pedals=peds, speeds=spds_new, T=T_new)
savemat(r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\stock_demand_law.mat",
        {"ped_bp": peds.astype(float), "spd_bp": spds_new.astype(float),
         "Tmap": T_new.astype(float)})
print(f"merged map: {T_new.shape}, low-speed 0%-pedal row now:",
      np.round(T_new[0, :8], 1))
