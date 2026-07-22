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


STRATEGIES = ["deck_default", "traction", "ratio_even", "loss_optimal",
              "rule", "fuzzy", "even", "single_motor"]

# ----------------------------------------------------------------------------
#  GEAR-RATIO AWARENESS  (the 2026-07-18 fix)
#
#  r_ch splits the combined MOTOR-torque demand. This vehicle's axles have
#  very different reductions (front AAM 18:1, rear SRM 9.59:1), so equal
#  motor torque puts 18/9.59 = 1.88x more torque on the FRONT wheels. The
#  deck's own default map does exactly that: measured front 178.3 Nm x 18 =
#  3204 Nm at the wheels vs rear 159.3 x 9.59 = 1527 Nm. Under a hard launch
#  the front axle (already unloaded by rearward weight transfer) breaks
#  traction and spins - observed at +1972% slip while the car crawled.
#
#  Everything below therefore reasons in WHEEL torque and converts back.
# ----------------------------------------------------------------------------

DEFAULT_RATIOS = (18.0, 9.59)      # (primary/front, secondary/rear)


def _gear_ratios(motors):
    """(primary, secondary) drive ratios from the motor specs."""
    if not motors:
        return DEFAULT_RATIOS
    g_p = float(motors[0].get("gearRatio") or DEFAULT_RATIOS[0]) or DEFAULT_RATIOS[0]
    g_s = (float(motors[1].get("gearRatio") or g_p)
           if len(motors) > 1 else g_p) or g_p
    return g_p, g_s


def beta_to_r(beta, g_p, g_s):
    """Convert a desired WHEEL-torque fraction to the secondary axle (beta)
    into the MOTOR-torque fraction r_ch that the FMU consumes.

        T_s = beta*T_wheel/g_s ,  T_p = (1-beta)*T_wheel/g_p
        r   = T_s / (T_p + T_s)

    Sanity: an EVEN WHEEL split (beta=0.5) at 18:1/9.59:1 needs r = 0.652,
    not 0.5 - which is precisely the error that over-drove the front axle."""
    beta = float(np.clip(beta, 0.0, 1.0))
    t_s = beta / max(g_s, 1e-9)
    t_p = (1.0 - beta) / max(g_p, 1e-9)
    tot = t_p + t_s
    return 0.0 if tot <= 0 else float(np.clip(t_s / tot, 0.0, 1.0))


def _load_transfer_beta(T_dem, w_s, g_p, g_s, params):
    """Wheel-torque fraction for the secondary (rear) axle, accounting for
    static axle load AND longitudinal load transfer under acceleration.

    Under acceleration weight moves rearward, so the rear axle can carry a
    larger share of tractive effort while the front loses grip. Sending the
    split the other way (the current deck behaviour) is what spins the front.
    """
    mass = float(params.get("mass_kg", 2746.94))
    wheelbase = float(params.get("wheelbase_m", 3.094))
    h_cg = float(params.get("h_cg_m", 0.55))
    r_tire = float(params.get("r_tire_m", 0.37))
    front_static = float(params.get("front_load_frac", 0.5))

    # wheel torque this demand can produce if split at the static share
    t_wheel = T_dem * ((1.0 - front_static) * g_s + front_static * g_p)
    accel = (t_wheel / max(r_tire, 1e-6)) / max(mass, 1.0)      # m/s^2
    accel = float(np.clip(accel, 0.0, 8.0))
    dyn = mass * accel * h_cg / max(wheelbase, 1e-6)            # N transferred
    rear_load = (1.0 - front_static) * mass * 9.81 + dyn
    total_load = mass * 9.81
    beta = float(np.clip(rear_load / total_load, 0.05, 0.95))
    return beta


def _axes_from_deck_map(map_path):
    """Read the w / T_dem breakpoints from the deck's own map so the
    regenerated map is grid-compatible with the FMU."""
    d = loadmat(map_path)
    return (np.ravel(d["w"]).astype(float), np.ravel(d["T_dem"]).astype(float),
            {k: v for k, v in d.items() if not k.startswith("__")})


