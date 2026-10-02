import numpy as np
import pytest

from optimizer import logmatch
from conftest import demo_drive


def test_suggest_map_from_role_words_and_units():
    chans = [{"name": "Zz_Spd_mps", "unit": "m/s"}, {"name": "Zz_AccPdl_frac", "unit": ""},
             {"name": "Zz_BrkPdl_pct", "unit": "%"}, {"name": "Zz_MotTq_Frnt", "unit": "Nm"},
             {"name": "Zz_MotTq_Rr", "unit": "Nm"}, {"name": "Zz_HV_Pwr_W", "unit": "W"},
             {"name": "Zz_SOC", "unit": "%"}, {"name": "Zz_Yaw", "unit": "deg/s"}]
    m = logmatch.suggest_map(chans)
    assert m["speed"]["name"] == "Zz_Spd_mps" and m["speed"]["unit"] == "m/s"
    assert m["pedal"]["name"] == "Zz_AccPdl_frac"
    assert m["brake"]["name"] == "Zz_BrkPdl_pct"
    assert m["torque_front"]["name"] == "Zz_MotTq_Frnt"
    assert m["torque_rear"]["name"] == "Zz_MotTq_Rr"
    assert m["pack_power"]["name"] == "Zz_HV_Pwr_W" and m["pack_power"]["unit"] == "W"
    assert m["soc"]["name"] == "Zz_SOC"


def test_unit_factors():
    assert logmatch.unit_factor("speed", "m/s") == pytest.approx(3.6)
    assert logmatch.unit_factor("pedal", "0-1") == 100.0
    assert logmatch.unit_factor("pack_power", "W") == 0.001
    assert logmatch.unit_factor("brake", None, full_scale=50.0) == 2.0
    with pytest.raises(ValueError):
        logmatch.unit_factor("speed", "furlongs")


def test_log_reference_and_units(fake_log):
    path, cmap = fake_log
    with logmatch.Log(path) as log:
        assert len(log.channels) == 7
        assert len(log.fingerprint) == 12
        assert logmatch.check_map(cmap, log) == []
        ref = logmatch.reference(log, cmap, 40.0, 60.0, dt=0.05)
    t, v, pedal, brake, torque, power, soc = demo_drive()
    i0, i1 = int(40 / 0.05), int(60 / 0.05)
    assert ref["t"][0] == 0.0 and ref["t"][-1] == pytest.approx(20.0, abs=0.06)
    assert np.allclose(ref["speed"], v[i0:i1 + 1][:len(ref["speed"])], atol=0.2)   # m/s -> km/h
    assert np.allclose(ref["pedal"], pedal[i0:i1 + 1][:len(ref["pedal"])], atol=0.5)  # 0-1 -> %
    assert np.allclose(ref["pack_power"], power[i0:i1 + 1][:len(ref["pack_power"])], atol=0.05)  # W -> kW
    assert ref["v0_kph"] == pytest.approx(v[i0], abs=0.3)
    assert ref["has"]["brake"] and ref["has"]["soc"]


def test_check_map_reports_problems(fake_log):
    path, cmap = fake_log
    bad = dict(cmap)
    bad["speed"] = {"name": "Nope", "unit": "m/s"}
    bad["pedal"] = None
    with logmatch.Log(path) as log:
        probs = logmatch.check_map(bad, log)
    assert any("not in this log" in p for p in probs)
    assert any("required" in p for p in probs)


def test_saved_map_roundtrip(fake_log, tmp_path, monkeypatch):
    path, cmap = fake_log
    monkeypatch.setattr(logmatch, "aliases_path", lambda: str(tmp_path / "aliases.json"))
    with logmatch.Log(path) as log:
        m0, src0 = logmatch.resolve_map(log)
        assert src0 == "suggested"
        logmatch.save_map(log.fingerprint, cmap, path)
        m1, src1 = logmatch.resolve_map(log)
    assert src1 == "saved" and m1 == cmap


def test_find_windows_excludes_standstill(fake_log):
    path, cmap = fake_log
    with logmatch.Log(path) as log:
        t0, t1 = log.span(cmap["speed"]["name"])
        ref = logmatch.reference(log, cmap, t0, t1, dt=0.05)
    wins = logmatch.find_windows(ref, min_len_s=15, max_len_s=60, v_floor_kph=3.0)
    assert wins, "expected at least one moving window"
    for w in wins:
        assert w["dur_s"] >= 15 and w["dur_s"] <= 60.5
        assert w["v0_kph"] > 3.0
        # no window straddles the standstill at 120-130 s
        assert not (w["t0"] < 122 < w["t1"]) and not (w["t0"] < 128 < w["t1"])
    bf = logmatch.find_windows(ref, min_len_s=15, max_len_s=60, brake_free=True)
    for w in bf:
        assert w["brake_frac"] == 0.0
    assert any(w["tipins"] > 0 for w in wins)


def test_best_lag_recovers_known_shift():
    t = np.arange(0.0, 60.0, 0.01)
    y = 50 + 10 * np.sin(t / 3.0) + 3 * np.sin(t * 1.7)
    lag = 0.37
    model_t, model_y = t, np.interp(t - lag, t, y)       # model trails by 0.37 s
    assert logmatch.best_lag(model_t, model_y, t, y, max_lag_s=1.0, dt=0.01) == pytest.approx(lag, abs=0.011)


def test_score_identical_is_perfect_and_scaled_is_not():
    t = np.arange(0.0, 40.0, 0.01)
    base = {"t": t, "has": {"speed": True, "torque_front": True, "pack_power": True},
            "speed": 40 + 10 * np.sin(t / 4), "torque_front": 100 + 50 * np.cos(t / 3),
            "pack_power": 10 + 5 * np.sin(t / 2)}
    ref = dict(base)
    ref["has"] = dict(base["has"], torque_rear=False)
    s = logmatch.score(base, ref, settle_s=2.0, max_lag_s=1.0)
    assert s["total"] == pytest.approx(0.0, abs=1e-6)
    assert s["signals"]["speed"]["corr"] == pytest.approx(1.0)
    assert s["lag_s"] == 0.0
    worse = dict(base)
    worse["speed"] = base["speed"] * 1.1
    s2 = logmatch.score(worse, ref, settle_s=2.0, max_lag_s=1.0)
    assert s2["total"] > 0.05
    assert s2["signals"]["speed"]["nrmse"] > 0 and s2["signals"]["torque_front"]["nrmse"] == 0
    assert any("torque_rear" in n for n in s2["notes"])


def test_score_penalises_early_end():
    t = np.arange(0.0, 40.0, 0.01)
    ref = {"t": t, "has": {"speed": True}, "speed": 40 + 10 * np.sin(t / 4)}
    short = {"t": t[:1500], "has": {"speed": True}, "speed": ref["speed"][:1500]}
    s = logmatch.score(short, ref, settle_s=2.0, max_lag_s=1.0)
    assert any("ended early" in n for n in s["notes"])
