"""
fmu_inject.py
================================================================================
Inject per-run motor data into an FMU that carries its motor maps INTERNALLY.

Some decks (e.g. the LYRIQ deck) reference no external motor .mat files at all -
the motor efficiency maps, torque envelopes and ratings live inside
Motor_PMSM_dual.fmu at:

    resources/<prefix>_frnt_motor_data.mat   (m_spd_data/m_max_trq/m_eff_map...)
    resources/<prefix>_rear_motor_data.mat
    resources/<prefix>_motor_char.mat        (m_*_rated_f / _r scalars)

For those decks motor_gen has nothing to shadow, so the Vehicle Builder's motor
fields / uploaded maps would never reach the sim. This module makes them reach
it: it copies the motor FMU into the run folder, rewrites those internal .mat
resources from the spec, and re-points the deck's FMU reference at the copy.
The shared FMU in the Altair install is never touched.

The FMU stores its own breakpoint axes inside each .mat, so we regrid onto the
FMU's fixed 15x14 shape (motor_gen.N_SPD x N_TRQ) and let the FMU interpolate.
================================================================================
"""

import io
import os
import re
import zipfile

import numpy as np
from scipy.io import loadmat, savemat

import motor_gen

# resources/<prefix>_frnt_motor_data.mat  /  _rear_motor_data.mat  /  _motor_char.mat
DATA_RE = re.compile(r".*_motor_data\.mat$", re.I)
CHAR_RE = re.compile(r".*_motor_char\.mat$", re.I)
OPT_RE = re.compile(r".*_opt_trq_ratio\.mat$", re.I)
FMU_REF_RE = re.compile(r'(string\s*=\s*")([^"]*\.fmu)(")', re.I)


def find_fmu_resource(deck_text, resource_re):
    """First deck-referenced FMU whose zip contains a resource matching
    resource_re: returns (ref match, native fmu path, [resource names]);
    (None, None, []) when no FMU carries it."""
    for m in FMU_REF_RE.finditer(deck_text):
        native = m.group(2).replace("/", os.sep)
        if not os.path.isfile(native):
            continue
        try:
            with zipfile.ZipFile(native) as z:
                names = [n for n in z.namelist() if resource_re.match(n)]
        except (zipfile.BadZipFile, OSError):
            continue
        if names:
            return m, native, names
    return None, None, []


def read_fmu_resource(fmu_path, name):
    with zipfile.ZipFile(fmu_path) as z:
        return z.read(name)


def replace_fmu_entries(src, dest, replacements):
    """Copy the FMU zip src -> dest replacing the named entries, preserving
    every other entry byte-for-byte. src may equal dest (in-place rewrite of
    the run copy: the whole zip is read into memory first)."""
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        blobs = {i.filename: zin.read(i.filename) for i in infos}
    blobs.update(replacements)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:
            zout.writestr(i, blobs[i.filename])

_FULL_KEYS = ("m_spd_data", "m_max_trq", "m_map_eff_spd", "m_map_eff_trq",
              "m_eff_map")


def _resample_full(src, n_spd=motor_gen.N_SPD, n_trq=motor_gen.N_TRQ,
                   motor=None, log=None):
    """Regrid a complete uploaded motor_data dict onto the FMU's n_spd x n_trq
    axes. Envelope precedence: if the motor's field ratings (peak power /
    torque / max rpm) are set, THEY define the envelope and the file supplies
    the efficiency surfaces only - consistent with the external-.mat deck
    path, where the fields always build the envelope. Without usable fields
    the file's own envelope is used verbatim."""
    spd = np.ravel(src["m_spd_data"]).astype(float)
    trq_env = np.ravel(src["m_max_trq"]).astype(float)
    eff_spd = np.ravel(src["m_map_eff_spd"]).astype(float)
    eff_trq = np.ravel(src["m_map_eff_trq"]).astype(float)
    eff = np.asarray(src["m_eff_map"], dtype=float)

    p_w = float((motor or {}).get("powerKW") or 0) * 1000.0
    t_pk = float((motor or {}).get("torqueNm") or 0)
    rpm = float((motor or {}).get("maxRpm") or 0)
    env_from_file = bool((motor or {}).get("envFromFile"))
    if env_from_file and log:
        log("    motor '{}': map file is TRUTH - using the file's measured "
            "envelope ({:.1f} Nm / {:.0f} rpm), ratings display-only".format(
                (motor or {}).get("name", "?"), trq_env.max(),
                spd.max() * 60.0 / (2 * np.pi)))
    if not env_from_file and p_w > 0 and t_pk > 0 and rpm > 0:
        w_max = rpm * 2.0 * np.pi / 60.0
        w = np.linspace(0.0, w_max, n_spd)
        t_env = np.minimum(t_pk, np.divide(
            p_w, np.maximum(w, 1e-9)))
        t_env[0] = t_pk
        t_grid = np.linspace(0.0, t_pk, n_trq)
        if log and (w_max > spd.max() * 1.02 or t_pk > eff_trq.max() * 1.02):
            log("    NOTE: field ratings exceed the file's data range "
                "(file: {:.0f} rpm / {:.1f} Nm) - efficiency edge-"
                "extrapolated beyond it".format(
                    spd.max() * 60.0 / (2 * np.pi), eff_trq.max()))
    else:
        w = np.linspace(0.0, float(spd.max()), n_spd)
        t_env = np.interp(w, spd, trq_env)
        t_grid = np.linspace(0.0, float(eff_trq.max()), n_trq)
    new_eff = motor_gen.regrid(eff_spd, eff_trq, eff, w, t_grid)

    t_regen = np.linspace(-float(t_grid.max()), float(t_grid.max()),
                          2 * n_trq - 1)
    if "m_eff_map_regen" in src and "m_map_eff_trq_regen" in src:
        rtrq = np.ravel(src["m_map_eff_trq_regen"]).astype(float)
        rmap = np.asarray(src["m_eff_map_regen"], dtype=float)
        eff_regen = motor_gen.regrid(eff_spd, rtrq, rmap, w, t_regen)
    else:
        eff_regen = np.empty((n_spd, len(t_regen)))
        for j, tq in enumerate(t_regen):
            eff_regen[:, j] = [np.interp(abs(tq), t_grid, new_eff[i])
                               for i in range(n_spd)]
    return {
        "m_spd_data": w.reshape(1, -1),
        "m_max_trq": t_env.reshape(1, -1),
        "m_map_eff_spd": w.reshape(1, -1),
        "m_map_eff_trq": t_grid.reshape(1, -1),
        "m_eff_map": new_eff,
        "m_map_eff_trq_regen": t_regen.reshape(1, -1),
        "m_eff_map_regen": eff_regen,
    }