def _motor_eff_interpolator(motor):
    """(w, tau) -> efficiency in (0,1], from a motor spec's efficiency map,
    plus the motor's max torque envelope at each speed for feasibility.

    IMPORTANT (fixed 2026-07-18): this must resolve the motor data exactly
    the way fmu_inject does, otherwise the EMS optimises against a different
    motor than the one actually injected into the FMU. With 'map file is
    truth' set, the rear SRM's real envelope is 197.6 Nm - sizing the split
    against the 317.9 Nm field rating would ask for torque it cannot make."""
    try:
        import fmu_inject
        data = fmu_inject._motor_data_for(motor, log=lambda *a: None)
    except Exception:
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


def strat_rear_only(w, T, **k):
    """All combined MOTOR torque to the SECONDARY (rear, 9.59:1) axle.
    Diagnostic mirror of single_motor for road-load / driveline studies."""
    return np.ones((len(w), len(T)))


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


def strat_ratio_even(w, T, motors=None, **k):
    """Even WHEEL-torque split - the ratio-aware replacement for 'even'.
    With 18:1/9.59:1 this is r_ch = 0.652, not 0.5."""
    g_p, g_s = _gear_ratios(motors)
    return np.full((len(w), len(T)), beta_to_r(0.5, g_p, g_s))


def strat_traction(w, T, motors=None, params=None, **k):
    """DEFAULT BASELINE. Distributes WHEEL torque in proportion to the load
    actually on each axle, including rearward load transfer under
    acceleration, then converts to r_ch through the drive ratios - and
    finally clamps to what each motor can physically deliver.

    This is deliberately a simple, physical, disclosable structure - not a
    model of any production strategy. It gives EMS/drivability work a sane
    starting point: no axle is asked for more tractive effort than its share
    of the vehicle's weight can put down, which is what stops the front from
    spinning up under launch.

    Envelope clamp matters on this vehicle: the front axle can make
    235.2 Nm x 18 = 4234 Nm at the wheel but the rear only 197.6 x 9.59 =
    1895 Nm, so at high demand the rear simply cannot take the share that
    traction alone would want. The clamp keeps the map physically
    realisable instead of asking for torque the hardware cannot produce."""
    g_p, g_s = _gear_ratios(motors)
    p = dict(params or {})
    envs = None
    if motors:
        _, taumax_p = _motor_eff_interpolator(motors[0])
        _, taumax_s = _motor_eff_interpolator(
            motors[1] if len(motors) > 1 else motors[0])
        envs = (taumax_p, taumax_s)
    r = np.zeros((len(w), len(T)))
    for i, ws in enumerate(w):
        wp = ws * (g_p / g_s)
        for j, td in enumerate(T):
            beta = _load_transfer_beta(td, ws, g_p, g_s, p)
            rr = beta_to_r(beta, g_p, g_s)
            if envs is not None and td > 1e-6:
                tp_max, ts_max = envs[0](wp), envs[1](ws)
                if td >= tp_max + ts_max:
                    # demand exceeds combined capability: both saturate, so
                    # split in proportion to what each can actually make
                    rr = ts_max / max(tp_max + ts_max, 1e-9)
                else:
                    if rr * td > ts_max:            # secondary over envelope
                        rr = ts_max / td
                    if (1.0 - rr) * td > tp_max:    # primary over envelope
                        rr = 1.0 - tp_max / td
                rr = float(np.clip(rr, 0.0, 1.0))
            r[i, j] = rr
    return r


