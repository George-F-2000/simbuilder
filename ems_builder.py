"""
ems_builder.py
================================================================================
Energy Management System builder: generate the dual-motor torque-split map
(`optimal_torque_ratio_map`, the r_ch grid) with a choice of EMS strategy, so
different energy-management approaches can be compared in the SAME vehicle and
scenario, judged by the resulting MF4.

WHAT THE MAP IS (confirmed by inspecting Motor_PMSM_dual.fmu + its default map)
    optimal_torque_ratio_map holds three arrays:
        w      (1, 151)   secondary-axle motor speed grid   [rad/s], 0..~1571
        T_dem  (1, 198)   combined driver torque demand grid [N*m], 0..~591
        r_ch   (151, 198) split ratio in [0,1]: FRACTION of the combined
                          demand sent to the SECONDARY motor. r=0 -> single
                          motor (all to primary); r=0.5 -> even split.
    The FMU reads this map as a String parameter (a .mat path); the deck
    overrides that path per run, so replacing r_ch changes the EMS. w and
    T_dem axes are preserved exactly - only r_ch is regenerated.

STRATEGIES
    deck_default   leave the deck's map untouched (EMS builder "off")
    even           r = 0.5 everywhere (naive baseline)
    single_motor   r = 0 everywhere (always one axle)
    rule           single motor below a demand threshold, ramp to a target
                   share above it (classic production rule-based VCU)
    fuzzy          smooth fuzzy-logic blend of low/high demand and speed
    loss_optimal   at every (w, T_dem) pick the split minimising combined
                   electrical loss from BOTH motors' efficiency maps
                   (instantaneous ECMS / static-optimal - the physics answer)

The loss-optimal strategy depends on the motor efficiency maps, so changing
the motors (Vehicle/Motor Builder) changes the optimal EMS - they are linked.
================================================================================
"""

import os

import numpy as np
from scipy.io import loadmat, savemat

import motor_gen


STRATEGIES = ["deck_default", "loss_optimal", "rule", "fuzzy", "even", "single_motor"]


def _axes_from_deck_map(map_path):
    """Read the w / T_dem breakpoints from the deck's own map so the
    regenerated map is grid-compatible with the FMU."""
    d = loadmat(map_path)
    return (np.ravel(d["w"]).astype(float), np.ravel(d["T_dem"]).astype(float),
            {k: v for k, v in d.items() if not k.startswith("__")})


def _motor_eff_interpolator(motor):
    """(w, tau) -> efficiency in (0,1], from a motor spec's efficiency map,
    plus the motor's max torque envelope at each speed for feasibility."""
    data = motor_gen.build_motor_data(motor, log=lambda *a: None)
    ws = np.ravel(data["m_map_eff_spd"])
    ts = np.ravel(data["m_map_eff_trq"])
    eff = np.asarray(data["m_eff_map"])           # (n_spd, n_trq)
    env_w = np.ravel(data["m_spd_data"])
    env_t = np.ravel(data["m_max_trq"])

    def eff_at(w, tau):
        i = np.interp(w, ws, np.arange(len(ws)))
        j = np.interp(tau, ts, np.arange(len(ts)))
        i0, j0 = int(np.clip(i, 0, len(ws) - 1)), int(np.clip(j, 0, len(ts) - 1))
        return max(float(eff[i0, j0]), 0.05)

    def tau_max(w):
        return float(np.interp(w, env_w, env_t))

    return eff_at, tau_max


# ----------------------------------------------------------------------------
#  strategies -> r_ch grid
# ----------------------------------------------------------------------------

def _grid_shapes(w, T):
    return len(w), len(T)


def strat_even(w, T, **k):
    return np.full((len(w), len(T)), 0.5)


def strat_single(w, T, **k):
    return np.zeros((len(w), len(T)))


def strat_rule(w, T, threshold_nm=250.0, target_share=0.5, **k):
    """Single motor until demand exceeds threshold, then ramp linearly to
    target_share by the top of the demand range."""
    r = np.zeros((len(w), len(T)))
    span = max(T.max() - threshold_nm, 1e-6)
    for j, td in enumerate(T):
        if td > threshold_nm:
            r[:, j] = target_share * min((td - threshold_nm) / span, 1.0)
    return r


def _mu(x, a, b):
    """Rising membership: 0 below a, 1 above b, linear between."""
    if b <= a:
        return 1.0 if x >= b else 0.0
    return float(np.clip((x - a) / (b - a), 0.0, 1.0))


