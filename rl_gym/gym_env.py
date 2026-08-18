"""
gym_env.py — the RL "practice track" for the demo EV torque-split EMS.
================================================================================
PLAIN LANGUAGE
    Reinforcement learning needs millions of practice attempts. MotionSolve
    costs ~13 min per 61 s of sim, so the agent practices HERE instead: a
    longitudinal-only simulator holding exactly the physics that decide energy
    use — vehicle mass + road load, the two real motor efficiency maps pulled
    from Motor_PMSM_dual.fmu, and the stock battery model. It runs thousands
    of sim-seconds per wall-second. The agent's ONLY job each 0.1 s step is
    the split r in [0,1]: what fraction of the combined motor torque demand
    goes to the REAR (secondary) motor. A simple "driver" (feedback loop)
    follows the drive cycle; the agent never steers or brakes.

DATA PROVENANCE (nothing invented)
    - Motor eff/torque maps + battery params: extracted from the stock FMU
      (Simulink EMS/stock_fmu_data, see MODEL_BIBLE Ch.27.2).
    - Mass: from the deck body sum, loaded via local config.
    - Gear ratios and wheel radius: deck / .tir, via local config.
    - Demand axis sanity: r_ch T_dem max 591 Nm == 210 (front peak) + 380
      (rear peak) — combined MOTOR-side demand, confirmed.
    - Road load coefficients are textbook estimates (Crr 0.009, CdA 0.73) —
      the gym is used for RELATIVE strategy comparison; absolute validation
      happens in MotionSolve afterwards.
================================================================================
"""

import os

import numpy as np
from scipy.io import loadmat

HERE = os.path.dirname(os.path.abspath(__file__))
STOCK = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                     "Simulink EMS", "stock_fmu_data")

# ---- vehicle constants (provenance in header) -------------------------------
# Demo-vehicle defaults; a private, gitignored vehicle_local.json two levels
# up (next to the app) overrides them with the real program values.
import json as _json
_cfg = {}
for _cand in (os.path.join(os.path.dirname(HERE), "vehicle_local.json"),):
    try:
        _cfg = _json.load(open(_cand))
    except Exception:
        pass
MASS = float(_cfg.get("mass_kg", 2100.0))
R_WHEEL = float(_cfg.get("wheel_radius_m", 0.35))
G_F = float(_cfg.get("gear_front", 11.0))
G_R = float(_cfg.get("gear_rear", 11.0))
CRR, CDA, RHO, GRAV = 0.009, 0.73, 1.225, 9.81
ETA_DRIVELINE = 0.97    # gearbox mechanical
AUX_W = 500.0           # accessory load, W
DT = 0.1                # s

# battery (stock FMU generic pack — Ch.27.2)
PACK_V = 3.7 * 5 * 20                       # 370 V nominal
PACK_AH = 3.2 * 4 * 2                       # 25.6 Ah
PACK_WH = PACK_V * PACK_AH                  # ~9472 Wh
ETA_INV, ETA_CONV = 0.95, 0.95
LOSS_DIS, LOSS_CHG = 0.05, 0.05
SOC0 = 0.75

T_DEM_MAX = 591.0       # Nm combined motor-side (r_ch axis max)
W_MAX = 1571.0          # rad/s, both motor map axes


class Motor:
    """Torque envelope + traction/regen efficiency maps from one FMU .mat."""

    def __init__(self, mat_path):
        m = loadmat(mat_path)
        self.spd = m["m_spd_data"].ravel()
        self.tmax = m["m_max_trq"].ravel()
        self.eff_spd = m["m_map_eff_spd"].ravel()
        self.eff_trq = m["m_map_eff_trq"].ravel()
        self.eff = m["m_eff_map"]                       # (spd, trq)
        self.rg_trq = m["m_map_eff_trq_regen"].ravel()
        self.rg_eff = m["m_eff_map_regen"]              # (spd, trq)

    def max_trq(self, w):
        return float(np.interp(abs(w), self.spd, self.tmax))

    def _bilerp(self, grid, xs, ys, x, y):
        x = np.clip(x, xs[0], xs[-1]); y = np.clip(y, ys[0], ys[-1])
        i = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
        j = np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2)
        fx = (x - xs[i]) / (xs[i + 1] - xs[i] + 1e-12)
        fy = (y - ys[j]) / (ys[j + 1] - ys[j] + 1e-12)
        g = grid
        return float((1-fx)*(1-fy)*g[i, j] + fx*(1-fy)*g[i+1, j] +
                     (1-fx)*fy*g[i, j+1] + fx*fy*g[i+1, j+1])

    def elec_power(self, w, T):
        """Electrical W at motor terminals. T>0 traction (draws), T<0 regen
        (returns). Mechanical power w*T; efficiency divides on the way in,
        multiplies on the way out."""
        pm = w * T
        if abs(pm) < 1.0:
            return pm
        if T >= 0:
            e = self._bilerp(self.eff, self.eff_spd, self.eff_trq, w, T)
            return pm / max(e, 0.30)
        e = self._bilerp(self.rg_eff, self.eff_spd, self.rg_trq, w, T)
        return pm * max(min(e, 0.99), 0.0)


