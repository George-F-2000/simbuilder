"""
drive_import.py
================================================================================
"Upload a real drive": turn an MF4 logged in the actual vehicle (the LYRIQ)
into a runnable scenario - speed following, and optionally the real PATH so
the simulated driver also steers where you steered.

Two output flavors
    speed-only   the drive's speed-vs-time trace as a [DEMAND_CURVE] ADF
                 (same mechanism as UDDS/HWFET; straight-line, no steering)
    path + speed the drive's trajectory as a DDF companion file
                 ([DEMAND_VECTORS] {X Y Z DV} - path points in meters with
                 the demanded speed at each point), with
                 [FEEDFORWARD_STEERING] PATH='DDF' steering along it and
                 traction following DV. Grammar taken verbatim from
                 Altair's own Snet_path.adf/.ddf example.

Path reconstruction options (real logs rarely have XY directly):
    yaw    dead-reckoning: heading = ∫ yaw-rate dt, then
           x += v cosψ dt, y += v sinψ dt. Drifts slowly with gyro bias -
           fine for maneuvers of minutes, not for a 2-hour commute.
    gps    latitude/longitude channels -> local equirectangular meters.
    steer  bicycle model: yaw rate = v·tan(road-wheel angle)/wheelbase,
           road-wheel angle = steering wheel angle / steer ratio
           (ratio + wheelbase from the Vehicle Builder spec).

The DDF is resampled to ~2 m point spacing (the driver's look-ahead
interpolates between points; centimeter spacing just bloats the file).
================================================================================
"""

import numpy as np
from asammdf import MDF


SPEED_UNITS = {"km/h": 1 / 3.6, "mph": 0.44704, "m/s": 1.0, "mm/s": 0.001}
ANGLE_RATE_UNITS = {"rad/s": 1.0, "deg/s": np.pi / 180.0}
ANGLE_UNITS = {"rad": 1.0, "deg": np.pi / 180.0}


def list_channels(mf4_path):
    """[{name, unit, samples}] for the channel-picker UI."""
    m = MDF(mf4_path)
    try:
        masters = getattr(m, "masters_db", {})
        out = []
        for name in sorted(m.channels_db, key=str.lower):
            for g, i in m.channels_db[name]:
                if masters.get(g) == i:
                    continue
                ch = m.groups[g].channels[i]
                out.append({"name": name,
                            "unit": getattr(ch, "unit", "") or "",
                            "samples": int(m.groups[g].channel_group.cycles_nr)})
                break
        return out
    finally:
        m.close()


def _sig(m, name):
    s = m.get(name)
    return (np.asarray(s.timestamps, dtype=float),
            np.asarray(s.samples, dtype=float))


