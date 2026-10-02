"""
Real-solver smoke test for the optimizer chain (NOT a pytest; run by hand):

    python tests/real_plant_smoke.py [--seconds 20] [--lmy 1.0] [--aero 1.0]

One open-loop replay of a SYNTHETIC pedal trace through the deck configured
in settings.json, with the tyre / aero copies the optimizer would write, then
the .plt read back through the same path the study uses. Prints only
pass/fail, timings and channel presence - no vehicle values. The run lands in
%TEMP%/lyriq_runs/optimizer_smoke (local, not synced).
"""
import os
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pipeline                                   # noqa: E402
from optimizer import logmatch, plant, replay    # noqa: E402


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def synthetic_reference(seconds, dt=0.05):
    """Start at 30 km/h; pedal 25 % -> 45 % tip-in -> 15 % lift; no brake."""
    t = np.arange(0.0, seconds + 1e-9, dt)
    pedal = np.where(t < seconds * 0.5, 25.0, np.where(t < seconds * 0.75, 45.0, 15.0))
    return {"t": t, "pedal": pedal, "brake": np.zeros_like(t), "v0_kph": 30.0,
            "has": {"speed": False, "pedal": True, "brake": True}}


def main():
    seconds = arg("--seconds", 20.0)
    lmy, aero = arg("--lmy", 1.0), arg("--aero", 1.0)
    s = pipeline.load_settings()
    s["runs_dir"] = os.path.join(tempfile.gettempdir(), "lyriq_runs", "optimizer_smoke")
    os.makedirs(s["runs_dir"], exist_ok=True)
    base = plant.base_files(s)
    print("deck ok:", os.path.isfile(s["deck"]), "| tyre ok:", base["tire_ok"],
          "| aero ok:", base["aero_ok"])
    if not (base["tire_ok"] and base["aero_ok"]):
        print("FAIL: base tyre/aero not resolvable"); return 2
    files = plant.candidate_files(os.path.join(s["runs_dir"], "plant"), 0,
                                  {"lmy_scale": lmy, "aero_scale": aero},
                                  base["tire"], base["aero"])
    print("plant copies written: lmy rows ok, aero rows scaled:", files["edits"]["aero"]["rows"])
    ref = synthetic_reference(seconds)
    adf, segs = replay.replay_adf("OptSmoke", ref, step_s=1.0, pedal_mode="physical")
    print("ADF: {} maneuvers, {} s".format(len(segs), replay.sim_time(segs)))
    payload = {"deck_default": False, "spec": {}, "generate_motors": False,
               "ems": {"enabled": False}, "tire_path": files["tire_path"],
               "aero_path": files["aero_path"]}
    lines = []

    def log(x):
        lines.append(str(x))

    t0 = time.time()
    run_dir, deck = pipeline.prepare_run(s, "OptSmoke", adf, log=log, vehicle=payload)
    print("prepared in {:.1f} s -> {}".format(time.time() - t0, run_dir))
    for l in lines:
        if "tire file" in l or "aero file" in l or "WARNING" in l or "plant repairs" in l \
                or "deck hook" in l:
            print("  " + l.strip())
    holder = {"proc": None}
    t1 = time.time()
    try:
        plt = pipeline.run_motionsolve(s, run_dir, deck, log=log, proc_holder=holder,
                                       sim_total=replay.sim_time(segs))
    except Exception as exc:
        print("SOLVER FAILED after {:.0f} s: {}".format(time.time() - t1, str(exc)[:200]))
        errs = [l for l in lines if "ERROR" in l or "error" in l.lower()][:8]
        for e in errs:
            print("  " + e.strip()[:160])
        open(os.path.join(run_dir, "smoke_log.txt"), "w", encoding="utf-8").write("\n".join(lines))
        return 1
    wall = time.time() - t1
    n_time = sum(1 for l in lines if pipeline.TIME_LINE.match(l))
    print("solved in {:.0f} s ({} Time= lines); .plt {:.1f} MB".format(
        wall, n_time, os.path.getsize(plt) / 1e6))
    model = logmatch.model_from_plt(plt, pack_voltage=float(s.get("pack_voltage") or 380.0))
    present = [k for k, v in model["has"].items() if v]
    print("model channels present:", present, "| missing:", model["missing"][:6])
    print("model duration {:.1f} s (requested {:.1f}); samples {}".format(
        float(model["t"][-1]), replay.sim_time(segs), len(model["t"])))
    # a self-score (model against itself) must be perfect: validates the scorer path
    self_ref = dict(model); self_ref["has"] = dict(model["has"])
    sc = logmatch.score(model, self_ref, settle_s=2.0, max_lag_s=1.0)
    print("self-score total {} (expect 0), lag {}".format(sc["total"], sc["lag_s"]))
    open(os.path.join(run_dir, "smoke_log.txt"), "w", encoding="utf-8").write("\n".join(lines))
    print("PASS" if sc["total"] < 1e-6 and float(model["t"][-1]) >= 0.9 * replay.sim_time(segs) else "CHECK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