def load_cycle(name):
    """EPA cycle file (2 header lines, tab 'sec  mph') -> (t, v m/s) at DT."""
    p = os.path.join(os.path.dirname(HERE), "cycles", name)
    raw = np.loadtxt(p, skiprows=2)
    t, v = raw[:, 0], raw[:, 1] * 0.44704
    tt = np.arange(t[0], t[-1], DT)
    return tt, np.interp(tt, t, v)


class DemoSplitEnv:
    """step(action r in [0,1]) -> obs, reward, done, info.
    obs = [v/55.55, T_dem/591, SOC]. Reward = -energy - jerk penalty."""

    # comfort sub-weights (documented in Bible 28.8; ISO-2631-flavoured jerk
    # emphasis). discomfort per step =
    #   C_JERK * jerk^2 * dt  +  C_ENGAGE per rear-axle wake/sleep event
    #   + C_RATE * (|dTf| + |dTr|) / T_DEM_MAX
    C_JERK = 0.02        # (m/s^3)^-2 s^-1 — 1 m/s^3 sustained ~ energy-visible
    C_ENGAGE = 0.05      # per event — the AVL "motor activation" analogue
    C_RATE = 0.02        # torque slew harshness
    ENGAGE_THR = 5.0     # Nm rear-torque hysteresis band for an "engagement"

    def __init__(self, cycle="hwycol.txt", w_energy=1.0, w_comfort=1.0,
                 soc0=SOC0, pack_wh=PACK_WH, obs_jerk=False):
        # obs_jerk=True appends normalized jerk to the observation - the
        # "jerk vision" upgrade (Bible Ch.29): the policy SEES harshness,
        # not just gets billed for it. Default False keeps v1 behavior.
        self.obs_jerk = obs_jerk
        self.front = Motor(os.path.join(STOCK, "one_strlineacc_0_frnt_motor_data.mat"))
        self.rear = Motor(os.path.join(STOCK, "one_strlineacc_0_rear_motor_data.mat"))
        self.t_grid, self.v_tgt = load_cycle(cycle)
        self.w_energy, self.w_comfort = w_energy, w_comfort
        self.soc0, self.pack_wh = soc0, pack_wh
        self.reset()

    def reset(self):
        self.k = 0
        self.v = float(self.v_tgt[0])
        self.soc = self.soc0
        self.dist = 0.0; self.e_batt_wh = 0.0
        self.prev_tf = 0.0; self.prev_tr = 0.0; self.prev_a = 0.0
        self.rear_awake = False
        self.g_mix = 0.5*(G_F + G_R)   # driver adapts to realized mix (28.9a)
        self.r_applied = 0.0           # slew-limited split: engagements ramp,
                                       # not clunk (28.9c); 2.0/s max
        self.track_err2 = 0.0
        self.jerk2_sum = 0.0; self.engage_events = 0
        self.discomfort = 0.0
        return self._obs(self._demand())

    def _road_load(self, v):
        return MASS*GRAV*CRR*np.tanh(v) + 0.5*RHO*CDA*v*v

    def _demand(self):
        """Driver: combined motor-side torque demand to follow the cycle."""
        vt = self.v_tgt[min(self.k + 1, len(self.v_tgt) - 1)]
        a_des = np.clip((vt - self.v)/DT, -5.0, 5.0)
        f = MASS*a_des + self._road_load(self.v)
        return float(np.clip(f*R_WHEEL/(self.g_mix*ETA_DRIVELINE),
                             -T_DEM_MAX, T_DEM_MAX))

    def _obs(self, t_dem):
        base = [self.v/55.55, t_dem/T_DEM_MAX, self.soc]
        if self.obs_jerk:
            jerk = (self.prev_a - getattr(self, "_a2", self.prev_a))/DT
            base.append(np.clip(jerk/10.0, -1.5, 1.5))
        return np.array(base, np.float64)

    def step(self, r):
        r_cmd = float(np.clip(r, 0.0, 1.0))
        self.r_applied += float(np.clip(r_cmd - self.r_applied, -2.0*DT, 2.0*DT))
        r = self.r_applied
        t_dem = self._demand()
        wf = np.clip(self.v/R_WHEEL*G_F, 0, W_MAX)
        wr = np.clip(self.v/R_WHEEL*G_R, 0, W_MAX)
        tf, tr = (1.0 - r)*t_dem, r*t_dem
        if t_dem >= 0:
            tf = min(tf, self.front.max_trq(wf)); tr = min(tr, self.rear.max_trq(wr))
        else:
            tf = max(tf, -self.front.max_trq(wf)); tr = max(tr, -self.rear.max_trq(wr))
            # regen shortfall vs demand -> friction brakes (no energy back)
        if abs(t_dem) > 20.0:      # driver learns the real demand->force mix
            self.g_mix = float(np.clip((tf*G_F + tr*G_R)/t_dem, G_R, G_F))
        f_wheel = (tf*G_F + tr*G_R)*ETA_DRIVELINE/R_WHEEL
        if t_dem < 0:   # friction brakes make up any deficit so the cycle holds
            f_need = MASS*np.clip((self.v_tgt[min(self.k+1, len(self.v_tgt)-1)]
                                   - self.v)/DT, -5.0, 5.0) + self._road_load(self.v)
            f_wheel = min(f_wheel, f_need) if f_need < f_wheel else f_wheel
        a = (f_wheel - self._road_load(self.v))/MASS
        self.v = max(self.v + a*DT, 0.0)
        self.dist += self.v*DT

        p_mot = self.front.elec_power(wf, tf) + self.rear.elec_power(wr, tr)
        p_dc = p_mot/(ETA_INV*ETA_CONV) if p_mot >= 0 else p_mot*ETA_INV*ETA_CONV
        p_batt = p_dc/(1-LOSS_DIS) if p_dc >= 0 else p_dc*(1-LOSS_CHG)
        p_batt += AUX_W
        e_wh = p_batt*DT/3600.0
        self.e_batt_wh += e_wh
        self.soc = float(np.clip(self.soc - e_wh/self.pack_wh, 0.0, 1.0))

        # ---- comfort accounting (Bible 28.8): jerk, axle engagement, slew ----
        jerk = (a - self.prev_a)/DT
        self._a2 = self.prev_a
        self.prev_a = a
        self.jerk2_sum += jerk*jerk*DT
        awake = abs(tr) > self.ENGAGE_THR
        engaged = awake != self.rear_awake
        if engaged:
            self.engage_events += 1
        self.rear_awake = awake
        step_discomfort = (self.C_JERK*jerk*jerk*DT
                           + (self.C_ENGAGE if engaged else 0.0)
                           + self.C_RATE*(abs(tf - self.prev_tf)
                                          + abs(tr - self.prev_tr))/T_DEM_MAX)
        self.discomfort += step_discomfort
        reward = -self.w_energy*e_wh - self.w_comfort*step_discomfort
        self.prev_tf, self.prev_tr = tf, tr
        self.k += 1
        done = self.k >= len(self.t_grid) - 1
        err = self.v - self.v_tgt[self.k]
        self.track_err2 += err*err
        info = {"tf": tf, "tr": tr, "t_dem": t_dem, "p_batt": p_batt,
                "v": self.v, "wr": wr, "jerk": jerk}
        return self._obs(self._demand()), reward, done, info

    def summary(self):
        km = max(self.dist/1000.0, 1e-9)
        minutes = self.k*DT/60.0
        return {"wh_per_km": self.e_batt_wh/km,
                "energy_wh": self.e_batt_wh,
                "dist_km": km,
                "soc_drop_pct": 100*(self.soc0 - self.soc),
                "track_rmse_kmh": 3.6*np.sqrt(self.track_err2/max(self.k, 1)),
                "jerk_rms": float(np.sqrt(self.jerk2_sum/max(self.k*DT, 1e-9))),
                "engage_per_min": self.engage_events/max(minutes, 1e-9),
                "discomfort": self.discomfort}
