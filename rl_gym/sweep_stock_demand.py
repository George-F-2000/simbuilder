"""
sweep_stock_demand.py — measure the stock FMU's TRUE pedal->torque law.
(Bible Ch.29 demand-parity step; the Ch.27.4 'empirical twin' finally run.)

Drives the factory Motor_PMSM_dual.fmu standalone (fmpy, CoSim interface,
vcu_type=4 exactly as the deck sets it) across a pedal x speed grid, holds
each point 3 s to let its internal filters settle, and records what the
factory demand desk ACTUALLY delivers - including the coast band and regen.
Also records pedal-step transients for filter identification.

Products: stock_demand_law.npz + figs/10_stock_demand_law.png + key numbers.
Knee v2's demand desk becomes a 2-D lookup of this measurement - matched to
stock by construction, not by reverse-engineering guesses.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fmpy import extract, read_model_description, simulate_fmu

FMU = (r"C:\Program Files\Altair\2025\hwdesktop\hw\mdl\mdllib\Common"
       r"\FMU_Library\Motor\FMU_source\FMUs\win64\Motor_PMSM_dual.fmu")
HERE = os.path.dirname(os.path.abspath(__file__))
R_WHEEL, G_F, G_R = [RADIUS], 18.0, [RATIO]
W_MAX = 1571.0

unzip = extract(FMU)
md = read_model_description(FMU)
OUT = ["front motor torque", "rear motor torque",
       "combined motor torque demand", "torque ratio rear"]


def run_point(pedal, v, stop=3.0):
    sv = {"throttle": float(pedal), "vehicle speed": float(v),
          "motor speed front": float(min(v/R_WHEEL*G_F, W_MAX)),
          "motor speed rear": float(min(v/R_WHEEL*G_R, W_MAX)),
          "vcu_type": 4.0}
    res = simulate_fmu(unzip, model_description=md,
                       fmi_type="CoSimulation", start_time=0, stop_time=stop,
                       output_interval=0.01, start_values=sv, output=OUT)
    tail = res[res["time"] > stop - 0.5]
    return {k: float(np.mean(tail[k])) for k in OUT}


pedals = np.arange(0, 101, 5)
speeds = np.arange(0, 55.1, 2.5)
TF = np.zeros((len(pedals), len(speeds)))
TR = np.zeros_like(TF); TD = np.zeros_like(TF); RS = np.zeros_like(TF)
for i, p in enumerate(pedals):
    for j, v in enumerate(speeds):
        r = run_point(p, v)
        TF[i, j] = r["front motor torque"]; TR[i, j] = r["rear motor torque"]
        TD[i, j] = r["combined motor torque demand"]
        RS[i, j] = r["torque ratio rear"]
    print(f"pedal {p:3.0f}%: Tcomb @15m/s = {TF[i, 6] + TR[i, 6]:7.1f} Nm", flush=True)

np.savez(os.path.join(HERE, "stock_demand_law.npz"),
         pedals=pedals, speeds=speeds, TF=TF, TR=TR, TD=TD, RS=RS)

# transients: pedal steps at 15 m/s for filter identification
v = 15.0
base = {"vehicle speed": v, "motor speed front": min(v/R_WHEEL*G_F, W_MAX),
        "motor speed rear": min(v/R_WHEEL*G_R, W_MAX), "vcu_type": 4.0}
steps = [(10, 50), (50, 100), (50, 10), (100, 0)]
tr_traces = {}
t = np.arange(0, 6, 0.01)
for p0, p1 in steps:
    thr = np.where(t < 2, p0, p1)
    rows = [(ti, th, v, base["motor speed front"], base["motor speed rear"])
            for ti, th in zip(t, thr)]
    inp = np.array(rows, dtype=[("time", np.double), ("throttle", np.double),
                                ("vehicle speed", np.double),
                                ("motor speed front", np.double),
                                ("motor speed rear", np.double)])
    res = simulate_fmu(unzip, model_description=md,
                       fmi_type="CoSimulation", start_time=0, stop_time=6,
                       output_interval=0.01, start_values={"vcu_type": 4.0},
                       input=inp, output=OUT)
    tr_traces[f"{p0}to{p1}"] = np.column_stack(
        [res["time"], res["front motor torque"] + res["rear motor torque"]])
np.savez(os.path.join(HERE, "stock_demand_transients.npz"), **tr_traces)

# ---- figure ----
fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
Tcomb = TF + TR
for j, vv in ((0, 0.0), (6, 15.0), (12, 30.0), (20, 50.0)):
    axes[0].plot(pedals, Tcomb[:, j], "-o", ms=3, label=f"{vv*3.6:.0f} km/h")
axes[0].plot(pedals, (pedals/100.0)**2*590, "k--", alpha=0.6,
             label="knee v1 assumption (pedal² x 590)")
axes[0].set_xlabel("pedal [%]"); axes[0].set_ylabel("combined motor torque [Nm]")
axes[0].set_title("The TRUE stock pedal law (measured)\nvs knee v1's assumption")
axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)

cz = np.zeros(len(speeds))
for j in range(len(speeds)):
    col = Tcomb[:, j]
    k = np.where(col > 1.0)[0]
    cz[j] = pedals[k[0]] if len(k) else np.nan
axes[1].plot(speeds*3.6, cz, "-o", ms=4, color="tab:red")
axes[1].set_xlabel("vehicle speed [km/h]"); axes[1].set_ylabel("pedal where torque goes positive [%]")
axes[1].set_title("The coast band (measured)\nbelow the line = coast/regen territory")
axes[1].grid(alpha=0.3)

pc = axes[2].pcolormesh(speeds*3.6, pedals, RS, cmap="RdYlBu_r", vmin=0, vmax=1,
                        shading="auto")
fig.colorbar(pc, ax=axes[2], label="rear share")
axes[2].set_xlabel("vehicle speed [km/h]"); axes[2].set_ylabel("pedal [%]")
axes[2].set_title("Stock split behavior across the sweep\n(the demo EV map, exercised live)")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "figs", "10_stock_demand_law.png"), dpi=140)

i50, j15 = 10, 6
print(f"\nKEY: 50% pedal @ 54 km/h -> measured {Tcomb[i50, j15]:.1f} Nm "
      f"(deck run showed ~90; knee v1 assumed 147.6)")
print("saved: stock_demand_law.npz, stock_demand_transients.npz, "
      "figs/10_stock_demand_law.png")
