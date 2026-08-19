# -*- coding: utf-8 -*-
"""
calibration.py
================================================================================
The Calibration tab engine: tune the model against a REAL CAN log and KNOW
whether each change helped.

Loop: pick a real-log window -> replay the real driver's pedal against the
current knob settings (constants-only maneuvers - the memory-safe form) ->
score the overlay (RMSE + correlation for speed and front torque) -> bank
the attempt in a history with deltas vs previous and vs best.

KNOBS ARE CONFIG LAYERS ONLY (pedal map gain, EMS strategy, tyre LMY,
throttle smoothing). Physics is locked by design - George's rule, enforced
here rather than remembered. Every knob carries tooltip metadata: what it
does, which way to turn it, and what evidence set its default.
================================================================================
"""
import glob
import json
import os
import re
import shutil
import time

import numpy as np

import pedal_map
import pipeline

import json as _vlj
try:
    import sys as _vls
    _VLC = _vlj.load(open(os.path.join(
        os.path.dirname(_vls.executable) if getattr(_vls, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)),
        "vehicle_local.json")))
except Exception:
    _VLC = {}
MBD = r"C:\Users\George\OneDrive\Desktop\MBD - Copy For Testing"
OVL = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\OVERLAY - Real vs Virtual"
DEFAULT_REF = os.path.join(OVL, "REAL_mct_chunk_full.mf4")
DEFAULT_WINDOW = os.path.join(OVL, "replay_window.json")
TIRE_SRC = os.path.join(MBD, _VLC.get("tire_file", "demo_tire.tir"))
AERO = os.path.join(MBD, _VLC.get("aero_file", "demo_aero.aae"))
VEHJSON = os.path.join(MBD, _VLC.get("vehicle_json", "demo.vehicle.json"))
STEP_S = 2.0


def _state_path():
    return os.path.join(pipeline.app_dir(), "calib_state.json")


def _hist_path():
    return os.path.join(pipeline.app_dir(), "calib_history.json")


DEFAULT_KNOBS = {"pedal_gain": 1.00, "ems": "single_motor",
                 "lmy": 0.75, "smoothing_hz": 1.0}

KNOB_META = {
    "pedal_gain": {
        "label": "Pedal map gain",
        "range": [0.7, 1.3], "step": 0.02,
        "tip": ("How much MODEL pedal your real foot commands (a multiplier "
                "on the fitted foot-to-model map). Turn UP if the virtual "
                "speed UNDERSHOOTS the real trace; DOWN if it overshoots. "
                "Default 1.00 = the map fitted from your MCT dyno log "
                "(2026-07-26). This is throttle-cable calibration, not "
                "physics."),
    },
    "ems": {
        "label": "EMS strategy (which axles drive)",
        "options": ["single_motor", "traction", "even", "ratio_even",
                    "loss_optimal", "rear_only"],
        "tip": ("Which motors carry the torque. YOUR REAL CAR ran FRONT-ONLY "
                "for the entire MCT test (measured: rear torque = 0 for "
                "3.5 h), so single_motor (all-front) matches reality. The "
                "others are what-if strategies - unvalidated until the AWD "
                "log arrives; a custom map fitted from that log will appear "
                "here when it does."),
    },
    "lmy": {
        "label": "Tyre rolling-resistance scale (LMY)",
        "range": [0.5, 1.2], "step": 0.05,
        "tip": ("Scales the tyre's rolling drag. UP = more drag = the car "
                "coasts down faster and uses more energy; DOWN = the "
                "opposite. Default 0.75 = calibrated to the tyre's RATED "
                "Crr, validated within +4% of your dyno data. If the "
                "virtual car carries too much speed between pedal inputs, "
                "raise it slightly."),
    },
    "smoothing_hz": {
        "label": "Throttle smoothing (Hz)",
        "range": [0.5, 10.0], "step": 0.5,
        "tip": ("How quickly pedal movements reach the powertrain. 1 Hz = "
                "smooth (cuts motor-torque ripple ~10x - the validated "
                "tune); 10 Hz = crisp but rippled. Shapes transient "
                "response only - steady speeds are unaffected."),
    },
}


def get_state():
    knobs = dict(DEFAULT_KNOBS)
    try:
        knobs.update(json.load(open(_state_path(), encoding="utf-8")))
    except Exception:
        pass
    hist = []
    try:
        hist = json.load(open(_hist_path(), encoding="utf-8"))
    except Exception:
        pass
    return {"knobs": knobs, "meta": KNOB_META, "history": hist,
            "reference": {"log": DEFAULT_REF,
                          "ok": os.path.isfile(DEFAULT_REF) and os.path.isfile(DEFAULT_WINDOW)}}


