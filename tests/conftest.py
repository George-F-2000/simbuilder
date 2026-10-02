"""Shared fixtures: synthetic tyre / aero files in the Altair demo formats, a
synthetic MF4 "real log" with invented channel names, and a demo drive."""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TIR_TEXT = """[UNITS]
 LENGTH = 'meter'
[SCALING_COEFFICIENTS]
 LFZO =                            1                      $Scale factor of nominal (rated) load
 LMUX =                            1                      $Scale factor of Fx peak friction coefficient
 LMY =                             1.25                   $Scale factor of rolling resistance torque
 LMUY =                            1                      $
[ROLLING_COEFFICIENTS]
 QSY1 =                            0.01                   $Rolling resistance torque coefficient
 QSY2 =                            0                      $
"""

AAE_TEXT = """$------------------------------------------------------------------ALTAIR_HEADER
[ALTAIR_HEADER]
FILE_TYPE 		= 'AAE'
FILE_VERSION 	= 1.0
$------------------------------------------------------------GEOMETRIC_PROPERTIES
[GEOMETRIC_PROPERTIES]
FRONTAL_SECTION_AREA        = 2e6
$---------------------------------------------------------------DRAG_COEFFICIENT
[DRAG_COEFFICIENT]
INTERPOLATION = 'AKIMA'
(SPLINE_DATA)
{INCIDENCE_ANGLE    COEFFICIENT}
0.0                 0.3
10.0                0.31
20.0                0.32
30.0                0.33
$---------------------------------------------------------------DRAG_COEFFICIENT
$----------------------------------------------------------SIDEFORCE_COEFFICIENT
[SIDEFORCE_COEFFICIENT]
INTERPOLATION = 'AKIMA'
(SPLINE_DATA)
{INCIDENCE_ANGLE    COEFFICIENT}
0.0                 0.0
10.0                0.4
$----------------------------------------------------------SIDEFORCE_COEFFICIENT
"""


@pytest.fixture
def tir_file(tmp_path):
    p = tmp_path / "demo.tir"
    p.write_text(TIR_TEXT, encoding="utf-8")
    return str(p)


@pytest.fixture
def aae_file(tmp_path):
    p = tmp_path / "demo.aae"
    p.write_text(AAE_TEXT, encoding="utf-8")
    return str(p)


def demo_drive(dt=0.05, seed=0):
    """A synthetic drive: standstill, launch, cruise with tip-ins, a braking
    stop, a second drive. Returns t, speed km/h, pedal %, brake %,
    torque Nm, power kW, soc %."""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, 240.0, dt)
    v = np.zeros_like(t)
    pedal = np.zeros_like(t)
    brake = np.zeros_like(t)
    # 0-10 s standstill; 10-40 s launch to 60; 40-100 cruise with tip-ins;
    # 100-120 brake to stop; 120-130 stop; 130-200 drive; 200-240 coast+stop
    for i, ti in enumerate(t):
        if ti < 10:
            v[i] = 0.0
        elif ti < 40:
            v[i] = 60.0 * (ti - 10) / 30.0
            pedal[i] = 35.0
        elif ti < 100:
            v[i] = 60.0 + 5.0 * np.sin((ti - 40) / 6.0)
            pedal[i] = 20.0 + 15.0 * (np.sin((ti - 40) / 6.0) > 0.7)
        elif ti < 120:
            v[i] = 60.0 * (1 - (ti - 100) / 20.0)
            brake[i] = 30.0
        elif ti < 130:
            v[i] = 0.0
        elif ti < 200:
            v[i] = min(80.0, 80.0 * (ti - 130) / 40.0)
            pedal[i] = 40.0 if ti < 170 else 25.0
        else:
            v[i] = max(0.0, 80.0 - 80.0 * (ti - 200) / 30.0)
            brake[i] = 20.0 if ti > 215 else 0.0
    v = np.maximum(v + rng.normal(0, 0.1, t.size), 0.0)
    torque = 2.5 * pedal - 0.8 * brake - 0.3 * v / 10.0
    power = torque * v / 60.0 + 1.0
    soc = 80.0 - np.cumsum(np.maximum(power, 0)) * dt / 3600.0 * 2.0
    return t, v, pedal, brake, torque, power, soc


@pytest.fixture
def fake_log(tmp_path):
    """A synthetic MF4 with INVENTED channel names (nothing from any real
    car) in mixed units, plus the mapping that reads it."""
    from asammdf import MDF, Signal
    t, v, pedal, brake, torque, power, soc = demo_drive()
    sigs = [
        Signal(v / 3.6, t, name="Zz_Spd_mps", unit="m/s"),
        Signal(pedal / 100.0, t, name="Zz_AccPdl_frac", unit="0-1"),
        Signal(brake, t, name="Zz_BrkPdl_pct", unit="%"),
        Signal(torque, t, name="Zz_MotTq_Frnt", unit="Nm"),
        Signal(torque * 0.0, t, name="Zz_MotTq_Rr", unit="Nm"),
        Signal(power * 1000.0, t, name="Zz_HV_Pwr_W", unit="W"),
        Signal(soc, t, name="Zz_SOC", unit="%"),
    ]
    m = MDF(version="4.10")
    m.append(sigs, comment="synthetic test log")
    path = str(tmp_path / "fake_log.mf4")
    m.save(path, overwrite=True)
    m.close()
    cmap = {
        "speed": {"name": "Zz_Spd_mps", "unit": "m/s"},
        "pedal": {"name": "Zz_AccPdl_frac", "unit": "0-1"},
        "brake": {"name": "Zz_BrkPdl_pct", "unit": "%"},
        "torque_front": {"name": "Zz_MotTq_Frnt", "unit": "Nm"},
        "torque_rear": {"name": "Zz_MotTq_Rr", "unit": "Nm"},
        "pack_power": {"name": "Zz_HV_Pwr_W", "unit": "W"},
        "soc": {"name": "Zz_SOC", "unit": "%"},
    }
    return path, cmap