def strat_fuzzy(w, T, **k):
    """Two-input Sugeno-style fuzzy blend. Demand HIGH and speed MODERATE
    favour sharing; low demand keeps a single motor."""
    Tmax, wmax = T.max(), w.max()
    r = np.zeros((len(w), len(T)))
    for i, ws in enumerate(w):
        spd_mid = _mu(ws, 0.1 * wmax, 0.4 * wmax) * (1 - _mu(ws, 0.7 * wmax, wmax))
        for j, td in enumerate(T):
            dem_hi = _mu(td, 0.3 * Tmax, 0.8 * Tmax)
            # rules: (demand high) -> share 0.5 ; (demand high & mid speed) -> share 0.45
            share = 0.5 * dem_hi
            share = 0.6 * share + 0.4 * (0.45 * dem_hi * spd_mid + share * (1 - spd_mid))
            r[i, j] = np.clip(share, 0.0, 0.5)
    return r


def strat_loss_optimal(w, T, motors=None, n_split=21, **k):
    """At each (w, T_dem) choose the split minimising combined electrical
    loss, using both motors' efficiency maps. Motoring only; both motors on
    the same axle-speed grid (identical drive ratios assumed)."""
    if not motors:
        raise ValueError("loss_optimal needs the motor specs")
    eff_p, taumax_p = _motor_eff_interpolator(motors[0])
    eff_s, taumax_s = _motor_eff_interpolator(motors[1] if len(motors) > 1 else motors[0])
    splits = np.linspace(0.0, 0.5, n_split)
    r = np.zeros((len(w), len(T)))
    for i, ws in enumerate(w):
        tp_max, ts_max = taumax_p(ws), taumax_s(ws)
        for j, td in enumerate(T):
            best_r, best_loss = 0.0, np.inf
            for s in splits:
                tau_s = s * td
                tau_p = (1.0 - s) * td
                if tau_p > tp_max + 1e-6 or tau_s > ts_max + 1e-6:
                    continue   # infeasible: a motor is over its envelope
                loss = tau_p * ws * (1.0 / eff_p(ws, tau_p) - 1.0)
                if tau_s > 0:
                    loss += tau_s * ws * (1.0 / eff_s(ws, tau_s) - 1.0)
                if loss < best_loss:
                    best_loss, best_r = loss, s
            r[i, j] = best_r
    return r


_STRAT_FUNCS = {
    "even": strat_even, "single_motor": strat_single, "rule": strat_rule,
    "fuzzy": strat_fuzzy, "loss_optimal": strat_loss_optimal,
}


def build_ratio_map(strategy, deck_map_path, motors=None, params=None, log=print):
    """Return the full map dict (w, T_dem, r_ch) for the chosen strategy,
    grid-matched to the deck's map. Raises for deck_default (caller should
    just not write anything)."""
    if strategy == "deck_default":
        raise ValueError("deck_default writes nothing")
    w, T, base = _axes_from_deck_map(deck_map_path)
    fn = _STRAT_FUNCS.get(strategy)
    if fn is None:
        raise ValueError("unknown EMS strategy: " + strategy)
    r = fn(w, T, motors=motors, **(params or {}))
    r = np.clip(np.asarray(r, dtype=float), 0.0, 1.0)
    out = dict(base)
    out["r_ch"] = r.reshape(len(w), len(T))
    out["w"] = w.reshape(1, -1)
    out["T_dem"] = T.reshape(1, -1)
    return out


def apply_ems(ems, run_dir, motors, log=print):
    """Generate and write the split map into the run folder, shadowing the
    healed deck default. `ems` is {enabled, strategy, params}. No-op when
    disabled or deck_default. Returns the strategy applied, or None."""
    if not ems or not ems.get("enabled"):
        return None
    strategy = ems.get("strategy", "deck_default")
    if strategy == "deck_default":
        log("  EMS: deck default map (builder off)")
        return None

    map_file = next((f for f in os.listdir(run_dir)
                     if "opt_trq_ratio" in f.lower()), None)
    if not map_file:
        log("  WARNING: no optimal_torque_ratio map in run folder - EMS skipped")
        return None
    try:
        m = build_ratio_map(strategy, os.path.join(run_dir, map_file),
                            motors=motors, params=ems.get("params"), log=log)
    except Exception as exc:
        log("  WARNING: EMS strategy '{}' failed ({}) - using deck default"
            .format(strategy, exc))
        return None
    savemat(os.path.join(run_dir, map_file), m)
    r = m["r_ch"]
    log("  EMS: '{}' split map written (r_ch {:.2f}..{:.2f}, mean {:.2f})"
        .format(strategy, r.min(), r.max(), r.mean()))
    return strategy
