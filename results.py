"""
results.py
================================================================================
The Results tab's engine: scan the runs folder, compute campaign metrics
from each run's MF4 + vehicle.json, and hand the Results tab one row per
run. This is the EMS-comparison leaderboard.

Metrics per run
    duration_s        simulated time
    dist_km           ∫ VehicleSpeed dt
    energy_kwh        ∫ BattPower dt  (net: regen reduces it)
    wh_per_km         the efficiency headline (needs dist > 50 m)
    soc_drop_pct      BattSOC start - end
    v_max_kph
    track_rmse_kph    only for UDDS/HWFET runs: RMSE vs the EPA schedule
                      (t > 5 s, launch transient excluded). Doubles as run
                      validity - a car that can't follow the cycle has a
                      meaningless Wh/km.
    jerk_rms          RMS of d(AccelerationChassis)/dt - ride harshness
    chatter_per_min   EM1+EM2 torque on/off transitions (|T| crossing 2 Nm)
                      per minute - the classic loss-optimal-EMS drivability
                      sin, and the drivability axis of the Pareto plot
    serial / serial_ok  vehicle fingerprint from vehicle.json, checked
                      against the MF4's VehicleSerial channel

Rows are cached in <runs_dir>\\.simbuilder_results_cache.json keyed by the
MF4's mtime, so a refresh only recomputes new or changed runs.
================================================================================
"""

import glob
import json
import os
import re

import numpy as np
from asammdf import MDF

import drive_cycles


CACHE_NAME = ".simbuilder_results_cache.json"
TORQUE_ON_NM = 2.0     # |torque| above this counts as "motor active"


def _get(m, name):
    try:
        return m.get(name)
    except Exception:
        return None


