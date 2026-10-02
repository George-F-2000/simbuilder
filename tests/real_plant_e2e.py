"""
Synthetic end-to-end test of the optimizer on the REAL plant (not a pytest;
takes tens of minutes of solver time):

    python tests/real_plant_e2e.py truth   [--seconds 40] [--lmy 1.15] [--aero 0.90]
    python tests/real_plant_e2e.py study   [--workers 6] [--grid 3] [--rounds 2]
    python tests/real_plant_e2e.py both

"truth": one replay of a synthetic pedal trace through the deck with the
tyre / aero scales PERTURBED by known factors, converted to MF4 and re-written
with INVENTED channel names in mixed units - the stand-in for a real-car log.
"study": the optimizer run against that log from the unperturbed base; pass =
the recovered scales land near the injected ones.

Prints only: injected vs recovered factors, totals, counts, timings. Files go
to %TEMP%/lyriq_runs/optimizer_e2e (local, not synced).
"""
import glob
import json
import os
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pipeline                                              # noqa: E402
from converter import convert                                # noqa: E402
from optimizer import logmatch, plant, replay                # noqa: E402
from optimizer import study as study_mod                     # noqa: E402

E2E = os.path.join(tempfile.gettempdir(), "lyriq_runs", "optimizer_e2e")
TRUTH_JSON = os.path.join(E2E, "truth.json")
CMAP = {
    "speed":        {"name": "Zz_Spd_mps", "unit": "m/s"},
    "pedal":        {"name": "Zz_AccPdl_frac", "unit": "0-1"},
    "brake":        {"name": "Zz_BrkPdl_pct", "unit": "%"},
    "torque_front": {"name": "Zz_MotTq_Frnt", "unit": "Nm"},
    "torque_rear":  {"name": "Zz_MotTq_Rr", "unit": "Nm"},
    "pack_power":   {"name": "Zz_HV_Pwr_W", "unit": "W"},
    "soc":          {"name": "Zz_SOC", "unit": "%"},
}
PAYLOAD = {"deck_default": False, "spec": {}, "generate_motors": False, "ems": {"enabled": False}}


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def synthetic_reference(seconds, dt=0.05):
    """Start at 50 km/h: 30 % -> 50 % tip-in -> 10 % lift (coast-down shows
    the road load) -> 35 %. No brake. Speeds span roughly 45-85 km/h so the
    v^2 (aero) and constant (rolling) terms separate."""
    t = np.arange(0.0, seconds + 1e-9, dt)
    q = t / seconds
    pedal = np.select([q < 0.25, q < 0.5, q < 0.75], [30.0, 50.0, 10.0], 35.0)
    return {"t": t, "pedal": pedal, "brake": np.zeros_like(t), "v0_kph": 50.0,
            "has": {"speed": False, "pedal": True, "brake": True}}


def settings_local():
    s = pipeline.load_settings()
    s["runs_dir"] = E2E
    s["optim_dir"] = os.path.join(E2E, "studies")
    os.makedirs(s["runs_dir"], exist_ok=True)
    return s


def truth():
    seconds, lmy, aero = arg("--seconds", 40.0), arg("--lmy", 1.15), arg("--aero", 0.90)
    s = settings_local()
    base = plant.base_files(s)
    assert base["tire_ok"] and base["aero_ok"], "base tyre/aero not resolvable"
    files = plant.candidate_files(os.path.join(E2E, "truth_plant"), 99,
                                  {"lmy_scale": lmy, "aero_scale": aero}, base["tire"], base["aero"])
    ref = synthetic_reference(seconds)
    adf, segs = replay.replay_adf("E2ETruth", ref, step_s=1.0, pedal_mode="physical")
    payload = dict(PAYLOAD, tire_path=files["tire_path"], aero_path=files["aero_path"])
    lines = []
    t0 = time.time()
    run_dir, deck = pipeline.prepare_run(s, "E2ETruth", adf, log=lines.append, vehicle=payload)
    plt = pipeline.run_motionsolve(s, run_dir, deck, log=lines.append, sim_total=replay.sim_time(segs))
    wall = time.time() - t0
    mf4 = convert(plt, log=lambda x: None, pack_voltage=float(s.get("pack_voltage") or 380.0))
    # re-write with invented names in mixed units: the stand-in real log
    from asammdf import MDF, Signal
    with logmatch.Log(mf4) as m:
        t, v = m.get("VehicleSpeed")
        get = lambda n: np.interp(t, *m.get(n))
        sigs = [Signal(v / 3.6, t, name="Zz_Spd_mps", unit="m/s"),
                Signal(get("AcceleratorPedal") / 100.0, t, name="Zz_AccPdl_frac", unit="0-1"),
                Signal(get("BrakePosition"), t, name="Zz_BrkPdl_pct", unit="%"),
                Signal(get("EM1Torque"), t, name="Zz_MotTq_Frnt", unit="Nm"),
                Signal(get("EM2Torque"), t, name="Zz_MotTq_Rr", unit="Nm"),
                Signal(get("BattPower") * 1000.0, t, name="Zz_HV_Pwr_W", unit="W"),
                Signal(get("BattSOC"), t, name="Zz_SOC", unit="%")]
    out = MDF(version="4.10")
    out.append(sigs, comment="synthetic stand-in for a real log (model run with perturbed road load)")
    fake = os.path.join(E2E, "fake_real_log.mf4")
    out.save(fake, overwrite=True)
    out.close()
    json.dump({"lmy": lmy, "aero": aero, "seconds": seconds, "log": fake, "run_dir": run_dir,
               "wall_s": round(wall)}, open(TRUTH_JSON, "w"), indent=1)
    print("TRUTH: injected lmy x{} aero x{} | {} s window solved in {:.0f} s | log -> {}".format(
        lmy, aero, seconds, wall, os.path.basename(fake)))
    for fp in glob.glob(os.path.join(run_dir, "*.mrf")) + glob.glob(os.path.join(run_dir, "*.abf")):
        os.remove(fp)
    return 0


