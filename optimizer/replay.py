"""
optimizer/replay.py
================================================================================
The open-loop driver file for a replay: the logged accelerator and brake,
compressed into constant maneuvers, drive the model directly (no speed
controller, no look-ahead). The vehicle starts at the log's speed.

Why constants: a MANEUVER per step with OPENLOOP CONSTANT throttle and brake
is the form the Altair Driver has proven to run for long sequences in this
deck (the Calibration tab's "constants-only, memory-safe" replay). The rules
learned on this deck, kept here:
  * the (CONTROLLERS) table grammar is required (key=value CONTROLLER lines
    end the run silently at maneuver load);
  * the brake must be an OPENLOOP CONSTANT block - an EXPRESSION brake with
    SIGNAL_CHANNEL 0 hijacks the throttle channel;
  * a brake step at zero speed kills the integrator, so windows should not
    reach standstill (logmatch.find_windows keeps a speed floor);
  * low-speed transitions want a fine h_max.
================================================================================
"""
import numpy as np

DEFAULT_STEP_S = 1.0
DEFAULT_SMOOTHING_HZ = 10.0
DEFAULT_HMAX = 0.01
DEFAULT_PRINT_INTERVAL = 0.01
KPH_TO_MMS = 1000.0 / 3.6


def segment_series(t, thr, brk, step_s=DEFAULT_STEP_S):
    """Compress pedal and brake (both fractions 0..1, sampled at times t)
    into constant steps of `step_s` (the last one takes the remainder).
    Returns [(duration_s, throttle, brake)], each value the mean over its
    step, clipped to 0..1."""
    t = np.asarray(t, float)
    thr = np.clip(np.asarray(thr, float), 0.0, 1.0)
    brk = np.clip(np.asarray(brk, float) if brk is not None else np.zeros_like(thr),
                  0.0, 1.0)
    if t.size < 2:
        raise ValueError("need at least two samples to build maneuvers")
    t0, t1 = float(t[0]), float(t[-1])
    edges = list(np.arange(t0, t1, step_s)) + [t1]
    if len(edges) > 2 and (edges[-1] - edges[-2]) < 0.5 * step_s:
        edges.pop(-2)   # fold a tiny tail into the previous step
    segs = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (t >= a) & (t < b) if b < t1 else (t >= a) & (t <= b)
        if not sel.any():
            sel = np.argmin(np.abs(t - 0.5 * (a + b)))
        segs.append((round(float(b - a), 4),
                     float(np.mean(thr[sel])), float(np.mean(brk[sel]))))
    return segs


def _hdr(name):
    return "$" + "-" * (75 - len(name)) + name + "\n"


def _std(ch, mx, mn, init, smoothing_hz=DEFAULT_SMOOTHING_HZ):
    return (_hdr(ch + "_STANDARD") + "[%s_STANDARD]\n" % ch +
            "MAX_VALUE            = %g\nMIN_VALUE            = %g\n" % (mx, mn) +
            "SMOOTHING_FREQUENCY  = %g\nINITIAL_VALUE        = %g\n"
            % (smoothing_hz, init))


def _ctrl(n):
    return ("(CONTROLLERS)\n"
            "{DRIVER_SIGNAL             PRIMARY_CONTROLLER        ADDITIONAL_CONTROLLER    }\n"
            " STEER                     OL_STEER                  NONE                     \n"
            " THROTTLE                  OL_THROTTLE_%d             NONE                     \n" % n +
            " BRAKE                     OL_BRAKE_%d                NONE                     \n" % n +
            " GEAR                      GEAR_CLUTCH_CONTROL       NONE                     \n"
            " CLUTCH                    GEAR_CLUTCH_CONTROL       NONE                     \n")


def _ol_const(n, channel, value):
    return (_hdr("OL_%s_%d" % (channel, n)) + "[OL_%s_%d]\n" % (channel, n) +
            "TAG                    = 'OPENLOOP'\n"
            "TYPE                   = 'CONSTANT'\n"
            "VALUE                  = %.4f\n" % value)


