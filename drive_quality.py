"""
drive_quality.py
================================================================================
Drive Quality metrics - an exact port of the EVC_DriveQuality.mlapp "Drive
Quality" tab (EV Challenge / Mobility Challenge scoring), computed on any run
MF4 or imported log. Targets live in dq_targets.json (extracted from the
team's targets workbook, 2025-01-17 edition).

METRICS (per tip-in event, classed by pedal 10/20/30/40/50/60/100 %):
  Response Delay  time from pedal movement until filtered accel rises
                  +0.3 m/s^2 above its value at the pedal step. Target 0.3 s.
  tARM            transient accel response = max d(MovMeanAccel)/dt in the
                  event window [m/s^3]. Targets 3..15 by class.
  ARM             accel sampled at the class's target speeds vs the target
                  curve. Per point: |diff| < 0.25 -> 1.0; < 0.5 -> 0.75;
                  else 0.5 if accel >= 0, 0 if negative. Class = mean.
Preprocessing mirrors the MATLAB app: MovMeanAccel = Butterworth low-pass
(order 2, cutoff 5 Hz, fs 100 Hz, causal `filter`) on longitudinal accel;
accel here is derived from VehicleSpeed (the model has no separate accel
sensor channel; at 100 Hz the derivative is clean after the filter).

DUAL PEDAL AXIS: the targets are defined on the REAL car's pedal axis. The
model's pedal axis is compressed (see MODEL_BIBLE section 8). Scores are
reported on BOTH axes: 'raw' (class = commanded pedal) and 'mapped' (class =
pedal_map.model_to_real(commanded), the fitted calibration layer). The gap
between them is the pedal-interface penalty, not vehicle response.
================================================================================
"""

import json
import os
import sys

import numpy as np
from scipy.signal import butter, filtfilt

import pedal_map            # the fitted calibration layer (v2, 2026-07-26)
BUTTER_ORDER = 2           # MATLAB app defaults
BUTTER_CUTOFF_HZ = 5.0
ACCEL_OFFSET = 0.3         # m/s^2 - delay detection threshold
PEDAL_GRAD_MIN = 60.0      # %/s   - tip-in detector
PEDAL_MIN = 5.0            # %
EVENT_MIN_GAP_S = 2.0
CLASSES = (10, 20, 30, 40, 50, 60, 100)


def _targets():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, "dq_targets.json")) as f:
        return json.load(f)


TARGETS = _targets()


def _movmean_accel(t, v_kmh):
    """Butterworth-filtered longitudinal accel AND jerk, from speed.

    DEVIATION FROM THE MATLAB APP (deliberate, documented): the app filters a
    real LngAccel sensor channel once and takes a raw gradient for tARM. Our
    accel is DIFFERENTIATED from speed, so tARM would be a second derivative
    of a sampled signal - raw, that returns ~120 m/s3 numerical spikes at a
    pedal step (targets are 3-15). We therefore filter the jerk with the same
    Butterworth, and use zero-phase filtfilt so the delay metric is not biased
    by filter lag. Verified against a cutoff sweep: 5 Hz gives physical tARM
    (~4 m/s3 on a 50% step) and is stable down to 1 Hz."""
    fs = 1.0 / max(np.median(np.diff(t)), 1e-4)
    a = np.gradient(v_kmh / 3.6, t)
    b, a_c = butter(BUTTER_ORDER, BUTTER_CUTOFF_HZ / (fs / 2.0))
    acc = filtfilt(b, a_c, a)
    jerk = filtfilt(b, a_c, np.gradient(acc, t))
    return acc, jerk


def find_tip_ins(t, v_kmh, pedal):
    """Port of the app's extractor: pedal gradient > 60 %/s while pedal > 5 %,
    events at least 2 s apart. Returns [(index, from_stop_bool)]."""
    dt = np.median(np.diff(t))
    grad = np.gradient(pedal, t)
    hit = (grad > PEDAL_GRAD_MIN) & (pedal > PEDAL_MIN)
    events, last_t = [], -1e9
    for i in np.where(hit)[0]:
        if t[i] - last_t >= EVENT_MIN_GAP_S:
            events.append((int(i), bool(v_kmh[i] < 5.0)))
            last_t = t[i]
    return events


def _nearest_class(pedal_pct):
    return min(CLASSES, key=lambda c: abs(c - pedal_pct))