def extract_drive(mf4_path, cfg):
    """cfg: {speed_ch, speed_unit, lateral: none|yaw|gps|steer,
             yaw_ch, yaw_unit, lat_ch, lon_ch, steer_ch, steer_unit,
             steer_ratio, wheelbase_mm, t_start, t_end}
    -> {t, v_ms, x, y (meters, None for speed-only), stats}"""
    m = MDF(mf4_path)
    try:
        t, v_raw = _sig(m, cfg["speed_ch"])
        v_ms = np.abs(v_raw) * SPEED_UNITS[cfg.get("speed_unit", "km/h")]

        # optional time window
        t0 = float(cfg.get("t_start") or t[0])
        t1 = float(cfg.get("t_end") or t[-1])
        keep = (t >= t0) & (t <= t1)
        if keep.sum() < 10:
            raise ValueError("time window keeps fewer than 10 samples")
        t, v_ms = t[keep] - t[keep][0], v_ms[keep]

        lateral = cfg.get("lateral", "none")
        x = y = None
        if lateral in ("yaw", "steer"):
            if lateral == "yaw":
                ty, r = _sig(m, cfg["yaw_ch"])
                r = r * ANGLE_RATE_UNITS[cfg.get("yaw_unit", "deg/s")]
            else:
                ty, sw = _sig(m, cfg["steer_ch"])
                sw = sw * ANGLE_UNITS[cfg.get("steer_unit", "deg")]
                ratio = float(cfg.get("steer_ratio") or 15.8)
                wb_m = float(cfg.get("wheelbase_mm") or 3094) / 1000.0
                v_on_ty = np.interp(ty, t + t0, np.append(v_ms, v_ms[-1])[:len(t)]) \
                    if len(ty) != len(t) else v_ms
                r = v_on_ty * np.tan(sw / ratio) / wb_m
            keep_y = (ty >= t0) & (ty <= t1)
            ty, r = ty[keep_y] - t0, r[keep_y]
            r_t = np.interp(t, ty, r)
            psi = np.concatenate([[0.0], np.cumsum(
                0.5 * (r_t[1:] + r_t[:-1]) * np.diff(t))])
            x = np.concatenate([[0.0], np.cumsum(
                0.5 * (v_ms[1:] * np.cos(psi[1:]) + v_ms[:-1] * np.cos(psi[:-1]))
                * np.diff(t))])
            y = np.concatenate([[0.0], np.cumsum(
                0.5 * (v_ms[1:] * np.sin(psi[1:]) + v_ms[:-1] * np.sin(psi[:-1]))
                * np.diff(t))])
        elif lateral == "gps":
            tla, lat = _sig(m, cfg["lat_ch"])
            tlo, lon = _sig(m, cfg["lon_ch"])
            lat_t = np.interp(t + t0, tla, lat)
            lon_t = np.interp(t + t0, tlo, lon)
            R = 6371000.0
            lat0 = np.radians(lat_t[0])
            x = R * np.radians(lon_t - lon_t[0]) * np.cos(lat0)
            y = R * np.radians(lat_t - lat_t[0])

        dist_m = float(np.trapezoid(v_ms, t))
        stats = {"duration_s": round(float(t[-1]), 1),
                 "dist_km": round(dist_m / 1000.0, 3),
                 "v_max_kph": round(float(v_ms.max() * 3.6), 1),
                 "v_start_kph": round(float(v_ms[0] * 3.6), 1),
                 "lateral": lateral,
                 "n_samples": int(len(t))}
        if x is not None:
            path_len = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
            stats["path_len_km"] = round(path_len / 1000.0, 3)
            # dead-reckoning sanity: path length should ~match ∫v dt
            if dist_m > 50:
                stats["path_vs_odo_pct"] = round(100.0 * path_len / dist_m, 1)
        return {"t": t, "v_ms": v_ms, "x": x, "y": y, "stats": stats}
    finally:
        m.close()


def _resample_path(t, v_ms, x, y, spacing_m=2.0):
    """Pick path points every ~spacing_m meters (always keeping endpoints)."""
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    if s[-1] < spacing_m * 3:
        idx = np.arange(len(s))
    else:
        targets = np.arange(0.0, s[-1], spacing_m)
        idx = np.unique(np.searchsorted(s, targets))
        idx = np.append(idx, len(s) - 1)
    return idx


def build_ddf(name, t, v_ms, x, y, spacing_m=2.0):
    """DDF in the DECK's units (mm, mm/s). Empirically the driver's path
    math runs in deck units regardless of the DDF's own units header
    (a meters DDF produced 'path error > 1 mm' spam and a forced stop);
    all-mm is correct under either interpretation."""
    idx = _resample_path(t, v_ms, x, y, spacing_m)
    rows = "\n".join("{:<13.1f} {:<13.1f} {:<4} {:.1f}".format(
        x[i] * 1000.0, y[i] * 1000.0, 0, max(v_ms[i], 0.1) * 1000.0)
        for i in idx)
    return """$-----------------------------------------------------------------ALTAIR_HEADER
[ALTAIR_HEADER]
FILE_TYPE 		= 'DDF'
FILE_VERSION 	= 1.0
FILE_FORMAT 	= 'ASCII'
$ Real drive imported by SimBuilder: {name}
$--------------------------------------------------------------------------UNITS
[UNITS]
(BASE)
{{length  force      angle       mass    time}}
'mm'   'newton'   'radians'   'kg'    'sec'
$-------------------------------------------------------------------DEMAND_VECTORS
[DEMAND_VECTORS]
{{X	    Y	    Z	DV}}
{rows}
""".format(name=name, rows=rows)


