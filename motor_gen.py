"""
motor_gen.py
================================================================================
Generate the motor FMU parameter .mat files from Vehicle Builder specs, so
the motor fields genuinely drive the simulation.

Schema (reverse-engineered from the model's own files):

  <deck>_motor_char.mat        scalar ratings for BOTH motors (_f / _r):
      m_spd_max_X       [rad/s]  absolute max speed
      m_spd_rated_rpm_X [rpm]    corner (base) speed
      m_spd_rated_X     [rad/s]  corner speed
      m_trq_rated_X     [N*m]    peak torque

  <deck>_frnt_motor_data.mat / _rear_motor_data.mat   per-motor maps:
      m_spd_data        (1,15)   speed grid 0..max [rad/s]
      m_max_trq         (1,15)   torque envelope: min(T_peak, P_peak/w)
      m_map_eff_spd     (1,15)   efficiency-map speed breakpoints [rad/s]
      m_map_eff_trq     (1,14)   efficiency-map torque breakpoints [N*m]
      m_eff_map         (15,14)  efficiency 0..1 (drive quadrant)
      m_map_eff_trq_regen (1,27) torque breakpoints -T..+T
      m_eff_map_regen   (15,27)  efficiency incl. regen quadrant

The optimal-torque-split map (opt_trq_ratio.mat) is VCU calibration and is
deliberately left alone.

Efficiency map upload formats:
  .csv  - cell A1 ignored; first row = torque breakpoints [N*m]; first
          column = speed breakpoints [rpm]; body = efficiency (0..1, or %
          if values exceed 1.5). Any grid size - it is re-interpolated
          onto the model's 15x14 grid.
  .mat  - any file containing m_eff_map + m_map_eff_spd + m_map_eff_trq
          (e.g. a file exported from a dyno post-processing script).
================================================================================
"""

import os

import numpy as np
from scipy.io import loadmat, savemat


N_SPD, N_TRQ = 15, 14


def rpm_to_rads(rpm):
    return float(rpm) * 2.0 * np.pi / 60.0


def torque_envelope(peak_trq, peak_kw, max_rpm):
    """Constant torque to the corner speed, constant power beyond."""
    w = np.linspace(0.0, rpm_to_rads(max_rpm), N_SPD)
    p = float(peak_kw) * 1000.0
    with np.errstate(divide="ignore"):
        t = np.minimum(float(peak_trq), np.where(w > 1e-9, p / np.maximum(w, 1e-9),
                                                 float(peak_trq)))
    return w, t


def default_eff_map(w_grid, t_grid):
    """A plausible PMSM island map: ~0.97 peak at mid speed / mid torque,
    dropping toward zero speed/torque and the extremes. Used when the user
    hasn't uploaded a measured map."""
    wmax = max(float(w_grid[-1]), 1e-9)
    tmax = max(float(t_grid[-1]), 1e-9)
    W, T = np.meshgrid(w_grid / wmax, t_grid / tmax, indexing="ij")
    eff = 0.97 - 0.22 * (W - 0.55) ** 2 - 0.20 * (T - 0.50) ** 2
    eff = np.clip(eff, 0.55, 0.97)
    eff[0, :] = 0.0   # zero speed -> zero efficiency, like the source maps
    return eff


def load_eff_csv(path):
    """Parse the documented CSV grid. Returns (speeds rad/s, torques, map)."""
    rows = [r.split(",") for r in
            open(path, encoding="utf-8-sig").read().strip().splitlines()]
    trqs = np.array([float(x) for x in rows[0][1:]])
    spds_rpm = np.array([float(r[0]) for r in rows[1:]])
    grid = np.array([[float(x) for x in r[1:]] for r in rows[1:]])
    if grid.max() > 1.5:          # given in percent
        grid = grid / 100.0
    return spds_rpm * 2 * np.pi / 60.0, trqs, grid


def load_eff_mat(path):
    d = loadmat(path)
    return (np.ravel(d["m_map_eff_spd"]).astype(float),
            np.ravel(d["m_map_eff_trq"]).astype(float),
            np.asarray(d["m_eff_map"], dtype=float))


def regrid(src_w, src_t, src_map, dst_w, dst_t):
    """Bilinear re-interpolation of an efficiency map onto the model grid."""
    out = np.empty((len(dst_w), len(dst_t)))
    # interpolate along torque for each source speed row, then along speed
    tmp = np.empty((len(src_w), len(dst_t)))
    for i in range(len(src_w)):
        tmp[i] = np.interp(dst_t, src_t, src_map[i])
    for j in range(len(dst_t)):
        out[:, j] = np.interp(dst_w, src_w, tmp[:, j])
    return np.clip(out, 0.0, 1.0)