def study():
    tr = json.load(open(TRUTH_JSON))
    s = settings_local()
    cfg = {"name": "e2e", "log_path": tr["log"], "channel_map": CMAP,
           "windows": [{"t0": 0.0, "t1": float(tr["seconds"])}],
           "params": {"lmy_scale": {"min": 0.7, "max": 1.6}, "aero_scale": {"min": 0.6, "max": 1.3}},
           "max_workers": int(arg("--workers", 6)), "step_s": 1.0, "pedal_mode": "physical",
           "settle_s": 2.0, "max_lag_s": 1.0, "base_payload": dict(PAYLOAD),
           "design": {"grid": int(arg("--grid", 3)), "rounds": int(arg("--rounds", 2)),
                      "shrink": 0.34, "tol": 0.0, "confirm": True}}
    log_lines = []
    st = study_mod.Study(s, cfg, app_log=log_lines.append)
    print("STUDY: {} | bounds {} | {} solvers".format(st.dir, cfg["params"], cfg["max_workers"]))
    st.start()
    last = None
    while st.is_running():
        time.sleep(20)
        snap = st.status()
        key = (snap["round"], snap["jobs_done"])
        if key != last:
            print("  round {} | jobs {}/{} | elapsed {} s | best {}".format(
                snap["round"], snap["jobs_done"], snap["jobs_total"], snap["elapsed_s"],
                (snap["best"] or {}).get("params")))
            last = key
    snap = st.status()
    best = snap["best"]
    print("STATUS:", snap["status"], "|", snap["message"])
    if not best:
        print("FAIL: no successful candidate"); return 1
    err_l = best["params"]["lmy_scale"] - tr["lmy"]
    err_a = best["params"]["aero_scale"] - tr["aero"]
    print("RESULT: injected lmy {:.3f} aero {:.3f} | best solved lmy {:.3f} aero {:.3f} "
          "(err {:+.3f}, {:+.3f}) | surface min {} | total {} | {} candidates in {} s".format(
              tr["lmy"], tr["aero"], best["params"]["lmy_scale"], best["params"]["aero_scale"],
              err_l, err_a, snap.get("surface_min"), best["score"], len(snap["candidates"]),
              snap["elapsed_s"]))
    sc = best["jobs"][0]["score"]
    print("  per signal:", {k: (v["nrmse"], v["corr"]) for k, v in sc["signals"].items()}, "lag", sc["lag_s"])
    ok = abs(err_l) <= 0.08 and abs(err_a) <= 0.08
    print("PASS" if ok else "CHECK: outside the 0.08 tolerance")
    try:
        out = study_mod.export_best(st.dir, s, out_root=os.path.join(E2E, "export"), redact=True)
        print("EXPORT:", {k: (os.path.basename(v) if isinstance(v, str) else v)
                          for k, v in out.items() if k in ("deck", "tire", "aero", "report", "figure", "export_dir")},
              "| mf4:", len(out["mf4"]))
    except Exception as exc:
        print("EXPORT FAILED:", type(exc).__name__, str(exc)[:200])
    return 0 if ok else 3


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    rc = 0
    if mode in ("truth", "both"):
        rc = truth()
    if rc == 0 and mode in ("study", "both"):
        rc = study()
    sys.exit(rc)