def _motor_data_for(motor, log):
    """Full motor_data dict for one motor. If its uploaded file is a complete
    motor_data .mat, use it verbatim (regridded); otherwise synthesise from the
    spec fields (envelope from peak power/torque/rpm, efficiency from the map)."""
    p = (motor.get("effMapPath") or "").strip()
    if p and p.lower().endswith(".mat") and os.path.isfile(p):
        try:
            d = loadmat(p)
            if all(k in d for k in _FULL_KEYS):
                log("    motor '{}': uploaded motor data {} regridded to "
                    "{}x{} ({})".format(
                        motor.get("name", "?"), os.path.basename(p),
                        motor_gen.N_SPD, motor_gen.N_TRQ,
                        "file envelope - map is truth"
                        if motor.get("envFromFile")
                        else "envelope from the field ratings"))
                return _resample_full(d, motor=motor, log=log)
        except Exception as exc:
            log("    WARNING: could not read {} ({}) - synthesising from fields"
                .format(os.path.basename(p), exc))
    return motor_gen.build_motor_data(motor, log=log)


def _char_from_data(data, suffix):
    """motor_char scalars consistent with a built motor_data dict."""
    w = np.ravel(data["m_spd_data"]).astype(float)
    t = np.ravel(data["m_max_trq"]).astype(float)
    t_max, w_max = float(t.max()), float(w.max())
    near = np.where(t >= 0.99 * t_max)[0]        # corner (base) speed
    w_rated = float(w[near[-1]]) if len(near) else w_max
    return {
        "m_spd_max_" + suffix: np.array([[w_max]]),
        "m_spd_rated_" + suffix: np.array([[w_rated]]),
        "m_spd_rated_rpm_" + suffix: np.array([[w_rated * 60.0 / (2 * np.pi)]]),
        "m_trq_rated_" + suffix: np.array([[t_max]]),
    }


def _mat_bytes(d):
    buf = io.BytesIO()
    savemat(buf, d)
    return buf.getvalue()


def _rewrite_fmu(src, dest, front_data, rear_data, front_m, rear_m, log):
    """Copy the FMU zip from src to dest, replacing its internal motor_data /
    motor_char resources. All other entries are preserved byte-for-byte."""
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        blobs = {i.filename: zin.read(i.filename) for i in infos}

    for name in list(blobs):
        low = name.lower()
        if DATA_RE.match(name):
            if "frnt" in low or "front" in low:
                blobs[name] = _mat_bytes(front_data)
                log("    FMU resource <- front motor data ({})".format(
                    os.path.basename(name)))
            elif "rear" in low:
                blobs[name] = _mat_bytes(rear_data)
                log("    FMU resource <- rear motor data ({})".format(
                    os.path.basename(name)))
        elif CHAR_RE.match(name):
            entries = {}
            entries.update(_char_from_data(front_data, "f"))
            entries.update(_char_from_data(rear_data, "r"))
            blobs[name] = _mat_bytes(entries)
            log("    FMU resource <- motor ratings ({})".format(
                os.path.basename(name)))

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:                     # keep original ZipInfo (name/attrs)
            zout.writestr(i, blobs[i.filename])


def inject_motor_fmu(deck_text, run_dir, spec, log):
    """If the deck references an FMU that carries motor data internally, rebuild
    it in run_dir from the vehicle spec and re-point the deck at the copy.
    Returns (deck_text, injected?)."""
    motors = (spec.get("motors") or [])[:int(spec.get("motorCount") or 1)]
    if not motors:
        return deck_text, False
    front_m = motors[0]
    rear_m = motors[1] if len(motors) > 1 else motors[0]

    for m in FMU_REF_RE.finditer(deck_text):
        native = m.group(2).replace("/", os.sep)
        if not os.path.isfile(native):
            continue
        try:
            with zipfile.ZipFile(native) as z:
                has_data = any(DATA_RE.match(n) for n in z.namelist())
        except (zipfile.BadZipFile, OSError):
            continue
        if not has_data:
            continue   # not the motor FMU (e.g. EPAS / ESP)

        front_data = _motor_data_for(front_m, log)
        rear_data = _motor_data_for(rear_m, log)
        dest = os.path.join(run_dir, os.path.basename(native))
        _rewrite_fmu(native, dest, front_data, rear_data, front_m, rear_m, log)
        new_ref = m.group(1) + dest.replace("\\", "/") + m.group(3)
        deck_text = deck_text.replace(m.group(0), new_ref, 1)
        log("  vehicle: motor FMU rebuilt in run folder and re-pointed ({})"
            .format(os.path.basename(dest)))
        return deck_text, True

    return deck_text, False
