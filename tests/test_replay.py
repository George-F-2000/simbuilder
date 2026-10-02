import re

import numpy as np
import pytest

from optimizer import replay


def test_segment_series_means_and_durations():
    t = np.arange(0.0, 10.0, 0.1)
    thr = np.where(t < 5, 0.2, 0.6)
    brk = np.where(t >= 8, 0.5, 0.0)
    segs = replay.segment_series(t, thr, brk, step_s=2.0)
    assert len(segs) == 5
    assert abs(sum(d for d, _, _ in segs) - 9.9) < 1e-6
    assert segs[0][1] == pytest.approx(0.2) and segs[-1][1] == pytest.approx(0.6)
    assert segs[-1][2] == pytest.approx(0.5, abs=0.01) and segs[0][2] == 0.0


def test_segment_series_clips_to_unit_interval():
    t = np.arange(0.0, 3.0, 0.5)
    segs = replay.segment_series(t, [1.5] * 6, [-0.2] * 6, step_s=1.0)
    assert all(s[1] == 1.0 and s[2] == 0.0 for s in segs)


def test_openloop_adf_grammar():
    segs = [(1.0, 0.3, 0.0), (1.0, 0.5, 0.0), (0.5, 0.0, 0.4)]
    adf = replay.build_openloop_adf("Test", segs, 5000.0, hmax=0.005)
    assert adf.count("[MANEUVER_") == 3
    assert adf.count("(CONTROLLERS)") == 3
    assert "VX0               = 5000" in adf
    assert "TYPE                   = 'CONSTANT'" in adf
    assert "[OL_BRAKE_3]" in adf and "VALUE                  = 0.4000" in adf
    assert "EXPRESSION" not in adf          # brake must never be an EXPRESSION block
    assert "'MANEUVER_1'" in adf and re.search(r"'MANEUVER_1'\s+1\s+0\.005\s+0\.01", adf)
    assert "[BRAKE_STANDARD]" in adf and "[THROTTLE_STANDARD]" in adf
    assert replay.sim_time(segs) == pytest.approx(2.5)


def test_replay_adf_from_reference():
    t = np.arange(0.0, 20.0, 0.1)
    ref = {"t": t, "pedal": 30.0 + 20.0 * (t > 10), "brake": np.zeros_like(t), "v0_kph": 36.0}
    adf, segs = replay.replay_adf("R", ref, step_s=2.0)
    assert len(segs) == 10
    assert segs[0][1] == pytest.approx(0.3) and segs[-1][1] == pytest.approx(0.5)
    assert "VX0               = 10000" in adf
    with pytest.raises(ValueError):
        replay.replay_adf("R", ref, pedal_mode="magic")
