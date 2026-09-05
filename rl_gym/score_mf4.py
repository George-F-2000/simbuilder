"""score_mf4.py — the MotionSolve tournament referee (Bible 29.6).
Scores any deck MF4 on: full-band jerk RMS, ACCELERATION DISTURBANCES
(band-passed 2-20 Hz accel, RMS + peak - the AVL-style 'shiver' column),
rear engagement events, energy per km (battery power integral / distance),
and SOC drop. Usage: python score_mf4.py <name>=<path> [<name>=<path> ...]"""
import sys

import numpy as np
from asammdf import MDF
from scipy.signal import butter, filtfilt


_MAPS = None


def _common_loss_maps():
    """Deck-FMU motor efficiency maps (the same for every entrant) + the stock
    FMU's inverter/converter/battery loss constants -> ONE loss model."""
    global _MAPS
    if _MAPS is None:
        import os
        from scipy.io import loadmat
        from scipy.interpolate import RegularGridInterpolator as RGI
        d = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\real_motor_maps"
        _MAPS = {}
        for tag, f in (("EM1", "deck_frnt_motor_data.mat"), ("EM2", "deck_rear_motor_data.mat")):
            x = loadmat(os.path.join(d, f))
            sp = np.asarray(x["m_map_eff_spd"]).ravel()
            tq = np.asarray(x["m_map_eff_trq"]).ravel(); e = np.asarray(x["m_eff_map"], float)
            tr = np.asarray(x["m_map_eff_trq_regen"]).ravel(); er = np.asarray(x["m_eff_map_regen"], float)
            _MAPS[tag] = (RGI((sp, tq), np.nan_to_num(e), bounds_error=False, fill_value=None),
                          RGI((sp, tr), np.nan_to_num(er), bounds_error=False, fill_value=None))
    return _MAPS


def common_loss_battery_power(m):
    """Battery power [W] rebuilt from motor torque x speed through the common
    loss model: motor efficiency map (motoring / regen), inverter 0.95,
    converter 0.95, battery 5% each way (stock FMU parameters)."""
    maps = _common_loss_maps()
    P = None
    for tag in ("EM1", "EM2"):
        T = np.asarray(m.get(tag + "Torque").samples, float)
        w = np.asarray(m.get(tag + "Speed").samples, float) * 2*np.pi/60   # 1/min -> rad/s
        mech = T*w
        eta_m = np.clip(maps[tag][0](np.column_stack([w, np.abs(T)])), 0.3, 1.0)
        eta_r = np.clip(maps[tag][1](np.column_stack([w, T])), 0.3, 1.0)
        chain = 0.95*0.95
        p = np.where(mech >= 0, mech/(eta_m*chain)/0.95, mech*eta_r*chain*0.95)
        P = p if P is None else P + p
    return P


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
    # unit heuristic on the 99th percentile, not the max: the stock FMU's launch
    # jolt can spike BattPower and flip a kW channel to 'W' (2026-09-05)
    wh = float(np.trapezoid(np.abs(pb), t)/3600.0)*(1000.0 if np.percentile(np.abs(pb), 99) < 500 else 1.0)
    try:
        pc = common_loss_battery_power(m)
        wh_common = float(np.trapezoid(pc, t)/3600.0)          # NET Wh, regen credited
    except Exception:
        wh_common = float("nan")
    return {"km": km, "wh_per_km": wh/max(km, 1e-9),
            "wh_per_km_common": wh_common/max(km, 1e-9),
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