def _save_knobs(knobs):
    json.dump(knobs, open(_state_path(), "w", encoding="utf-8"), indent=1)


def _append_history(row):
    hist = get_state()["history"]
    hist.append(row)
    json.dump(hist, open(_hist_path(), "w", encoding="utf-8"), indent=1)
    return hist


# ------------------------------------------------------------------ ADF build
def _hdr(name):
    return "$" + "-" * (75 - len(name)) + name + "\n"


def _std(ch, mx, mn, init):
    return (_hdr(ch + "_STANDARD") + "[%s_STANDARD]\n" % ch +
            "MAX_VALUE            = %g\nMIN_VALUE            = %g\n" % (mx, mn) +
            "SMOOTHING_FREQUENCY  = 10\nINITIAL_VALUE        = %g\n" % init)


def _ctrl(n):
    return ("STEERING_CONTROLLER    = 'OL_STEER'\n"
            "THROTTLE_CONTROLLER    = 'OL_THROTTLE_%d'\n" % n +
            "BRAKE_CONTROLLER       = 'OL_BRAKE_%d'\n" % n +
            "GEAR_CONTROLLER        = 'GEAR_CLUTCH_CONTROL'\n"
            "CLUTCH_CONTROLLER      = 'GEAR_CLUTCH_CONTROL'\n")


def _ol_const(n, channel, value):
    return (_hdr("OL_%s_%d" % (channel, n)) + "[OL_%s_%d]\n" % (channel, n) +
            "TAG                    = 'OPENLOOP'\n"
            "TYPE                   = 'CONSTANT'\n"
            "VALUE                  = %.4f\n" % value)


def _adf_constants(name, segs, vx0, smoothing_hz, thr0):
    s = _hdr("ALTAIR_HEADER") + "[ALTAIR_HEADER]\n"
    s += "FILE_TYPE    = 'ADF'\nFILE_VERSION = 2.0\nFILE_FORMAT  = 'ASCII'\n"
    s += "$ Scenario: %s - calibration replay (%d constant maneuvers)\n" % (name, len(segs))
    s += _hdr("UNITS") + "[UNITS]\n(BASE)\n"
    s += "{ length  force         angle           mass     time }\n"
    s += "  'mm'   'newton'      'radians'        'kg'    'sec'\n"
    s += _hdr("VEHICLE_IC") + "[VEHICLE_INITIAL_CONDITIONS]\n"
    s += "VX0               = %g\nVY0               = 0.0\nVZ0               = 0.0\n" % vx0
    s += "ENGINE_INIT_SPEED = 300\n"
    s += _std("STEER", 9.4248, -9.4248, 0)
    s += _hdr("THROTTLE_STANDARD") + "[THROTTLE_STANDARD]\n"
    s += "MAX_VALUE            = 1\nMIN_VALUE            = 0\n"
    s += "SMOOTHING_FREQUENCY  = %g\nINITIAL_VALUE        = %.4f\n" % (smoothing_hz, thr0)
    s += _std("BRAKE", 1, 0, 0) + _std("GEAR", 6, 1, 1) + _std("CLUTCH", 1, 0, 0)
    s += _hdr("MANEUVERS_LIST") + "[MANEUVERS_LIST]\n"
    s += "{name            simulation_time      h_max           print_interval }\n"
    for i, (dur, _) in enumerate(segs, 1):
        s += "'MANEUVER_%d'     %-20g 0.01            0.01            \n" % (i, dur)
    for i, (dur, val) in enumerate(segs, 1):
        s += _hdr("MANEUVER_%d" % i) + "[MANEUVER_%d]\nTASK = 'STANDARD'\n" % i + _ctrl(i)
        s += _ol_const(i, "THROTTLE", val) + _ol_const(i, "BRAKE", 0.0)
    s += _hdr("OL_STEER") + "[OL_STEER]\n"
    s += "TAG                    = 'OPENLOOP'\nTYPE                   = 'CONSTANT'\nVALUE                  = 0\n"
    s += _hdr("%GEAR_CLUTCH_CONTROL") + "$Used in case of models with IC Engine \n"
    s += "[GEAR_CLUTCH_CONTROL] \nTAG = 'ENGINE_SPEED'  \n(GEAR_SHIFT_MAP)      \n"
    s += "{G   US      DS      CT      CRT     TFD     TFT     CFT     TRD     TRT}    \n"
    for gg in range(1, 6):
        s += " %d   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05   \n" % gg
    return s


