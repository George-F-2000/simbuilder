"""The search and the scheduler, with the solver replaced by a synthetic plant
whose response has a known optimum. No MotionSolve needed."""
import json
import os
import re
import threading
import time

import numpy as np
import pytest

import pipeline
from optimizer import logmatch, plant
from optimizer import study as study_mod

TRUE = {"lmy_scale": 1.15, "aero_scale": 0.90}
PLANT = {"study": None}      # the fake plant finds the window's reference here


def test_grid_points_and_dedupe():
    b = {"lmy_scale": (0.8, 1.2), "aero_scale": (0.9, 1.1)}
    pts = study_mod.grid_points(b, 3)
    assert len(pts) == 9
    pinned = {"lmy_scale": (0.8, 1.2), "aero_scale": (1.0, 1.0)}
    assert len(study_mod.grid_points(pinned, 3)) == 3
    sub = study_mod.grid_points(b, 3, center={"lmy_scale": 1.2, "aero_scale": 1.0},
                                span={"lmy_scale": 0.2, "aero_scale": 0.1})
    assert max(p["lmy_scale"] for p in sub) <= 1.2 + 1e-9      # clipped to bounds


def test_quadratic_surface_recovers_minimum():
    b = {"lmy_scale": (0.8, 1.4), "aero_scale": (0.7, 1.2)}
    pts = study_mod.grid_points(b, 3)
    tot = [3 * (p["lmy_scale"] - 1.1) ** 2 + 5 * (p["aero_scale"] - 0.95) ** 2 + 0.01 for p in pts]
    surf = study_mod.fit_quadratic(pts, tot, b)
    assert surf["r2"] > 0.999
    m = study_mod.surface_min(surf, b)
    assert m["lmy_scale"] == pytest.approx(1.1, abs=1e-3)
    assert m["aero_scale"] == pytest.approx(0.95, abs=1e-3)


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace prepare_run / run_motionsolve / model_from_plt with a plant
    whose curves drift linearly with the distance from TRUE, and record the
    number of concurrently 'solving' jobs."""
    state = {"active": 0, "peak": 0, "calls": 0, "fail_ids": set()}
    lock = threading.Lock()

    def fake_prepare_run(settings, name, adf, log, vehicle=None, **kw):
        rd = os.path.join(settings["runs_dir"], name + "_" + time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "params.json"), "w") as fh:
            json.dump({"tire": vehicle["tire_path"], "aero": vehicle["aero_path"],
                       "deck_default": vehicle.get("deck_default")}, fh)
        log("Run folder: " + rd)
        return rd, name + ".xml"

    def fake_run_motionsolve(settings, run_dir, deck, log, progress=None, sim_total=None,
                             proc_holder=None):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["calls"] += 1
        try:
            for k in range(4):
                time.sleep(0.03)
                log("Time=%.2E; Order=2" % (k + 1))
                if progress and sim_total:
                    progress((k + 1) / 4.0, "")
            cid = int(re.search(r"_c(\d+)_w", os.path.basename(run_dir)).group(1))
            if cid in state["fail_ids"]:
                raise RuntimeError("MotionSolve exited with code 1")
            plt = os.path.join(run_dir, deck.replace(".xml", ".plt"))
            open(plt, "w").write("fake")
            return plt
        finally:
            with lock:
                state["active"] -= 1

    def fake_model_from_plt(plt_path, nam_path=None, pack_voltage=380.0, log=None):
        rd = os.path.dirname(plt_path)
        wi = int(re.search(r"_w(\d+)_", os.path.basename(rd)).group(1))
        ref = PLANT["study"].refs[wi]
        p = json.load(open(os.path.join(rd, "params.json")))
        lmy = plant.scale_keyword(open(p["tire"]).read(), "LMY", 1.0)[1] / 1.25
        aero_txt = open(p["aero"]).read().split("[DRAG_COEFFICIENT]")[1]
        aero = float(aero_txt.split("\n0.0")[1].split()[0]) / 0.3
        d_l, d_a = lmy - TRUE["lmy_scale"], aero - TRUE["aero_scale"]
        t = ref["t"]
        speed = ref["speed"] * (1 + 0.15 * d_l + 0.10 * d_a) + 2.0 * d_l * np.sin(t / 3)
        torque = ref["torque_front"] + 40.0 * d_a + 25.0 * d_l
        return {"t": t, "has": {"speed": True, "torque_front": True, "torque_rear": True,
                                "pack_power": True, "pedal": True, "brake": True, "soc": False},
                "speed": speed, "torque_front": torque, "torque_rear": ref["torque_rear"],
                "pack_power": ref["pack_power"] * (1 + 0.2 * d_a), "pedal": ref["pedal"],
                "brake": ref["brake"]}

    monkeypatch.setattr(pipeline, "prepare_run", fake_prepare_run)
    monkeypatch.setattr(pipeline, "run_motionsolve", fake_run_motionsolve)
    monkeypatch.setattr(logmatch, "model_from_plt", fake_model_from_plt)
    monkeypatch.setattr(pipeline, "kill_process_tree", lambda pid, log=None: None)
    return state


def _settings(tmp_path):
    deck = tmp_path / "deck.xml"
    deck.write_text("<Model/>")
    return {"deck": str(deck), "runs_dir": str(tmp_path / "runs"),
            "optim_dir": str(tmp_path / "optim"), "motionsolve": "x", "pack_voltage": 380.0}


def _config(fake_log, tir_file, aae_file, **over):
    path, cmap = fake_log
    c = {"name": "unit test", "log_path": path, "channel_map": cmap,
         "windows": [{"t0": 45.0, "t1": 75.0}, {"t0": 140.0, "t1": 165.0}],
         "params": {"lmy_scale": {"min": 0.8, "max": 1.5}, "aero_scale": {"min": 0.6, "max": 1.3}},
         "max_workers": 3, "tire_src": tir_file, "aero_src": aae_file,
         "design": {"grid": 3, "rounds": 2, "shrink": 0.34, "tol": 0.0, "confirm": True},
         "settle_s": 1.0, "max_lag_s": 0.5}
    c.update(over)
    return c


def test_study_rejects_locked_parameters(tmp_path, fake_log, tir_file, aae_file):
    cfg = _config(fake_log, tir_file, aae_file, params={"mass_kg": {"min": 1, "max": 2}})
    with pytest.raises(KeyError):
        study_mod.Study(_settings(tmp_path), cfg)


def test_study_finds_the_known_optimum(tmp_path, fake_log, tir_file, aae_file, fake_pipeline):
    settings = _settings(tmp_path)
    cfg = _config(fake_log, tir_file, aae_file)
    flags = []
    st = study_mod.Study(settings, cfg, on_running=flags.append)
    PLANT["study"] = st
    st.start()
    st.join(timeout=180)
    assert not st.is_running()
    s = st.status()
    assert s["status"] == "done", s["message"]
    assert flags == [True, False]
    # 9 + up to 9 + 1 candidates, every job scored, solver cap respected
    assert 10 <= len(s["candidates"]) <= 19
    assert all(c["status"] == "ok" for c in s["candidates"])
    assert fake_pipeline["peak"] <= 3
    assert fake_pipeline["calls"] == s["jobs_done"] == 2 * len(s["candidates"])
    best = s["best"]
    assert abs(best["params"]["lmy_scale"] - TRUE["lmy_scale"]) < 0.08
    assert abs(best["params"]["aero_scale"] - TRUE["aero_scale"]) < 0.08
    assert s["surface"]["r2"] > 0.9
    # state persisted, run folders named uniquely, plant copies per candidate
    on_disk = json.load(open(os.path.join(st.dir, "state.json")))
    assert on_disk["best"]["id"] == best["id"]
    names = [os.path.basename(j["run_dir"]) for c in s["candidates"] for j in c["jobs"]]
    assert len(set(names)) == len(names)
    assert len(os.listdir(os.path.join(st.dir, "plant"))) == 2 * len(s["candidates"])
    assert all(j["run_dir"].startswith(st.dir) for c in s["candidates"] for j in c["jobs"])
    assert os.path.isfile(os.path.join(st.dir, "logs", "study.log"))
    assert all(abs(j["score"]["lag_s"]) <= 0.5 for c in s["candidates"] for j in c["jobs"])


def test_failed_solve_is_penalised_not_fatal(tmp_path, fake_log, tir_file, aae_file, fake_pipeline):
    settings = _settings(tmp_path)
    cfg = _config(fake_log, tir_file, aae_file, design={"grid": 2, "rounds": 1, "confirm": False},
                  windows=[{"t0": 45.0, "t1": 65.0}])
    fake_pipeline["fail_ids"].add(1)
    st = study_mod.Study(settings, cfg)
    PLANT["study"] = st
    st.start()
    st.join(timeout=60)
    s = st.status()
    assert s["status"] == "done"
    c1 = s["candidates"][1]
    assert c1["status"] == "failed" and c1["score"] == study_mod.FAIL_PENALTY
    assert "code 1" in c1["jobs"][0]["error"]
    assert s["best"]["id"] != 1
    assert sum(1 for c in s["candidates"] if c["status"] == "ok") == 3
    assert os.path.isfile(os.path.join(st.dir, "logs", "{}_c01_w0.log".format(st.short)))


def test_stop_ends_the_study(tmp_path, fake_log, tir_file, aae_file, fake_pipeline):
    settings = _settings(tmp_path)
    cfg = _config(fake_log, tir_file, aae_file, design={"grid": 3, "rounds": 3, "confirm": False},
                  max_workers=1, windows=[{"t0": 45.0, "t1": 65.0}])
    st = study_mod.Study(settings, cfg)
    PLANT["study"] = st
    st.start()
    time.sleep(0.5)
    st.stop()
    st.join(timeout=30)
    s = st.status()
    assert s["status"] == "stopped"
    assert len(s["candidates"]) <= 9
    assert s["jobs_done"] < 27