def build_openloop_adf(name, segs, vx0_mms, smoothing_hz=DEFAULT_SMOOTHING_HZ,
                       hmax=DEFAULT_HMAX, print_interval=DEFAULT_PRINT_INTERVAL,
                       title="replay"):
    """The ADF text: one STANDARD maneuver per (duration, throttle, brake)
    step, throttle and brake both OPENLOOP CONSTANT, steer zero, the vehicle
    launched at vx0_mms (mm/s)."""
    if not segs:
        raise ValueError("no maneuvers")
    thr0, brk0 = segs[0][1], segs[0][2]
    s = _hdr("ALTAIR_HEADER") + "[ALTAIR_HEADER]\n"
    s += "FILE_TYPE    = 'ADF'\nFILE_VERSION = 2.0\nFILE_FORMAT  = 'ASCII'\n"
    s += "$ Scenario: %s - %s (%d constant maneuvers, step %.3g s)\n" % (
        name, title, len(segs), segs[0][0])
    s += _hdr("UNITS") + "[UNITS]\n(BASE)\n"
    s += "{ length  force         angle           mass     time }\n"
    s += "  'mm'   'newton'      'radians'        'kg'    'sec'\n"
    s += _hdr("VEHICLE_IC") + "[VEHICLE_INITIAL_CONDITIONS]\n"
    s += "VX0               = %g\nVY0               = 0.0\nVZ0               = 0.0\n" % vx0_mms
    s += "ENGINE_INIT_SPEED = 300\n"
    s += _std("STEER", 9.4248, -9.4248, 0, smoothing_hz)
    s += _hdr("THROTTLE_STANDARD") + "[THROTTLE_STANDARD]\n"
    s += "MAX_VALUE            = 1\nMIN_VALUE            = 0\n"
    s += "SMOOTHING_FREQUENCY  = %g\nINITIAL_VALUE        = %.4f\n" % (smoothing_hz, thr0)
    s += _hdr("BRAKE_STANDARD") + "[BRAKE_STANDARD]\n"
    s += "MAX_VALUE            = 1\nMIN_VALUE            = 0\n"
    s += "SMOOTHING_FREQUENCY  = %g\nINITIAL_VALUE        = %.4f\n" % (smoothing_hz, brk0)
    s += _std("GEAR", 6, 1, 1, smoothing_hz) + _std("CLUTCH", 1, 0, 0, smoothing_hz)
    s += _hdr("MANEUVERS_LIST") + "[MANEUVERS_LIST]\n"
    s += "{name            simulation_time      h_max           print_interval }\n"
    for i, (dur, _thr, _brk) in enumerate(segs, 1):
        s += "'MANEUVER_%d'     %-20g %-15g %-15g\n" % (i, dur, hmax, print_interval)
    for i, (dur, thr, brk) in enumerate(segs, 1):
        s += _hdr("MANEUVER_%d" % i) + "[MANEUVER_%d]\nTASK = 'STANDARD'\n" % i + _ctrl(i)
        s += _ol_const(i, "THROTTLE", thr) + _ol_const(i, "BRAKE", brk)
    s += _hdr("OL_STEER") + "[OL_STEER]\n"
    s += "TAG                    = 'OPENLOOP'\nTYPE                   = 'CONSTANT'\nVALUE                  = 0\n"
    s += _hdr("%GEAR_CLUTCH_CONTROL") + "$Used in case of models with IC Engine \n"
    s += "[GEAR_CLUTCH_CONTROL] \nTAG = 'ENGINE_SPEED'  \n(GEAR_SHIFT_MAP)      \n"
    s += "{G   US      DS      CT      CRT     TFD     TFT     CFT     TRD     TRT}    \n"
    for gg in range(1, 6):
        s += " %d   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05   \n" % gg
    return s


def sim_time(segs):
    return float(sum(d for d, _t, _b in segs))


def replay_adf(name, ref, step_s=DEFAULT_STEP_S, pedal_mode="physical",
               smoothing_hz=DEFAULT_SMOOTHING_HZ, hmax=DEFAULT_HMAX,
               print_interval=DEFAULT_PRINT_INTERVAL):
    """ADF for one reference window (a logmatch.reference() dict: t [s from
    window start], pedal [%], brake [%], v0_kph).

    pedal_mode "physical": the logged pedal drives the deck's throttle input
    as is - correct when the car's pedal law sits in the deck (a deck hook).
    pedal_mode "mapped": the pedal is first sent through pedal_map.real_to_model
    (the Python-side fit the Calibration tab uses), for a deck whose FMU
    applies its own demand law to the throttle it receives.
    Returns (adf_text, segs)."""
    pedal = np.asarray(ref["pedal"], float)
    if pedal_mode == "mapped":
        import pedal_map
        pedal = np.array([pedal_map.real_to_model(float(p)) for p in pedal])
    elif pedal_mode != "physical":
        raise ValueError("pedal_mode must be 'physical' or 'mapped'")
    brake = ref.get("brake")
    segs = segment_series(ref["t"], pedal / 100.0,
                          (np.asarray(brake, float) / 100.0) if brake is not None else None,
                          step_s=step_s)
    adf = build_openloop_adf(name, segs, float(ref["v0_kph"]) * KPH_TO_MMS,
                             smoothing_hz=smoothing_hz, hmax=hmax,
                             print_interval=print_interval,
                             title="log replay (%s pedal)" % pedal_mode)
    return adf, segs