def build_path_adf(name, ddf_filename, t, v_ms, hmax=0.01, print_interval=0.01):
    """ADF with FEEDFORWARD steering along the DDF path + traction following
    the DDF's DV column. Deck units (mm); the DDF carries its own units."""
    return """$-----------------------------------------------------------------------ALTAIR_HEADER
[ALTAIR_HEADER]
FILE_TYPE    = 'ADF'
FILE_VERSION = 2.0
FILE_FORMAT  = 'ASCII'
$ Scenario: {name} — real drive (path + speed via {ddf}) — SimBuilder import
$-------------------------------------------------------------------------------UNITS
[UNITS]
(BASE)
{{ length  force         angle           mass     time }}
  'mm'   'newton'      'radians'        'kg'    'sec'
$--------------------------------------------------------------------------VEHICLE_IC
[VEHICLE_INITIAL_CONDITIONS]
VX0               = {vx0:.2f}
VY0               = 0.0
VZ0               = 0.0
ENGINE_INIT_SPEED = 300
$----------------------------------------------------------------------STEER_STANDARD
[STEER_STANDARD]
MAX_VALUE            = 9.4248
MIN_VALUE            = -9.4248
SMOOTHING_FREQUENCY  = 10
INITIAL_VALUE        = 0
$-------------------------------------------------------------------THROTTLE_STANDARD
[THROTTLE_STANDARD]
MAX_VALUE            = 1
MIN_VALUE            = 0
SMOOTHING_FREQUENCY  = 10
INITIAL_VALUE        = 0
$----------------------------------------------------------------------BRAKE_STANDARD
[BRAKE_STANDARD]
MAX_VALUE            = 1
MIN_VALUE            = 0
SMOOTHING_FREQUENCY  = 10
INITIAL_VALUE        = 0
$-----------------------------------------------------------------------GEAR_STANDARD
[GEAR_STANDARD]
MAX_VALUE            = 6
MIN_VALUE            = 1
SMOOTHING_FREQUENCY  = 10
INITIAL_VALUE        = 1
$---------------------------------------------------------------------CLUTCH_STANDARD
[CLUTCH_STANDARD]
MAX_VALUE            = 1
MIN_VALUE            = 0
SMOOTHING_FREQUENCY  = 10
INITIAL_VALUE        = 0
$----------------------------------------------------------------------MANEUVERS_LIST
[MANEUVERS_LIST]
{{name            simulation_time      h_max           print_interval }}
'MANEUVER_1'     {sim:.0f}                  {hmax:g}           {pint:g}
$--------------------------------------------------------------------------MANEUVER_1
[MANEUVER_1]
TASK = 'STANDARD'
(CONTROLLERS)
{{DRIVER_SIGNAL             PRIMARY_CONTROLLER        ADDITIONAL_CONTROLLER    }}
 STEER                     FEEDFORWARD_STEERING      NONE
 THROTTLE                  FEEDFORWARD_TRACTION      NONE
 BRAKE                     FEEDFORWARD_TRACTION      NONE
 GEAR                      GEAR_CLUTCH_CONTROL       NONE
 CLUTCH                    GEAR_CLUTCH_CONTROL       NONE
$-------------------------------------------------------------------FOLLOW_PATH
[FEEDFORWARD_STEERING]
TAG = 'FEEDFORWARD'
LOOK_AHEAD_TIME = 0.5
PATH = 'DDF'
FILE = '{ddf}'
INTEGRATION_STEP_SIZE = 0.01
AGGRESSIVE = 'TRUE'
$-----------------------------------------------------------FEEDFORWARD_TRACTION
[FEEDFORWARD_TRACTION]
TAG                    = 'FEEDFORWARD'
TYPE                   = 'FOLLOW_VELOCITY'
LOOK_AHEAD_TIME        = 0.25
DEMAND_SIGNAL          = 'DEMAND_SPEED'
$-----------------------------------------------------------DEMAND_SPEED
[DEMAND_SPEED]
TYPE = 'CURVE'
FILE = '{ddf}'
DEMAND_VECTOR = 'DV'
$----------------------------------------------------------------%GEAR_CLUTCH_CONTROL
$Used in case of models with IC Engine
[GEAR_CLUTCH_CONTROL]
TAG = 'ENGINE_SPEED'
(GEAR_SHIFT_MAP)
{{G   US      DS      CT      CRT     TFD     TFT     CFT     TRD     TRT}}
 1   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05
 2   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05
 3   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05
 4   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05
 5   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05
""".format(name=name, ddf=ddf_filename, vx0=v_ms[0] * 1000.0,
           sim=t[-1], hmax=hmax, pint=print_interval)


def build_speed_adf(name, t, v_ms, hmax=0.01, print_interval=0.01):
    """Speed-only import: the measured trace through the shared
    speed-following ADF builder (1 Hz resample keeps the table sane)."""
    import drive_cycles
    grid = np.arange(0.0, float(t[-1]), 1.0)
    v_g = np.interp(grid, t, v_ms)
    return drive_cycles.build_adf_from_series(
        name, "real drive (speed only)", list(grid),
        [float(v) * 1000.0 for v in v_g],
        hmax=hmax, print_interval=print_interval)