def drivability_metrics(t, a, jerk):
    """Longitudinal drivability numbers from the chassis acceleration trace.

    Standard, well-defined:
      jerk_peak   max |da/dt|                                    [m/s^3]
      accel_rms   RMS of a (ride-comfort proxy; ISO-2631 uses a
                  frequency-weighted a, this is the unweighted form)  [m/s^2]
      vdv         vibration dose value (integral a^4 dt)^0.25      [m/s^1.75]

    Best-effort (definitions NOT standardised in public sources - George to
    confirm against the AVL/lab convention; the formula is shown in-app):
      arm   Acceleration Response Magnitude = 95th-pctile |a|      [m/s^2]
      t_arm Acceleration Response Time = 10->90% rise time of the
            strongest tip-in (largest sustained positive-a event)  [s]
    """
    out = {}
    a = np.asarray(a, float)
    out["jerk_peak"] = round(float(np.max(np.abs(jerk))), 2)
    out["accel_rms"] = round(float(np.sqrt(np.mean(a ** 2))), 3)
    out["vdv"] = round(float(np.trapezoid(a ** 4, t) ** 0.25), 3)
    out["arm"] = round(float(np.percentile(np.abs(a), 95)), 3)

    # t_arm: find the strongest positive-acceleration tip-in and time its
    # 10->90% rise. Robust to noise via a light smoothing window.
    try:
        n = len(a)
        if n > 20:
            w = max(3, n // 200)
            sm = np.convolve(a, np.ones(w) / w, mode="same")
            # split into positive-accel runs, score by (peak x duration)
            pos = sm > 0.2
            best, cur = None, None
            for k in range(n):
                if pos[k]:
                    cur = cur or k
                elif cur is not None:
                    peak = sm[cur:k].max()
                    score = peak * (t[k - 1] - t[cur])
                    if best is None or score > best[0]:
                        best = (score, cur, k)
                    cur = None
            if best:
                _, i0, i1 = best
                seg_t, seg_a = t[i0:i1], sm[i0:i1]
                pk = seg_a.max()
                lo = np.where(seg_a >= 0.1 * pk)[0]
                hi = np.where(seg_a >= 0.9 * pk)[0]
                if len(lo) and len(hi):
                    out["t_arm"] = round(float(seg_t[hi[0]] - seg_t[lo[0]]), 3)
    except Exception:
        pass
    return out


def metrics_from_mf4(mf4_path, run_name):
    m = MDF(mf4_path)
    try:
        out = {}
        v = _get(m, "VehicleSpeed")
        if v is None or len(v.timestamps) < 10:
            return {"error": "no VehicleSpeed channel"}
        t = np.asarray(v.timestamps, dtype=float)
        vk = np.asarray(v.samples, dtype=float)          # km/h
        out["duration_s"] = round(float(t[-1] - t[0]), 1)
        out["dist_km"] = round(float(np.trapezoid(vk / 3.6, t)) / 1000.0, 3)
        out["v_max_kph"] = round(float(vk.max()), 1)

        bp = _get(m, "BattPower")
        if bp is not None:
            e_kwh = float(np.trapezoid(np.asarray(bp.samples, dtype=float),
                                   np.asarray(bp.timestamps, dtype=float))) / 3600.0
            out["energy_kwh"] = round(e_kwh, 4)
            if out["dist_km"] > 0.05:
                out["wh_per_km"] = round(e_kwh * 1000.0 / out["dist_km"], 1)

        soc = _get(m, "BattSOC")
        if soc is not None:
            out["soc_drop_pct"] = round(
                float(soc.samples[0] - soc.samples[-1]), 4)

        az = _get(m, "AccelerationChassis")
        if az is not None and len(az.timestamps) > 10:
            at = np.asarray(az.timestamps, dtype=float)
            a = np.asarray(az.samples, dtype=float)          # m/s^2 longitudinal
            dt = np.diff(at)
            jerk = np.diff(a) / np.maximum(dt, 1e-6)          # m/s^3
            out["jerk_rms"] = round(float(np.sqrt(np.mean(jerk ** 2))), 3)
            out.update(drivability_metrics(at, a, jerk))

        # motor on/off chatter (drivability sin of aggressive EMS maps)
        trans = 0
        for ch in ("EM1Torque", "EM2Torque"):
            sig = _get(m, ch)
            if sig is not None:
                active = np.abs(np.asarray(sig.samples, dtype=float)) > TORQUE_ON_NM
                trans += int(np.count_nonzero(np.diff(active)))
        if out["duration_s"] > 0:
            out["chatter_per_min"] = round(trans / (out["duration_s"] / 60.0), 1)

        ser = _get(m, "VehicleSerial")
        if ser is not None:
            out["mf4_serial"] = int(np.median(ser.samples))

        # drive-cycle tracking (UDDS_* / HWFET_* run names)
        cyc = next((c for c in drive_cycles.CYCLES
                    if run_name.upper().startswith(c)), None)
        if cyc:
            out["cycle"] = cyc
            tc, vc = drive_cycles.cycle_speed_kph(cyc)
            ref = np.interp(t, tc, vc)
            sel = t > 5.0
            if sel.any():
                out["track_rmse_kph"] = round(
                    float(np.sqrt(np.mean((vk[sel] - ref[sel]) ** 2))), 2)
        return out
    finally:
        m.close()


def scan_runs(runs_dir, force=False, log=None):
    """-> list of row dicts, newest first. Cached by MF4 mtime."""
    cache_path = os.path.join(runs_dir, CACHE_NAME)
    cache = {}
    if not force:
        try:
            with open(cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            pass

    rows = []
    if not os.path.isdir(runs_dir):
        return rows
    for folder in sorted(os.listdir(runs_dir), reverse=True):
        fpath = os.path.join(runs_dir, folder)
        if not os.path.isdir(fpath):
            continue
        mf4s = glob.glob(os.path.join(fpath, "*_avldrive.mf4"))
        if not mf4s:
            continue
        mf4 = mf4s[0]
        mtime = os.path.getmtime(mf4)

        cached = cache.get(folder)
        if cached and cached.get("mtime") == mtime:
            rows.append(cached["row"])
            continue

        # run name = folder minus the _YYYYmmdd_HHMMSS suffix
        mo = re.match(r"(.+)_(\d{8}_\d{6})$", folder)
        name = mo.group(1) if mo else folder
        when = ("{}-{}-{} {}:{}".format(mo.group(2)[0:4], mo.group(2)[4:6],
                                        mo.group(2)[6:8], mo.group(2)[9:11],
                                        mo.group(2)[11:13]) if mo else "")
        row = {"folder": folder, "path": fpath, "mf4": mf4,
               "name": name, "when": when}

        vj = os.path.join(fpath, "vehicle.json")
        if os.path.isfile(vj):
            try:
                spec = json.load(open(vj, encoding="utf-8"))
                row["vehicle"] = spec.get("name", "")
                row["serial"] = spec.get("serial", "")
                ems = spec.get("ems") or {}
                row["ems"] = (ems.get("strategy", "deck_default")
                              if ems.get("enabled") else "deck_default")
            except Exception:
                pass
        row.setdefault("ems", "deck_default")

        try:
            row.update(metrics_from_mf4(mf4, name))
        except Exception as exc:
            row["error"] = "{}: {}".format(type(exc).__name__, exc)
        if log:
            log("  results: computed " + folder)

        # serial cross-check: MF4 channel vs vehicle.json
        digits = re.sub(r"\D", "", str(row.get("serial", "")))
        if digits and row.get("mf4_serial") is not None:
            row["serial_ok"] = int(digits) == row["mf4_serial"]

        cache[folder] = {"mtime": mtime, "row": row}
        rows.append(row)

    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass
    return rows
