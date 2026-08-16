"""
policies.py — split strategies the gym can play, including the STOCK champion.
Every policy is a callable: r = policy(obs, info_prev) with r in [0,1]
(fraction of combined demand to the REAR/secondary motor).
"""

import os

import numpy as np
from scipy.io import loadmat

from gym_env import STOCK, DemoSplitEnv, G_R, R_WHEEL, W_MAX, T_DEM_MAX


class StockMapPolicy:
    """The stock FMU's own r_ch(w_rear, T_dem) lookup — 'STOCK EMS'.
    Exactly the table MotionSolve runs (Hamiltonian/offline-optimal family)."""

    def __init__(self):
        m = loadmat(os.path.join(STOCK, "one_strlineacc_0_opt_trq_ratio.mat"))
        self.w = m["w"].ravel(); self.T = m["T_dem"].ravel(); self.r = m["r_ch"]

    def __call__(self, obs, info=None):
        v = obs[0]*55.55
        w = np.clip(v/R_WHEEL*G_R, self.w[0], self.w[-1])
        T = np.clip(abs(obs[1])*T_DEM_MAX, self.T[0], self.T[-1])
        i = int(np.clip(np.searchsorted(self.w, w)-1, 0, len(self.w)-2))
        j = int(np.clip(np.searchsorted(self.T, T)-1, 0, len(self.T)-2))
        return float(self.r[i, j])


def single_motor(obs, info=None):
    return 0.0          # everything to the front (primary) — real-car MCT mode


def even_split(obs, info=None):
    return 0.5


class LossGreedy:
    """Per-step brute force: try 21 splits, keep the one with least electrical
    power RIGHT NOW. The 'instantaneous physics optimum' reference — what a
    perfect myopic optimizer achieves (no foresight, no smoothness)."""

    def __init__(self, env: DemoSplitEnv):
        self.env = env
        self.grid = np.linspace(0, 1, 21)

    def __call__(self, obs, info=None):
        e = self.env
        v = obs[0]*55.55; t_dem = obs[1]*T_DEM_MAX
        wf = np.clip(v/R_WHEEL*18.0, 0, W_MAX)
        wr = np.clip(v/R_WHEEL*G_R, 0, W_MAX)
        best_r, best_p = 0.0, np.inf
        for r in self.grid:
            tf, tr = (1-r)*t_dem, r*t_dem
            if t_dem >= 0:
                tf = min(tf, e.front.max_trq(wf)); tr = min(tr, e.rear.max_trq(wr))
            else:
                tf = max(tf, -e.front.max_trq(wf)); tr = max(tr, -e.rear.max_trq(wr))
            p = e.front.elec_power(wf, tf) + e.rear.elec_power(wr, tr)
            if p < best_p:
                best_p, best_r = p, r
        return best_r
