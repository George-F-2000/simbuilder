# -*- coding: utf-8 -*-
"""Performance event: ONE scenario that yields both headline numbers.

A single wide-open-throttle pull from rest through 70 mph. From that one run
we extract:
  * 0-60 mph WITH a 1-foot (0.3048 m) rollout - the industry-standard way
    manufacturers quote it: the clock starts after the car has rolled one
    foot, not at throttle application.
  * 50-70 mph - a segment of the same pull. For a single-speed EV with no
    gearbox the WOT torque at a given wheel speed is history-independent, so
    this equals a standalone 50->70 roll-on (the model has no pack-power or
    thermal derate that would make a from-launch pass differ - see
    MODEL_BIBLE section 8; a real car may differ at the top).

The launch begins at the 250 mm/s creep floor (true v=0 is a tyre
singularity - MODEL_BIBLE rule 7); the 1-foot rollout absorbs that tiny
initial creep, which is exactly what rollout is for.
"""
import numpy as np

MPH = 1609.344 / 3600.0 * 1000.0        # 1 mph in mm/s
V60 = 60 * MPH
V50 = 50 * MPH
V70 = 70 * MPH
ROLLOUT_M = 0.3048                       # 1 foot

# imported lazily so this module is usable both in-app and from scripts
def _helpers():
    try:
        from avl_tipin import _hdr, _std, _ctrl, _end, _ol_thr, _ol_brk
    except ImportError:
        import sys, os
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "demo EV Analysis", "scripts"))
        from avl_tipin import _hdr, _std, _ctrl, _end, _ol_thr, _ol_brk
    return _hdr, _std, _ctrl, _end, _ol_thr, _ol_brk


def build_perf_adf(name, pct=100, sim_cap_s=30):
    """WOT pull from the creep floor until the car passes 70 mph."""
    _hdr, _std, _ctrl, _end, _ol_thr, _ol_brk = _helpers()
    p = pct / 100.0
    s = _hdr("ALTAIR_HEADER") + "[ALTAIR_HEADER]\n"
    s += "FILE_TYPE    = 'ADF'\nFILE_VERSION = 2.0\nFILE_FORMAT  = 'ASCII'\n"
    s += "$ Scenario: %s - performance pull %d%% (0-60 w/ 1ft rollout + 50-70)\n" % (name, pct)
    s += _hdr("UNITS") + "[UNITS]\n(BASE)\n"
    s += "{ length  force         angle           mass     time }\n"
    s += "  'mm'   'newton'      'radians'        'kg'    'sec'\n"
    s += _hdr("VEHICLE_IC") + "[VEHICLE_INITIAL_CONDITIONS]\n"
    s += "VX0               = 250\nVY0               = 0.0\nVZ0               = 0.0\n"
    s += "ENGINE_INIT_SPEED = 300\n"
    s += _std("STEER", 9.4248, -9.4248, 0) + _std("THROTTLE", 1, 0, 0)
    s += _std("BRAKE", 1, 0, 0) + _std("GEAR", 6, 1, 1) + _std("CLUTCH", 1, 0, 0)
    s += _hdr("MANEUVERS_LIST") + "[MANEUVERS_LIST]\n"
    s += "{name            simulation_time      h_max           print_interval }\n"
    s += "'MANEUVER_1'     %-20d 0.01            0.01            \n" % sim_cap_s
    s += _hdr("MANEUVER_1") + "[MANEUVER_1]\nTASK = 'STANDARD'\n" + _ctrl(1)
    s += _end("GT", V70)
    # near-instant WOT (0.1 s to floor it) - a performance launch, not a ramp
    s += _ol_thr(1, "STEP({%%TIME},0,{THROTTLE_0},0.1,%.4f)" % p) + _ol_brk(1)
    s += _hdr("OL_STEER") + "[OL_STEER]\n"
    s += "TAG                    = 'OPENLOOP'\nTYPE                   = 'CONSTANT'\nVALUE                  = 0\n"
    s += _hdr("%GEAR_CLUTCH_CONTROL") + "$Used in case of models with IC Engine \n"
    s += "[GEAR_CLUTCH_CONTROL] \nTAG = 'ENGINE_SPEED'  \n(GEAR_SHIFT_MAP)      \n"
    s += "{G   US      DS      CT      CRT     TFD     TFT     CFT     TRD     TRT}    \n"
    for gg in range(1, 6):
        s += " %d   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05   \n" % gg
    return s


def extract_perf(t, v_kmh, batt_kw=None):
    """0-60 (rollout-corrected), 50-70, and supporting numbers from one pull."""
    t = np.asarray(t, float); v = np.asarray(v_kmh, float)
    vms = v / 3.6
    dist = np.concatenate([[0.0], np.cumsum(0.5 * (vms[1:] + vms[:-1]) * np.diff(t))])
    v_mmps = v * 1000.0 / 3.6

    def t_at_speed(target_mmps):
        i = np.argmax(v_mmps >= target_mmps)
        return float(t[i]) if v_mmps.max() >= target_mmps else None

    def t_at_dist(d):
        i = np.argmax(dist >= d)
        return float(t[i]) if dist.max() >= d else None

    t_roll = t_at_dist(ROLLOUT_M)
    t60 = t_at_speed(V60); t50 = t_at_speed(V50); t70 = t_at_speed(V70)
    a = np.gradient(vms, t)
    out = {
        "rollout_m": ROLLOUT_M,
        "t_rollout_s": round(t_roll, 3) if t_roll is not None else None,
        "zero_to_60_s": round(t60 - t_roll, 2) if (t60 and t_roll is not None) else None,
        "zero_to_60_no_rollout_s": round(t60 - float(t[0]), 2) if t60 else None,
        "fifty_to_70_s": round(t70 - t50, 2) if (t50 and t70) else None,
        "peak_accel_ms2": round(float(a.max()), 2),
        "peak_accel_g": round(float(a.max() / 9.80665), 3),
        "vmax_kmh": round(float(v.max()), 1),
    }
    if batt_kw is not None:
        out["peak_batt_kw"] = round(float(np.asarray(batt_kw, float).max()), 0)
    return out
