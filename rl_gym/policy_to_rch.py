"""
policy_to_rch.py — Step 4 of Bible Ch.28: flatten any policy into a stock-
shaped r_ch map. We ask the policy "what split would you pick?" at every one
of the stock map's 151 rear-motor-speed x 198 torque-demand grid points and
write the answers into a .mat with the exact same variable names (w, T_dem,
r_ch). SimBuilder's existing EMS injection then treats it like any other map.
"""

import os

import numpy as np
from scipy.io import loadmat, savemat

from gym_env import STOCK, G_R, R_WHEEL


def flatten_to_rch(policy, out_path):
    """policy(v_mps, t_dem_nm, soc) -> r in [0,1]; returns out_path."""
    m = loadmat(os.path.join(STOCK, "one_strlineacc_0_opt_trq_ratio.mat"))
    w, T = m["w"].ravel(), m["T_dem"].ravel()
    r = np.zeros((len(w), len(T)))
    for i, wi in enumerate(w):
        v = wi * R_WHEEL / G_R          # rear motor speed -> vehicle speed
        for j, tj in enumerate(T):
            r[i, j] = policy(v, tj)
    savemat(out_path, {"w": w.reshape(1, -1), "T_dem": T.reshape(1, -1),
                       "r_ch": r})
    return out_path


if __name__ == "__main__":
    # smoke: flatten the trivial single-motor policy
    p = flatten_to_rch(lambda v, t, soc=0.75: 0.0,
                       os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "smoke_single_motor.mat"))
    print("smoke map:", p)