def build_motor_data(motor, log=print):
    """One motor spec dict -> the dict of arrays for its _motor_data.mat."""
    peak_trq = float(motor.get("torqueNm") or 1.0)
    peak_kw = float(motor.get("powerKW") or 1.0)
    max_rpm = float(motor.get("maxRpm") or 1000.0)

    w, t_env = torque_envelope(peak_trq, peak_kw, max_rpm)
    t_grid = np.linspace(0.0, peak_trq, N_TRQ)

    inline = motor.get("effMapInline")
    eff_path = (motor.get("effMapPath") or "").strip()
    if inline and inline.get("eff"):
        # MotorBuilder map: normalized fractions of this motor's ranges
        try:
            sw = np.asarray(inline["spd_frac"], dtype=float) * w[-1]
            st = np.asarray(inline["trq_frac"], dtype=float) * peak_trq
            eff = regrid(sw, st, np.asarray(inline["eff"], dtype=float),
                         w, t_grid)
            log("    efficiency map: MotorBuilder custom grid "
                "({}x{})".format(len(sw), len(st)))
        except Exception as exc:
            log("    WARNING: bad MotorBuilder map ({}) - using synthetic "
                "map".format(exc))
            eff = default_eff_map(w, t_grid)
    elif eff_path and os.path.isfile(eff_path):
        try:
            if eff_path.lower().endswith(".csv"):
                sw, st, smap = load_eff_csv(eff_path)
            else:
                sw, st, smap = load_eff_mat(eff_path)
            eff = regrid(sw, st, smap, w, t_grid)
            log("    efficiency map: " + os.path.basename(eff_path) +
                " (re-gridded {}x{} -> {}x{})".format(*smap.shape, N_SPD, N_TRQ))
        except Exception as exc:
            log("    WARNING: could not read efficiency map {} ({}) - using "
                "synthetic map".format(eff_path, exc))
            eff = default_eff_map(w, t_grid)
    else:
        if eff_path:
            log("    WARNING: efficiency map not found: {} - using synthetic "
                "map".format(eff_path))
        eff = default_eff_map(w, t_grid)

    # regen side: mirror the drive map onto negative torque (27 breakpoints)
    t_regen = np.linspace(-peak_trq, peak_trq, 2 * N_TRQ - 1)
    eff_regen = np.empty((N_SPD, len(t_regen)))
    for j, tq in enumerate(t_regen):
        eff_regen[:, j] = np.array(
            [np.interp(abs(tq), t_grid, eff[i]) for i in range(N_SPD)])

    return {
        "m_spd_data": w.reshape(1, -1),
        "m_max_trq": t_env.reshape(1, -1),
        "m_map_eff_spd": w.reshape(1, -1),
        "m_map_eff_trq": t_grid.reshape(1, -1),
        "m_eff_map": eff,
        "m_map_eff_trq_regen": t_regen.reshape(1, -1),
        "m_eff_map_regen": eff_regen,
    }


def char_entries(motor, suffix):
    """Scalar rating block for one motor (suffix 'f' or 'r')."""
    peak_trq = float(motor.get("torqueNm") or 1.0)
    peak_kw = float(motor.get("powerKW") or 1.0)
    max_rpm = float(motor.get("maxRpm") or 1000.0)
    # corner (base) speed: where constant power meets constant torque
    w_rated = min(peak_kw * 1000.0 / max(peak_trq, 1e-9), rpm_to_rads(max_rpm))
    return {
        "m_spd_max_" + suffix: np.array([[rpm_to_rads(max_rpm)]]),
        "m_spd_rated_" + suffix: np.array([[w_rated]]),
        "m_spd_rated_rpm_" + suffix: np.array([[w_rated * 60.0 / (2 * np.pi)]]),
        "m_trq_rated_" + suffix: np.array([[peak_trq]]),
    }


def generate_motor_files(spec, run_dir, log=print):
    """Write generated motor .mat files into the run folder, shadowing the
    deck defaults that were healed in earlier. File targets are found by
    name heuristics on the .mat files already in the run folder:
    '*char*' -> ratings file, '*frnt*/*front*' -> motor 1, '*rear*' ->
    motor 2. Returns the list of file names written."""
    motors = (spec or {}).get("motors") or []
    count = int((spec or {}).get("motorCount") or len(motors))
    motors = motors[:count]
    if not motors:
        return []

    mats = [f for f in os.listdir(run_dir) if f.lower().endswith(".mat")]
    char_file = next((f for f in mats if "char" in f.lower()), None)
    front_file = next((f for f in mats if "frnt" in f.lower()
                       or "front" in f.lower()), None)
    rear_file = next((f for f in mats if "rear" in f.lower()), None)

    written = []
    front_m = motors[0]
    rear_m = motors[1] if len(motors) > 1 else motors[0]
    if len(motors) == 1 and rear_file:
        log("  NOTE: deck is dual-motor but spec has 1 motor - using the "
            "same spec for both.")

    if front_file:
        savemat(os.path.join(run_dir, front_file),
                build_motor_data(front_m, log=log))
        written.append(front_file)
        log("  motor 1 -> generated " + front_file)
    if rear_file:
        savemat(os.path.join(run_dir, rear_file),
                build_motor_data(rear_m, log=log))
        written.append(rear_file)
        log("  motor 2 -> generated " + rear_file)
    if char_file:
        entries = {}
        entries.update(char_entries(front_m, "f"))
        entries.update(char_entries(rear_m, "r"))
        savemat(os.path.join(run_dir, char_file), entries)
        written.append(char_file)
        log("  motor ratings -> generated " + char_file)
    return written