def strat_loss_optimal(w, T, motors=None, n_split=41, params=None, **k):
    """Minimise electrical cost per unit of WHEEL torque delivered.

    Fixed 2026-07-18 - the previous version had two ratio bugs: it assumed
    identical drive ratios, and it evaluated BOTH motors at the same speed.
    In this vehicle a given road speed puts the front motor at 18/9.59 =
    1.88x the rear motor's speed, and a given motor torque produces very
    different wheel torque per axle. Both are now handled, and the search is
    capped by each axle's traction share so the optimum can never ask an
    axle for more than it can put down."""
    if not motors:
        raise ValueError("loss_optimal needs the motor specs")
    g_p, g_s = _gear_ratios(motors)
    eff_p, taumax_p = _motor_eff_interpolator(motors[0])
    eff_s, taumax_s = _motor_eff_interpolator(
        motors[1] if len(motors) > 1 else motors[0])
    p = dict(params or {})
    betas = np.linspace(0.0, 1.0, n_split)
    r = np.zeros((len(w), len(T)))
    for i, ws in enumerate(w):
        wp = ws * (g_p / g_s)           # primary spins faster for same road speed
        tp_max, ts_max = taumax_p(wp), taumax_s(ws)
        for j, td in enumerate(T):
            # wheel torque available if split at the traction-neutral point
            beta_tr = _load_transfer_beta(td, ws, g_p, g_s, p)
            t_wheel = td * ((1 - beta_tr) * g_p + beta_tr * g_s)
            best_b, best_cost = beta_tr, np.inf
            for b in betas:
                if b > beta_tr + 0.25 or b < beta_tr - 0.25:
                    continue        # stay near the traction-feasible region
                tau_s = b * t_wheel / max(g_s, 1e-9)
                tau_p = (1.0 - b) * t_wheel / max(g_p, 1e-9)
                if tau_p > tp_max + 1e-6 or tau_s > ts_max + 1e-6:
                    continue
                p_in = 0.0
                if tau_p > 0:
                    p_in += tau_p * wp / eff_p(wp, tau_p)
                if tau_s > 0:
                    p_in += tau_s * ws / eff_s(ws, tau_s)
                if t_wheel <= 0:
                    continue
                cost = p_in / t_wheel        # electrical watts per Nm at wheel
                if cost < best_cost:
                    best_cost, best_b = cost, b
            r[i, j] = beta_to_r(best_b, g_p, g_s)
    return r


_STRAT_FUNCS = {
    "even": strat_even, "single_motor": strat_single, "rear_only": strat_rear_only,
    "rule": strat_rule,
    "fuzzy": strat_fuzzy, "loss_optimal": strat_loss_optimal,
    "traction": strat_traction, "ratio_even": strat_ratio_even,
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


def apply_ems_any(ems, deck_text, run_dir, motors, log=print):
    """apply_ems for BOTH deck styles. External opt_trq_ratio .mat in the run
    folder (doublelane): shadow the file. Map inside the motor FMU (LYRIQ):
    extract its axes, rebuild r_ch, and inject it back into the run's FMU
    copy (making + re-pointing the copy if motor injection didn't already).
    Returns (strategy applied or None, possibly-updated deck_text)."""
    if not ems or not ems.get("enabled"):
        return None, deck_text
    strategy = ems.get("strategy", "deck_default")
    if strategy == "deck_default":
        log("  EMS: deck default map (builder off)")
        return None, deck_text

    if any("opt_trq_ratio" in f.lower() for f in os.listdir(run_dir)):
        return apply_ems(ems, run_dir, motors, log=log), deck_text

    import io
    import fmu_inject
    ref, native, names = fmu_inject.find_fmu_resource(deck_text,
                                                      fmu_inject.OPT_RE)
    if ref is None:
        log("  WARNING: no torque-split map found (neither an external "
            "opt_trq_ratio .mat nor one inside a deck FMU) - EMS skipped")
        return None, deck_text
    try:
        src = io.BytesIO(fmu_inject.read_fmu_resource(native, names[0]))
        m = build_ratio_map(strategy, src, motors=motors,
                            params=ems.get("params"), log=log)
    except Exception as exc:
        log("  WARNING: EMS strategy '{}' failed ({}) - using deck default"
            .format(strategy, exc))
        return None, deck_text
    buf = io.BytesIO()
    savemat(buf, m)
    dest = os.path.join(run_dir, os.path.basename(native))
    fmu_inject.replace_fmu_entries(native, dest, {names[0]: buf.getvalue()})
    if os.path.normpath(native) != os.path.normpath(dest):
        deck_text = deck_text.replace(
            ref.group(0),
            ref.group(1) + dest.replace("\\", "/") + ref.group(3), 1)
        log("  EMS: motor FMU copied into the run folder and re-pointed")
    r = m["r_ch"]
    log("  EMS: '{}' split map injected into {} (r_ch {:.2f}..{:.2f}, "
        "mean {:.2f})".format(strategy, os.path.basename(dest),
                              r.min(), r.max(), r.mean()))
    return strategy, deck_text


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