def _tire_with_lmy(lmy, run_root):
    txt = open(TIRE_SRC, encoding="utf-8", errors="replace").read()
    txt, n = re.subn(r"^(\s*LMY\s*=\s*)[\d.]+", r"\g<1>%.3f" % lmy, txt,
                     count=1, flags=re.M)
    dst = os.path.join(run_root, "calib_tire_lmy%03d.tir" % int(lmy * 100))
    open(dst, "w", encoding="utf-8").write(txt)
    return dst if n == 1 else TIRE_SRC


# ------------------------------------------------------------------ run+score
def run_calibration(settings, knobs, log=lambda s: None):
    """One calibration attempt: replay the reference window with the given
    knobs, score the overlay, append to history. Returns the history row."""
    knobs = {**DEFAULT_KNOBS, **(knobs or {})}
    _save_knobs(knobs)
    from asammdf import MDF
    w = json.load(open(DEFAULT_WINDOW, encoding="utf-8"))
    m = MDF(DEFAULT_REF)

    def ch(n):
        s_ = m.get(n)
        return np.asarray(s_.timestamps, float), np.asarray(s_.samples, float)

    tp, ped = ch("AccelPdlPos")
    tv, vv = ch("VehSpd_VCU")
    tF, FF = ch("F_MotTrq")
    m.close()
    tt = np.arange(w["t0"], w["t1"], 0.25)
    trel = tt - tt[0]
    ped_r = np.interp(tt, tp, ped)
    v_real = np.interp(tt, tv, vv)
    thr = np.array([pedal_map.real_to_model(p) for p in ped_r]) / 100.0
    thr = np.clip(thr * knobs["pedal_gain"], 0.0, 0.95)
    edges = list(np.arange(0.0, float(trel[-1]), STEP_S)) + [float(trel[-1])]
    if edges[-1] - edges[-2] < 0.5:
        edges.pop(-2)
    segs = []
    for a, b in zip(edges, edges[1:]):
        sel = (trel >= a - 1e-9) & (trel <= b + 1e-9)
        segs.append((b - a, float(np.mean(thr[sel]))))
    run_root = settings["runs_dir"]
    os.makedirs(run_root, exist_ok=True)
    tire = _tire_with_lmy(knobs["lmy"], run_root)
    v = json.load(open(VEHJSON, encoding="utf-8"))
    v["tirePath"] = tire
    v["aeroPath"] = AERO
    payload = {"deck_default": False, "generate_motors": True,
               "apply_mass": True, "tire_path": tire, "aero_path": AERO,
               "pack_voltage": 360.0,
               "ems": {"enabled": True, "strategy": knobs["ems"],
                       "params": {"mass_kg": 2746.94, "wheelbase_m": 3.094}},
               "spec": v}
    adf = _adf_constants("Calib_attempt", segs, v_real[0] * 1000 / 3.6,
                         knobs["smoothing_hz"], segs[0][1])
    t0 = time.time()
    rd, mf4 = pipeline.run_scenario(settings, "Calib_attempt", adf, log=log,
                                    viewer_launcher=False, vehicle=payload)
    mm = MDF(mf4)
    t2 = mm.get("VehicleSpeed").timestamps
    v2 = np.asarray(mm.get("VehicleSpeed").samples[:len(t2)], float)
    T1 = np.asarray(mm.get("EM1Torque").samples[:len(t2)], float)
    T2 = np.asarray(mm.get("EM2Torque").samples[:len(t2)], float)
    mm.close()
    vref = np.interp(t2, trel, v_real)
    Fref = np.interp(t2, np.asarray(tF) - w["t0"], np.clip(FF, 0, None))
    Tt = T1 + T2
    row = {
        "when": time.strftime("%m-%d %H:%M"),
        "knobs": knobs,
        "speed_rmse": round(float(np.sqrt(np.mean((v2 - vref) ** 2))), 2),
        "speed_corr": round(float(np.corrcoef(v2, vref)[0, 1]), 3),
        "torque_rmse": round(float(np.sqrt(np.mean((Tt - Fref) ** 2))), 1),
        "torque_corr": round(float(np.corrcoef(Tt, Fref)[0, 1]), 3),
        "minutes": round((time.time() - t0) / 60, 1),
        "mf4": mf4,
    }
    _append_history(row)
    for ext in ("mrf", "abf", "h3d"):
        for fp in glob.glob(os.path.join(rd, "*." + ext)):
            try:
                os.remove(fp)
            except OSError:
                pass
    return row
