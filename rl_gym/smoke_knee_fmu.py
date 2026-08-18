"""smoke_knee_fmu.py — first light for GeorgeEMS_Knee.fmu.
Runs the exported FMU standalone via fmpy (no MotionSolve): a 25 s story -
launch from standstill, pedal step to 60%, speeds ramped consistently -
then checks the vital signs and plots them (figs/8_knee_fmu_smoke.png)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fmpy import simulate_fmu

HERE = os.path.dirname(os.path.abspath(__file__))
FMU = os.path.join(os.path.dirname(os.path.dirname(HERE)), "Simulink EMS",
                   "GeorgeEMS_Knee.fmu")
from gym_env import R_WHEEL as R, G_F as GF, G_R as GR

t = np.arange(0, 25, 0.01)
throttle = np.where(t < 2, 0.0, 60.0)
v = np.clip((t - 2)*2.2, 0, 30)                      # ~0-100 km/h pull
rows = [(ti, th, vi, min(vi/R*GF, 1571.0), min(vi/R*GR, 1571.0))
        for ti, th, vi in zip(t, throttle, v)]
inp = np.array(rows, dtype=[("time", np.double), ("throttle", np.double),
                            ("vehicleSpeed", np.double),
                            ("motorSpeedFront", np.double),
                            ("motorSpeedRear", np.double)])

res = simulate_fmu(FMU, start_time=0, stop_time=25, input=inp,
                   output=["frontMotorTorque", "rearMotorTorque",
                           "SOC", "torqueRatioRear"])
tf, tr = res["frontMotorTorque"], res["rearMotorTorque"]
soc, ratio = res["SOC"], res["torqueRatioRear"]
checks = {
    "front torque responds (>50 Nm after pedal)": float(tf.max()) > 50,
    "torques finite": bool(np.isfinite(tf).all() and np.isfinite(tr).all()),
    "ratio in [0,1]": bool((ratio >= -1e-6).all() and (ratio <= 1 + 1e-6).all()),
    "SOC declines under load": float(soc[-1]) < float(soc[0]),
    "SOC sane (0.5-0.76)": 0.5 < float(soc[-1]) <= 0.7500001,
}
for k, ok in checks.items():
    print(("PASS  " if ok else "FAIL  ") + k)
print(f"peaks: front {tf.max():.0f} Nm, rear {tr.max():.0f} Nm, "
      f"SOC {soc[0]:.4f}->{soc[-1]:.4f}, ratio max {ratio.max():.3f}")

fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
axes[0].plot(res["time"], tf, label="front"); axes[0].plot(res["time"], tr, label="rear")
axes[0].set_ylabel("motor torque [Nm]"); axes[0].legend(); axes[0].grid(alpha=0.3)
axes[0].set_title("GeorgeEMS_Knee.fmu first light - 60% pedal pull, standalone via fmpy")
axes[1].plot(res["time"], ratio); axes[1].set_ylabel("rear share r"); axes[1].grid(alpha=0.3)
axes[2].plot(res["time"], soc); axes[2].set_ylabel("SOC"); axes[2].set_xlabel("time [s]")
axes[2].grid(alpha=0.3)
fig.tight_layout()
out = os.path.join(HERE, "figs", "8_knee_fmu_smoke.png")
fig.savefig(out, dpi=140)
print("plot ->", out)
