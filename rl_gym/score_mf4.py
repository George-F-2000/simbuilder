"""score_mf4.py — the MotionSolve tournament referee (Bible 29.6).
Scores any deck MF4 on: full-band jerk RMS, ACCELERATION DISTURBANCES
(band-passed 2-20 Hz accel, RMS + peak - the AVL-style 'shiver' column),
rear engagement events, energy per km (battery power integral / distance),
and SOC drop. Usage: python score_mf4.py <name>=<path> [<name>=<path> ...]"""
import sys

import numpy as np
from asammdf import MDF
from scipy.signal import butter, filtfilt


def score(path):
    m = MDF(path)
    def g(ch):
        s = m.get(ch)
        return np.asarray(s.timestamps), np.asarray(s.samples, float)
    t, v = g("VehicleSpeed")                      # km/h
    _, a = g("AccelerationChassis")               # m/s^2
    _, tr = g("EM2Torque")
    _, pb = g("BattPower")
    _, soc = g("BattSOC")
    dt = float(np.median(np.diff(t)))
    fs = 1.0/dt
    jerk = np.gradient(a, dt)
    b, aa = butter(3, [2.0/(fs/2), min(20.0, 0.45*fs)/(fs/2)], btype="band")
    dist_sig = filtfilt(b, aa, a)
    awake = np.abs(tr) > 5.0
    engages = int(np.sum(np.diff(awake.astype(int)) != 0))
    km = float(np.trapezoid(v/3.6, t)/1000.0)
    wh = float(np.trapezoid(np.abs(pb), t)/3600.0)*(1000.0 if np.abs(pb).max() < 500 else 1.0)
    return {"km": km, "wh_per_km": wh/max(km, 1e-9),
            "soc_drop_pct": float((soc[0]-soc[-1]) if soc.max() > 2 else 100*(soc[0]-soc[-1])),
            "jerk_rms": float(np.sqrt(np.mean(jerk**2))),
            "disturb_rms": float(np.sqrt(np.mean(dist_sig**2))),
            "disturb_peak": float(np.max(np.abs(dist_sig))),
            "engage_events": engages,
            "eng_per_min": engages/max((t[-1]-t[0])/60.0, 1e-9)}


if __name__ == "__main__":
    rows = []
    for arg in sys.argv[1:]:
        name, path = arg.split("=", 1)
        s = score(path); s["name"] = name; rows.append(s)
    hdr = f"{'entrant':16s}{'km':>7}{'Wh/km':>8}{'SOCdrop%':>9}{'jerkRMS':>9}" \
          f"{'dist RMS':>9}{'dist pk':>8}{'wakes/min':>10}"
    print(hdr); print("-"*len(hdr))
    for s in rows:
        print(f"{s['name']:16s}{s['km']:7.2f}{s['wh_per_km']:8.1f}"
              f"{s['soc_drop_pct']:9.2f}{s['jerk_rms']:9.3f}"
              f"{s['disturb_rms']:9.3f}{s['disturb_peak']:8.2f}"
              f"{s['eng_per_min']:10.2f}")
