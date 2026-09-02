"""fig18_realmaps.py - operating points vs motor envelopes (Bible 30.8).
Every torque/speed sample of the champion and knee runs on the healed car,
against the Altair generic envelopes the learned FMUs used to clip to and
the real maps they clip to now. Shows why the swap changed nothing here."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from asammdf import MDF
from scipy.io import loadmat

_lc = {}
try:
    _lc = json.load(open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "vehicle_local.json")))
except Exception:
    pass
R = os.path.join(_lc.get("data_root", "C:/demo_data"), "healed_runs")
E = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS"
MF4 = "AVLlit_tipin_50pct_avldrive.mf4"
runs = {"champion": os.path.join(R, "champion_20260902_161844", MF4),
        "knee v2": os.path.join(R, "knee_v2_20260902_154939", MF4)}
envs = {"front": (("Altair generic", E + r"\stock_fmu_data\one_strlineacc_0_frnt_motor_data.mat"),
                  ("real map", E + r"\real_motor_maps\deck_frnt_motor_data.mat")),
        "rear": (("Altair generic", E + r"\stock_fmu_data\one_strlineacc_0_rear_motor_data.mat"),
                 ("real map", E + r"\real_motor_maps\deck_rear_motor_data.mat"))}
fig, ax = plt.subplots(1, 2, figsize=(12, 5))
for a_, (axle, tq, sp) in zip(ax, (("front", "EM1Torque", "EM1Speed"), ("rear", "EM2Torque", "EM2Speed"))):
    for (lab, p), ls in zip(envs[axle], ("--", "-")):
        d = loadmat(p); s = np.asarray(d["m_spd_data"]).ravel()*60/(2*np.pi); e = np.asarray(d["m_max_trq"]).ravel()
        a_.plot(s, e, ls, color="k", lw=1.3, label=axle + " envelope: " + lab)
    for (who, p), c in zip(runs.items(), ("#d62728", "#1f77b4")):
        m = MDF(p)
        T = np.abs(np.asarray(m.get(tq).samples, float)); w = np.asarray(m.get(sp).samples, float)
        a_.scatter(w, T, s=4, color=c, alpha=0.5, label=who + " operating points")
    a_.set_xlabel(axle + " motor speed [rpm]"); a_.set_ylabel("|torque| [Nm]")
    a_.set_xlim(0, 12000 if axle == "front" else 9500); a_.grid(alpha=0.3); a_.legend(fontsize=8)
ax[0].set_title("Healed-car tip-in 50%: where the motors actually operate")
fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs", "18_envelope_headroom.png")
fig.savefig(out, dpi=150); print("saved ->", out)