def _arm_class_score(cls, v_kmh, accel):
    """ARM banded scoring for one class over its scoring window."""
    arm = TARGETS["arm"]
    key = str(cls)
    if key not in arm["pedal_curves_ms2"]:
        return None
    speeds = np.array(arm["speeds_kph"], float)
    curve = np.array(arm["pedal_curves_ms2"][key], float)
    i0, i1 = arm["score_window_idx"][key]
    pts_v, pts_target = speeds[i0:i1 + 1], curve[i0:i1 + 1]
    # measured accel at each target speed = accel sample where v is closest
    meas = np.array([accel[np.argmin(np.abs(v_kmh - sv))] for sv in pts_v])
    diff = np.abs(pts_target - meas)
    in1 = diff < arm["offset1"]
    in2 = diff < arm["offset2"]
    above0 = meas >= 0
    nonsat = (~in2) & above0
    score = (0.5 * nonsat + 0.75 * in2 + 0.25 * in1) * above0
    return {"points_v": pts_v.tolist(),
            "target": pts_target.tolist(),
            "measured": [round(float(x), 3) for x in meas],
            "score": round(float(score.sum() / len(pts_target)), 3)}


def analyze_event(t, v_kmh, mov_accel, i_event, i_end, jerk=None):
    """Delay + tARM for one tip-in window."""
    w = slice(i_event, i_end)
    tw = t[w]
    start_a = mov_accel[i_event]
    rising = np.where(mov_accel[w] > start_a + ACCEL_OFFSET)[0]
    delay = float(tw[rising[0]] - t[i_event]) if len(rising) else None
    if i_end - i_event > 5:
        j = jerk[w] if jerk is not None else np.gradient(mov_accel[w], tw)
        tarm = float(np.max(j))
    else:
        tarm = None
    return delay, tarm


def dq_from_mf4(mf4_path):
    """Full Drive Quality report for one MF4. Dual pedal axis (raw + mapped)."""
    from asammdf import MDF
    m = MDF(mf4_path)

    def get(name):
        try:
            s = m.get(name)
            return np.asarray(s.samples, float), np.asarray(s.timestamps, float)
        except Exception:
            return None, None

    # Speed axis: prefer the sensor-floor-emulated channel (what AVL scores).
    # ACCEL axis: always from the RAW speed - the floor clamp puts an
    # artificial 0->1 km/h step at driveaway, and differentiating that gives
    # a ~30 m/s3 phantom tARM spike. True motion is the honest source.
    v, t = get("VehSpd_VCU")
    v_raw, t_raw = get("VehicleSpeed")
    if v is None:
        v, t = v_raw, t_raw
    if v_raw is None:
        v_raw, t_raw = v, t
    pedal, tp = get("AccelPdlPos")
    if pedal is None:
        pedal, tp = get("AcceleratorPedal")
    if v is None or pedal is None:
        return {"error": "needs a speed and a pedal channel"}
    pedal = np.interp(t, tp, pedal)
    mov, jerk = _movmean_accel(t, np.interp(t, t_raw, v_raw))

    events = find_tip_ins(t, v, pedal)
    per_event = []
    for n, (i, from_stop) in enumerate(events):
        i_end = events[n + 1][0] if n + 1 < len(events) else len(t) - 1
        # settle pedal level: median over 0.5-1.5 s after the step
        sel = (t >= t[i] + 0.5) & (t <= t[i] + 1.5)
        ped_level = float(np.median(pedal[sel])) if sel.any() else float(pedal[i])
        delay, tarm = analyze_event(t, v, mov, i, i_end, jerk)
        ev = {"t": round(float(t[i]), 2), "from_stop": from_stop,
              "pedal_pct": round(ped_level, 1),
              "class_raw": _nearest_class(ped_level),
              "class_mapped": _nearest_class(pedal_map.model_to_real(ped_level)),
              "delay_s": round(delay, 3) if delay is not None else None,
              "tarm_ms3": round(tarm, 2) if tarm is not None else None}
        for axis in ("raw", "mapped"):
            cls = ev["class_%s" % axis]
            arm = _arm_class_score(cls, v[i:i_end], mov[i:i_end])
            ev["arm_%s" % axis] = arm
        per_event.append(ev)

    # scores per the app: delay fraction under target; tARM banded; ARM mean
    tg = TARGETS["tarm"]
    report = {"file": os.path.basename(mf4_path), "events": per_event}
    for axis in ("raw", "mapped"):
        delays, tarms, arms = [], [], []
        for ev in per_event:
            cls = ev["class_%s" % axis]
            if cls in tg["pedal_pct"]:
                k = tg["pedal_pct"].index(cls)
                if ev["delay_s"] is not None:
                    delays.append(ev["delay_s"] < tg["response_delay_s"][k])
                if ev["tarm_ms3"] is not None:
                    d = abs(tg["tarm_ms3"][k] - ev["tarm_ms3"])
                    tarms.append(0.5 * (ev["tarm_ms3"] > 0)
                                 + 0.25 * (d < tg["offset2"])
                                 + 0.25 * (d < tg["offset1"]))
            if ev.get("arm_%s" % axis):
                arms.append(ev["arm_%s" % axis]["score"])
        report["scores_%s" % axis] = {
            "delay": round(float(np.mean(delays)), 3) if delays else None,
            "tarm": round(float(np.mean(tarms)), 3) if tarms else None,
            "arm": round(float(np.mean(arms)), 3) if arms else None,
        }
    return report
