"""creep_smoke.py — verify the v2.1 creep feature before spending solver time.
Three steady points per FMU:
  (throttle 0,  v 0.5)  expect net POSITIVE demand (creep ~10 Nm through filter)
  (throttle 0,  v 3.0)  expect the plain coast law (creep fully tapered out)
  (throttle 50, v 0.5)  expect the map's drive torque (gate off, no double-dip)
"""
import numpy as np
from fmpy import simulate_fmu

FMUS = {
    "knee_v2": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Knee_v2.fmu",
    "champion": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu",
}
CASES = [(0.0, 0.5), (0.0, 3.0), (50.0, 0.5)]
OUT = ["frontMotorTorque", "rearMotorTorque", "combMotorTorqueDemand"]

fail = False
for tag, path in FMUS.items():
    print(f"\n{tag}:", flush=True)
    got = {}
    for ped, v in CASES:
        w = v * 25.0  # generic low-speed motor spin; envelopes nowhere near
        dtype = [("time", np.float64), ("motorSpeedRear", np.float64),
                 ("motorSpeedFront", np.float64), ("throttle", np.float64),
                 ("vehicleSpeed", np.float64)]
        inp = np.array([(0.0, w, w, ped, v), (3.0, w, w, ped, v)], dtype=dtype)
        res = simulate_fmu(path, start_time=0, stop_time=3.0,
                           output_interval=0.1, input=inp, output=OUT)
        row = {k: float(res[k][-1]) for k in OUT}
        got[(ped, v)] = row
        print(f"  ped {ped:4.0f}%  v {v:.1f} m/s -> front {row['frontMotorTorque']:7.2f}"
              f"  rear {row['rearMotorTorque']:7.2f}"
              f"  comb {row['combMotorTorqueDemand']:7.2f}", flush=True)
    creep_lift = got[(0.0, 0.5)]["combMotorTorqueDemand"] - got[(0.0, 3.0)]["combMotorTorqueDemand"]
    ok = (got[(0.0, 0.5)]["combMotorTorqueDemand"] > 3.0
          and creep_lift > 6.0
          and got[(50.0, 0.5)]["combMotorTorqueDemand"] > 50.0)
    print(f"  creep lift vs 3 m/s: {creep_lift:+.2f} Nm  ->  {'PASS' if ok else 'FAIL'}",
          flush=True)
    fail = fail or not ok

raise SystemExit(1 if fail else 0)
