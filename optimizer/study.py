"""
optimizer/study.py
================================================================================
A STUDY: the search over the two road-load scales, the scheduler that runs
candidates in parallel, its state, and the export of the tuned model.

Search (two parameters, expensive evaluations):
  round 1  a grid over the bounds (design.grid x design.grid candidates);
  fit      a quadratic response surface to every candidate scored so far;
  round k  a grid of the same size over a box of design.shrink x the previous
           span, centred on the surface minimum (clipped to the bounds);
  confirm  one solve at the final surface minimum.
The reported best is the best candidate actually SOLVED, never a surface
prediction. Early stop when a round improves the best total by less than
design.tol (relative).

Evaluation of one (candidate, window) job:
  plant copies  -> ADF from the log window -> pipeline.prepare_run (unique
  name, this study's folder as runs_dir) -> pipeline.run_motionsolve with its
  own process holder and log -> logmatch.model_from_plt -> logmatch.score.
  No MF4 is written for intermediate candidates (the Results tab therefore
  never sees them); the best candidate is converted on export.

The study folder:
  <optim_dir>/<name>_<stamp>/config.json, state.json, plant/, logs/,
  <name>_cNN_wM_<stamp>/ (one per job), best/ (after export).
================================================================================
"""
import copy
import glob
import itertools
import json
import os
import re
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import numpy as np

import pipeline
from . import logmatch, plant, replay

STATE_FILE = "state.json"
CONFIG_FILE = "config.json"
DEFAULT_DESIGN = {"grid": 3, "rounds": 2, "shrink": 0.34, "tol": 0.02,
                  "confirm": True}
FAIL_PENALTY = 10.0
FATAL_PATTERNS = ("License error", "license error", "Simulation failed",
                  "ERROR: Unable to open", "not well-formed")
FATAL_GRACE_S = 30.0


def optim_root(settings):
    return settings.get("optim_dir") or os.path.join(settings["runs_dir"], "optimizer")


# ------------------------------------------------------------------- design
def grid_points(bounds, n=3, center=None, span=None):
    """Candidate parameter sets on a regular grid. bounds {name: (lo, hi)};
    with center/span {name: value} the grid covers [center - span/2,
    center + span/2] clipped to bounds. Duplicates removed."""
    axes = []
    names = sorted(bounds)
    for k in names:
        lo, hi = float(bounds[k][0]), float(bounds[k][1])
        if center is not None and span is not None:
            c, s = float(center[k]), float(span[k])
            a, b = max(lo, c - s / 2), min(hi, c + s / 2)
            if b - a < 1e-9:
                a, b = lo, hi
            lo, hi = a, b
        axes.append(np.linspace(lo, hi, int(n)) if n > 1 else np.array([(lo + hi) / 2]))
    pts, seen = [], set()
    for combo in itertools.product(*axes):
        key = tuple(round(float(v), 6) for v in combo)
        if key in seen:
            continue
        seen.add(key)
        pts.append({k: float(v) for k, v in zip(names, key)})
    return pts


def _norm(p, bounds, names):
    return [2.0 * (float(p[k]) - bounds[k][0]) / (bounds[k][1] - bounds[k][0]) - 1.0
            for k in names]


def _denorm(x, bounds, names):
    return {k: bounds[k][0] + (xi + 1.0) / 2.0 * (bounds[k][1] - bounds[k][0])
            for k, xi in zip(names, x)}


def fit_quadratic(points, totals, bounds):
    """Quadratic response surface over the normalised box [-1, 1]^2.
    Returns {"coeffs", "r2", "names", "n"} or None with fewer than 6 points."""
    names = sorted(bounds)
    if len(points) < 6 or len(names) != 2:
        return None
    X = np.array([_norm(p, bounds, names) for p in points])
    y = np.asarray(totals, float)
    A = np.column_stack([np.ones(len(X)), X[:, 0], X[:, 1],
                         X[:, 0] ** 2, X[:, 1] ** 2, X[:, 0] * X[:, 1]])
    coeffs, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ coeffs
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    return {"coeffs": [float(c) for c in coeffs], "r2": round(1 - ss_res / ss_tot, 4),
            "names": names, "n": int(len(y))}


def surface_min(surface, bounds):
    """Minimiser of the fitted quadratic inside the box, as {name: value}.
    Uses the stationary point when the Hessian is positive definite and the
    point lies inside; otherwise the best of a fine grid."""
    a, b, c, d, e, f = surface["coeffs"]
    names = surface["names"]
    H = np.array([[2 * d, f], [f, 2 * e]])
    x = None
    if 2 * d > 0 and np.linalg.det(H) > 0:
        xs = np.linalg.solve(H, -np.array([b, c]))
        if np.all(np.abs(xs) <= 1.0):
            x = xs
    if x is None:
        g = np.linspace(-1, 1, 101)
        G1, G2 = np.meshgrid(g, g, indexing="ij")
        Z = a + b * G1 + c * G2 + d * G1 ** 2 + e * G2 ** 2 + f * G1 * G2
        i, j = np.unravel_index(int(np.argmin(Z)), Z.shape)
        x = np.array([G1[i, j], G2[i, j]])
    return _denorm(x, bounds, names)


def surface_eval(surface, p, bounds):
    a, b, c, d, e, f = surface["coeffs"]
    x1, x2 = _norm(p, bounds, surface["names"])
    return a + b * x1 + c * x2 + d * x1 ** 2 + e * x2 ** 2 + f * x1 * x2


# -------------------------------------------------------------------- study
class Study:
    def __init__(self, settings, config, app_log=None, on_running=None):
        self.settings = dict(settings)
        self.app_log = app_log or (lambda s: None)
        self.on_running = on_running or (lambda flag: None)
        self.cfg = self._normalise(config)
        name = pipeline.safe_name(self.cfg["name"])
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(optim_root(self.settings), "{}_{}".format(name, stamp))
        self.short = re.sub(r"[^A-Za-z0-9]", "", name)[:12] or "study"
        os.makedirs(os.path.join(self.dir, "plant"))
        os.makedirs(os.path.join(self.dir, "logs"))
        with open(os.path.join(self.dir, CONFIG_FILE), "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, default=str)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._procs = {}
        self._cand_files = {}
        self._exec = None
        self._thread = None
        self._scan_cache = (0.0, [])
        self.refs = []
        self.state = {
            "status": "created", "name": self.cfg["name"], "dir": self.dir,
            "started": None, "elapsed_s": 0, "round": 0,
            "rounds": self.cfg["design"]["rounds"], "candidates": [],
            "best": None, "surface": None, "surface_min": None, "message": "",
            "windows": [dict(w) for w in self.cfg["windows"]],
            "params": self.cfg["params"], "weights": self.cfg["weights"],
            "jobs_done": 0, "jobs_total": 0, "max_workers": self.cfg["max_workers"],
        }
        self._write_state()

    # ---------------------------------------------------------------- config
    def _normalise(self, config):
        c = copy.deepcopy(config or {})
        if not c.get("log_path") or not os.path.isfile(c["log_path"]):
            raise FileNotFoundError("log file not found: {}".format(c.get("log_path")))
        if not c.get("channel_map"):
            raise ValueError("channel_map is required")
        wins = [{"t0": float(w["t0"]), "t1": float(w["t1"])} for w in (c.get("windows") or [])]
        if not wins:
            raise ValueError("at least one window is required")
        for w in wins:
            if w["t1"] - w["t0"] < 5.0:
                raise ValueError("window {}-{} s is shorter than 5 s".format(w["t0"], w["t1"]))
        c["windows"] = wins
        params = c.get("params") or {}
        if not params:
            raise ValueError("choose at least one parameter to tune")
        bounds = {}
        for k, v in params.items():
            if k not in plant.PARAMS:
                raise KeyError("'{}' is not tunable (registry: {})".format(k, sorted(plant.PARAMS)))
            lo = float(v.get("min", plant.PARAMS[k]["min"]))
            hi = float(v.get("max", plant.PARAMS[k]["max"]))
            plant.validate_params({k: lo}, {k: (lo, hi)})
            bounds[k] = (lo, hi)
        if len(bounds) == 1:
            # the search is written for two axes; pin the other at its default
            other = [k for k in plant.PARAMS if k not in bounds][0]
            d = plant.PARAMS[other]["default"]
            bounds[other] = (d, d)
            c.setdefault("notes", []).append("{} pinned at {}".format(other, d))
        c["params"] = {k: {"min": lo, "max": hi} for k, (lo, hi) in bounds.items()}
        c["weights"] = {k: float(v) for k, v in (c.get("weights") or logmatch.DEFAULT_WEIGHTS).items()}
        c["max_workers"] = int(c.get("max_workers") or self.settings.get("optim_max_workers") or 6)
        c["step_s"] = float(c.get("step_s") or replay.DEFAULT_STEP_S)
        c["hmax"] = float(c.get("hmax") or replay.DEFAULT_HMAX)
        c["smoothing_hz"] = float(c.get("smoothing_hz") or replay.DEFAULT_SMOOTHING_HZ)
        c["settle_s"] = float(c.get("settle_s", 3.0))
        c["max_lag_s"] = float(c.get("max_lag_s", 2.0))
        c["pedal_mode"] = c.get("pedal_mode") or "physical"
        c["timeout_min"] = float(c.get("timeout_min") or 90.0)
        c["keep_plt"] = c.get("keep_plt") or "best"
        d = dict(DEFAULT_DESIGN)
        d.update(c.get("design") or {})
        d["grid"] = max(2, int(d["grid"]))
        d["rounds"] = max(1, int(d["rounds"]))
        c["design"] = d
        c["name"] = c.get("name") or "roadload"
        c["pack_voltage"] = float(c.get("pack_voltage") or self.settings.get("pack_voltage") or 380.0)
        base = plant.base_files(self.settings, c.get("base_payload"))
        c["tire_src"] = c.get("tire_src") or base["tire"]
        c["aero_src"] = c.get("aero_src") or base["aero"]
        if not (c["tire_src"] and os.path.isfile(c["tire_src"])):
            raise FileNotFoundError("tyre file not found: {}".format(c["tire_src"]))
        if not (c["aero_src"] and os.path.isfile(c["aero_src"])):
            raise FileNotFoundError("aero file not found: {}".format(c["aero_src"]))
        payload = copy.deepcopy(c.get("base_payload") or {})
        payload["deck_default"] = False
        payload.setdefault("spec", {})
        c["base_payload"] = payload
        return c

    # ----------------------------------------------------------------- state
    def _write_state(self):
        with self._lock:
            if self.state.get("started"):
                self.state["elapsed_s"] = int(time.time() - self.state["started"])
            tmp = os.path.join(self.dir, STATE_FILE + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, indent=1, default=str)
            os.replace(tmp, os.path.join(self.dir, STATE_FILE))

    def _note(self, msg):
        with self._lock:
            self.state["message"] = msg
        self.app_log("[optimizer] " + msg)
        with open(os.path.join(self.dir, "logs", "study.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + msg + "\n")

    def status(self):
        with self._lock:
            st = copy.deepcopy(self.state)
        live = self._live()
        by_dir = {os.path.normcase(r["dir"]): r for r in live}
        for cand in st["candidates"]:
            for job in cand["jobs"]:
                rec = by_dir.get(os.path.normcase(job.get("run_dir") or "~"))
                if rec and job["status"] == "running":
                    job["eta_s"], job["ram_mb"] = rec.get("eta_s"), rec.get("ram_mb")
                    job["frac"] = rec.get("frac") if rec.get("frac") is not None else job.get("frac")
        st["running"] = self.is_running()
        return st

    def _live(self):
        t, recs = self._scan_cache
        if time.time() - t < 4.0:
            return recs
        try:
            import live_procs
            recs = live_procs.scan()
        except Exception:
            recs = []
        self._scan_cache = (time.time(), recs)
        return recs

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------ run
    def start(self):
        if self._thread:
            raise RuntimeError("study already started")
        self._thread = threading.Thread(target=self._run, name="optimizer-study", daemon=True)
        self._thread.start()
        return self.dir

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def stop(self):
        self._stop.set()
        self._note("stop requested - killing running solvers")
        ex = self._exec
        if ex:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        for holder in list(self._procs.values()):
            proc = holder.get("proc")
            if proc is not None and proc.poll() is None:
                try:
                    pipeline.kill_process_tree(proc.pid)
                except Exception:
                    pass

    def _run(self):
        self.on_running(True)
        with self._lock:
            self.state["status"] = "running"
            self.state["started"] = time.time()
        try:
            self._load_reference()
            cfg, design = self.cfg, self.cfg["design"]
            bounds = {k: (v["min"], v["max"]) for k, v in cfg["params"].items()}
            span = {k: hi - lo for k, (lo, hi) in bounds.items()}
            center = None
            best_prev = None
            for r in range(1, design["rounds"] + 1):
                if self._stop.is_set():
                    break
                with self._lock:
                    self.state["round"] = r
                pts = grid_points(bounds, design["grid"], center, span if center else None)
                pts = [p for p in pts if not self._already(p)]
                self._note("round {}/{}: {} candidate(s) x {} window(s), {} solvers".format(
                    r, design["rounds"], len(pts), len(self.refs), cfg["max_workers"]))
                self._round(pts, "round {}".format(r))
                if self._stop.is_set():
                    break
                self._fit()
                best = self.state["best"]
                if best_prev is not None and best and best_prev > 0:
                    gain = (best_prev - best["score"]) / best_prev
                    if gain < design["tol"]:
                        self._note("round {} improved the best total by {:.1%} (< {:.0%}) - stopping early".format(
                            r, gain, design["tol"]))
                        break
                best_prev = best["score"] if best else None
                sm = self.state.get("surface_min")
                if sm:
                    center = sm
                    span = {k: span[k] * design["shrink"] for k in span}
            if design["confirm"] and not self._stop.is_set() and self.state.get("surface_min"):
                sm = self.state["surface_min"]
                if not self._already(sm):
                    self._note("confirmation solve at the surface minimum")
                    self._round([sm], "confirm")
                    self._fit()
            self._cleanup_plt()
            with self._lock:
                self.state["status"] = "stopped" if self._stop.is_set() else "done"
            best = self.state["best"]
            self._note("finished: {} candidate(s), best total {} at {}".format(
                len(self.state["candidates"]),
                best["score"] if best else "n/a",
                best["params"] if best else "n/a"))
        except Exception as exc:
            with self._lock:
                self.state["status"] = "failed"
            self._note("FAILED: {}: {}".format(type(exc).__name__, exc))
            with open(os.path.join(self.dir, "logs", "study.log"), "a", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        finally:
            self._write_state()
            self.on_running(False)

    def _load_reference(self):
        cfg = self.cfg
        with logmatch.Log(cfg["log_path"]) as log:
            probs = logmatch.check_map(cfg["channel_map"], log)
            if probs:
                raise ValueError("channel map: " + "; ".join(probs))
            self.refs = [logmatch.reference(log, cfg["channel_map"], w["t0"], w["t1"])
                         for w in cfg["windows"]]
        with self._lock:
            for w, ref in zip(self.state["windows"], self.refs):
                w["dur_s"] = round(float(ref["t"][-1]), 1)
                w["v0_kph"] = round(ref["v0_kph"], 1)
                w["has"] = {k: bool(v) for k, v in ref["has"].items()}
                w["notes"] = ref["notes"]
        self._note("reference loaded: {} window(s), {} s total".format(
            len(self.refs), round(sum(float(r["t"][-1]) for r in self.refs), 1)))

    def _already(self, p):
        for c in self.state["candidates"]:
            if all(abs(c["params"][k] - float(v)) < 1e-6 for k, v in p.items()):
                return True
        return False

    def _round(self, points, label):
        if not points:
            return
        with self._lock:
            start_id = len(self.state["candidates"])
            for i, p in enumerate(points):
                self.state["candidates"].append({
                    "id": start_id + i, "params": plant.full_params(p), "round": label,
                    "status": "queued", "score": None, "jobs": [
                        {"window": wi, "status": "queued", "run_dir": None, "frac": 0.0,
                         "score": None, "wall_s": None, "error": None}
                        for wi in range(len(self.refs))]})
            self.state["jobs_total"] += len(points) * len(self.refs)
        self._write_state()
        jobs = [(start_id + i, wi) for i in range(len(points)) for wi in range(len(self.refs))]
        self._exec = ThreadPoolExecutor(max_workers=self.cfg["max_workers"],
                                        thread_name_prefix="optim-solve")
        try:
            futures = {self._exec.submit(self._evaluate, cid, wi): (cid, wi) for cid, wi in jobs}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=5.0, return_when=FIRST_COMPLETED)
                for fut in done:
                    cid, wi = futures[fut]
                    try:
                        res = fut.result()
                    except Exception as exc:   # cancelled or unexpected
                        res = {"ok": False, "error": "{}: {}".format(type(exc).__name__, exc)}
                    self._job_done(cid, wi, res)
                self._write_state()
                if self._stop.is_set():
                    break
        finally:
            self._exec.shutdown(wait=not self._stop.is_set(), cancel_futures=True)
            self._exec = None
        self._score_candidates()
        self._write_state()

    def _job_done(self, cid, wi, res):
        with self._lock:
            cand = self.state["candidates"][cid]
            job = cand["jobs"][wi]
            job["status"] = "ok" if res.get("ok") else ("stopped" if self._stop.is_set() else "failed")
            job["run_dir"] = res.get("run_dir") or job.get("run_dir")
            job["score"] = res.get("score")
            job["wall_s"] = res.get("wall_s")
            job["error"] = res.get("error")
            job["frac"] = 1.0 if res.get("ok") else job.get("frac")
            self.state["jobs_done"] += 1

    def _score_candidates(self):
        with self._lock:
            for cand in self.state["candidates"]:
                if cand["status"] in ("ok", "failed", "stopped"):
                    continue
                if any(j["status"] in ("queued", "running") for j in cand["jobs"]):
                    cand["status"] = "stopped" if self._stop.is_set() else cand["status"]
                    continue
                oks = [j for j in cand["jobs"] if j["status"] == "ok" and j["score"]]
                if len(oks) == len(cand["jobs"]):
                    w = np.array([self.refs[j["window"]]["t"][-1] for j in oks], float)
                    tot = np.array([j["score"]["total"] for j in oks], float)
                    cand["score"] = round(float(np.sum(w * tot) / np.sum(w)), 5)
                    cand["status"] = "ok"
                else:
                    cand["score"] = FAIL_PENALTY
                    cand["status"] = "failed"
            ok = [c for c in self.state["candidates"] if c["status"] == "ok"]
            if ok:
                b = min(ok, key=lambda c: c["score"])
                self.state["best"] = {"id": b["id"], "params": b["params"], "score": b["score"],
                                      "jobs": [{"window": j["window"], "run_dir": j["run_dir"],
                                                "score": j["score"]} for j in b["jobs"]]}

    def _fit(self):
        """Response surface over the candidates solved so far. The total is an
        RMSE-type quantity, cone-shaped near the optimum, so the quadratic is
        fitted to its SQUARE (quadratic in the parameters when the model's
        residual is close to linear in them); the minimiser is the same."""
        bounds = {k: (v["min"], v["max"]) for k, v in self.cfg["params"].items()}
        with self._lock:
            pts = [c["params"] for c in self.state["candidates"] if c["status"] == "ok"]
            sq = [c["score"] ** 2 for c in self.state["candidates"] if c["status"] == "ok"]
        active = {k: b for k, b in bounds.items() if b[1] > b[0]}
        if len(active) < 2:
            # one axis pinned: 1-D quadratic through the active axis
            k = next(iter(active)) if active else None
            if k and len(pts) >= 3:
                x = np.array([p[k] for p in pts]); y = np.array(sq)
                c2, c1, c0 = np.polyfit(x, y, 2)
                xm = -c1 / (2 * c2) if c2 > 0 else x[int(np.argmin(y))]
                xm = float(min(max(xm, active[k][0]), active[k][1]))
                pinned = {kk: b[0] for kk, b in bounds.items() if kk != k}
                pred = max(float(np.polyval([c2, c1, c0], xm)), 0.0) ** 0.5
                with self._lock:
                    self.state["surface"] = {"coeffs": [float(c0), float(c1), float(c2)],
                                             "names": [k], "n": int(len(y)), "fits": "total^2"}
                    self.state["surface_min"] = dict(pinned, **{k: round(xm, 5)})
                    self.state["surface_min_pred"] = round(pred, 5)
            return
        surf = fit_quadratic(pts, sq, bounds)
        if surf:
            surf["fits"] = "total^2"
            smin = surface_min(surf, bounds)
            smin = plant.full_params({k: smin[k] for k in surf["names"]})
            pred = max(float(surface_eval(surf, smin, bounds)), 0.0) ** 0.5
            with self._lock:
                self.state["surface"] = surf
                self.state["surface_min"] = {k: round(v, 5) for k, v in smin.items()}
                self.state["surface_min_pred"] = round(pred, 5)

    # ------------------------------------------------------------- one job
    def _candidate_files(self, cid):
        with self._lock:
            if cid in self._cand_files:
                return self._cand_files[cid]
            params = self.state["candidates"][cid]["params"]
            files = plant.candidate_files(os.path.join(self.dir, "plant"), cid, params,
                                          self.cfg["tire_src"], self.cfg["aero_src"])
            self._cand_files[cid] = files
            self.state["candidates"][cid]["edits"] = files["edits"]
            return files

    def _evaluate(self, cid, wi):
        cfg = self.cfg
        ref = self.refs[wi]
        name = "{}_c{:02d}_w{}".format(self.short, cid, wi)
        lines = []
        state = {"saw_time": False, "fatal": None}
        holder = {"proc": None}
        t_start = time.time()

        def jlog(s):
            s = str(s)
            lines.append(s)
            if pipeline.TIME_LINE.match(s):
                state["saw_time"] = True
            elif any(p in s for p in FATAL_PATTERNS) and not state["saw_time"] and not state["fatal"]:
                state["fatal"] = time.time()
                threading.Timer(FATAL_GRACE_S, _kill_if_stuck).start()

        def _kill_if_stuck():
            if state["saw_time"]:
                return
            proc = holder.get("proc")
            if proc is not None and proc.poll() is None:
                lines.append("*** watchdog: fatal message and no time progress after {:.0f} s - killed ***".format(FATAL_GRACE_S))
                try:
                    pipeline.kill_process_tree(proc.pid)
                except Exception:
                    pass

        def _timeout():
            proc = holder.get("proc")
            if proc is not None and proc.poll() is None:
                lines.append("*** watchdog: {} min timeout - killed ***".format(cfg["timeout_min"]))
                try:
                    pipeline.kill_process_tree(proc.pid)
                except Exception:
                    pass

        def prog(frac, _text):
            with self._lock:
                self.state["candidates"][cid]["jobs"][wi]["frac"] = round(float(frac or 0.0), 3)

        with self._lock:
            self.state["candidates"][cid]["status"] = "running"
            self.state["candidates"][cid]["jobs"][wi]["status"] = "running"
        run_dir = None
        timer = threading.Timer(cfg["timeout_min"] * 60.0, _timeout)
        try:
            if self._stop.is_set():
                raise RuntimeError("stopped before start")
            files = self._candidate_files(cid)
            payload = copy.deepcopy(cfg["base_payload"])
            payload["tire_path"] = files["tire_path"]
            payload["aero_path"] = files["aero_path"]
            adf, segs = replay.replay_adf(name, ref, step_s=cfg["step_s"],
                                          pedal_mode=cfg["pedal_mode"],
                                          smoothing_hz=cfg["smoothing_hz"], hmax=cfg["hmax"])
            s = dict(self.settings)
            s["runs_dir"] = self.dir
            run_dir, deck = pipeline.prepare_run(s, name, adf, log=jlog, vehicle=payload)
            with self._lock:
                self.state["candidates"][cid]["jobs"][wi]["run_dir"] = run_dir
            for fp in (files["tire_path"], files["aero_path"]):
                try:
                    shutil.copy2(fp, os.path.join(run_dir, os.path.basename(fp)))
                except OSError:
                    pass
            self._procs[(cid, wi)] = holder
            timer.start()
            plt = pipeline.run_motionsolve(s, run_dir, deck, log=jlog, progress=prog,
                                           sim_total=replay.sim_time(segs), proc_holder=holder)
            if self._stop.is_set():
                raise RuntimeError("stopped")
            model = logmatch.model_from_plt(plt, pack_voltage=cfg["pack_voltage"], log=jlog)
            sc = logmatch.score(model, ref, cfg["weights"], cfg["settle_s"], cfg["max_lag_s"])
            jlog("score: total {} lag {} s | {}".format(
                sc["total"], sc["lag_s"],
                " | ".join("{} nrmse {} corr {}".format(k, v["nrmse"], v["corr"])
                           for k, v in sc["signals"].items())))
            return {"ok": True, "run_dir": run_dir, "plt": plt, "score": sc,
                    "wall_s": int(time.time() - t_start)}
        except Exception as exc:
            jlog("JOB FAILED: {}: {}".format(type(exc).__name__, exc))
            return {"ok": False, "run_dir": run_dir, "error": str(exc)[:300],
                    "wall_s": int(time.time() - t_start)}
        finally:
            timer.cancel()
            self._procs.pop((cid, wi), None)
            if run_dir:
                for ext in ("mrf", "abf", "h3d"):
                    for fp in glob.glob(os.path.join(run_dir, "*." + ext)):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
            try:
                with open(os.path.join(self.dir, "logs", name + ".log"), "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
            except OSError:
                pass

    def _cleanup_plt(self):
        if self.cfg["keep_plt"] != "best":
            return
        best = self.state.get("best")
        keep = {os.path.normcase(j["run_dir"]) for j in best["jobs"]} if best else set()
        n = 0
        for cand in self.state["candidates"]:
            for job in cand["jobs"]:
                rd = job.get("run_dir")
                if rd and os.path.normcase(rd) not in keep:
                    for fp in glob.glob(os.path.join(rd, "*.plt")):
                        try:
                            os.remove(fp); n += 1
                        except OSError:
                            pass
        if n:
            self._note("removed {} intermediate .plt file(s); the best candidate's are kept".format(n))


# ------------------------------------------------------------------ history
def load_state(study_dir):
    with open(os.path.join(study_dir, STATE_FILE), encoding="utf-8") as fh:
        return json.load(fh)


def load_config(study_dir):
    with open(os.path.join(study_dir, CONFIG_FILE), encoding="utf-8") as fh:
        return json.load(fh)


def list_studies(settings, limit=50):
    root = optim_root(settings)
    out = []
    for sf in sorted(glob.glob(os.path.join(root, "*", STATE_FILE)),
                     key=os.path.getmtime, reverse=True)[:limit]:
        try:
            st = load_state(os.path.dirname(sf))
        except (OSError, ValueError):
            continue
        out.append({"dir": os.path.dirname(sf), "name": st.get("name"),
                    "status": st.get("status"), "best": st.get("best"),
                    "n_candidates": len(st.get("candidates") or []),
                    "elapsed_s": st.get("elapsed_s"), "started": st.get("started"),
                    "exported": os.path.isdir(os.path.join(os.path.dirname(sf), "best"))})
    return out


# ------------------------------------------------------------------- export
def export_best(study_dir, settings, out_root=None, redact=False, log=None):
    """Convert the best candidate's runs to MF4 (SOC started where the log's
    was), collect the tuned deck + tyre + aero into <study>/best/ with a
    report and overlay figure, and copy a leaderboard-visible run into the
    real runs folder. Returns a dict of what was written."""
    log = log or (lambda s: None)
    st = load_state(study_dir)
    cfg = load_config(study_dir)
    best = st.get("best")
    if not best:
        raise RuntimeError("the study has no successful candidate to export")
    best_dir = os.path.join(study_dir, "best")
    os.makedirs(best_dir, exist_ok=True)
    from converter import convert
    spec = (cfg.get("base_payload") or {}).get("spec") or {}
    pack_kwh = float(spec.get("packKWh") or 0) or None
    with logmatch.Log(cfg["log_path"]) as lg:
        refs = [logmatch.reference(lg, cfg["channel_map"], w["t0"], w["t1"]) for w in cfg["windows"]]
    written = {"mf4": [], "deck": None, "tire": None, "aero": None, "report": None, "figure": None}
    tyre_dst = aero_dst = None
    for job in best["jobs"]:
        rd = job["run_dir"]
        ref = refs[job["window"]]
        plts = glob.glob(os.path.join(rd, "*.plt"))
        if not plts:
            log("  window {}: no .plt left in {}".format(job["window"], rd))
            continue
        soc_start = float(ref["soc"][0]) / 100.0 if ref["has"].get("soc") else spec.get("packSOCstart")
        mf4 = convert(plts[0], log=log, pack_voltage=float(cfg.get("pack_voltage") or 380.0),
                      pack_kwh=pack_kwh, soc_start=soc_start if pack_kwh else None)
        dst = os.path.join(best_dir, "window{}_{}".format(job["window"], os.path.basename(mf4)))
        shutil.copy2(mf4, dst)
        written["mf4"].append(dst)
        if written["deck"] is None:
            for xml in glob.glob(os.path.join(rd, "*.xml")):
                text = open(xml, encoding="utf-8", errors="replace").read()
                for ext, key in ((".tir", "tire"), (".aae", "aero")):
                    src = glob.glob(os.path.join(rd, "*" + ext))
                    if src:
                        dstf = os.path.join(best_dir, os.path.basename(src[0]))
                        shutil.copy2(src[0], dstf)
                        text, _n = re.subn(r'(?:[A-Za-z]:/|(?:\.\./)+)[^";\r\n]+?\.' + re.escape(ext[1:]),
                                           dstf.replace("\\", "/"), text, flags=re.I)
                        written[key] = dstf
                deck_dst = os.path.join(best_dir, "{}_tuned.xml".format(pipeline.safe_name(st["name"])))
                open(deck_dst, "w", encoding="utf-8").write(text)
                written["deck"] = deck_dst
                for extra in glob.glob(os.path.join(rd, "*.adf")) + glob.glob(os.path.join(rd, "vehicle.json")) \
                        + glob.glob(os.path.join(rd, "*.nam")):
                    shutil.copy2(extra, os.path.join(best_dir, os.path.basename(extra)))
    written["report"] = _write_report(best_dir, st, cfg, best)
    try:
        written["figure"] = _overlay_figure(best_dir, st, cfg, best, refs, redact=redact)
    except Exception as exc:
        log("  overlay figure skipped: {}".format(exc))
    out_root = out_root or settings.get("runs_dir")
    if out_root and written["mf4"]:
        exp = os.path.join(out_root, "{}_best_{}".format(pipeline.safe_name(st["name"]),
                                                       time.strftime("%Y%m%d_%H%M%S")))
        os.makedirs(exp, exist_ok=True)
        for f in written["mf4"] + [written["deck"], written["tire"], written["aero"],
                                   written["report"], written["figure"]]:
            if f and os.path.isfile(f):
                shutil.copy2(f, os.path.join(exp, os.path.basename(f)))
        vj = os.path.join(best_dir, "vehicle.json")
        if os.path.isfile(vj):
            shutil.copy2(vj, os.path.join(exp, "vehicle.json"))
        written["export_dir"] = exp
    written["best_dir"] = best_dir
    return written


def _write_report(best_dir, st, cfg, best):
    lines = ["# Optimizer study: {}".format(st["name"]), "",
             "Study folder: `{}`".format(st["dir"]),
             "Status: {} after {} s, {} candidate(s), {} job(s)".format(
                 st.get("status"), st.get("elapsed_s"), len(st.get("candidates") or []), st.get("jobs_done")),
             "", "## Tuned parameters (scales on the base tyre / aero files)", ""]
    for k, v in best["params"].items():
        lines.append("- {}: {:.4f}  ({})".format(k, v, plant.PARAMS[k]["label"]))
    edits = next((c.get("edits") for c in st["candidates"] if c["id"] == best["id"]), None)
    if edits:
        lines.append("- tyre LMY: base {} -> {} ; aero Cd table rows scaled: {}".format(
            edits["lmy"]["base"], round(edits["lmy"]["value"], 5), edits["aero"]["rows"]))
    lines += ["", "Objective weights: {}".format(cfg["weights"]),
              "Best weighted total (normalised RMSE): {}".format(best["score"]), ""]
    if st.get("surface"):
        lines += ["Response surface: {} points, R2 {}; predicted minimum {} (pred. total {})".format(
            st["surface"].get("n"), st["surface"].get("r2"), st.get("surface_min"),
            st.get("surface_min_pred")), ""]
    lines += ["## Per window", ""]
    for job in best["jobs"]:
        sc = job["score"] or {}
        w = cfg["windows"][job["window"]]
        lines.append("### Window {}: {} - {} s of the log  (lag {} s, scored span {} s)".format(
            job["window"], w["t0"], w["t1"], sc.get("lag_s"), sc.get("span_s")))
        lines.append("")
        lines.append("| signal | RMSE | nRMSE | corr | model mean | log mean | weight |")
        lines.append("|---|---|---|---|---|---|---|")
        for role, s in (sc.get("signals") or {}).items():
            lines.append("| {} [{}] | {} | {} | {} | {} | {} | {} |".format(
                role, s["unit"], s["rmse"], s["nrmse"], s["corr"], s["mean_model"], s["mean_ref"], s["weight"]))
        if sc.get("soc_drop"):
            lines.append("")
            lines.append("SOC drop over the window: model {} %, log {} %".format(
                sc["soc_drop"]["model"], sc["soc_drop"]["ref"]))
        for n in sc.get("notes") or []:
            lines.append("- note: " + n)
        lines.append("")
    lines += ["## All candidates", "", "| id | round | " + " | ".join(sorted(best["params"])) + " | total | status |",
              "|---|---|" + "---|" * len(best["params"]) + "---|---|"]
    for c in st["candidates"]:
        lines.append("| {} | {} | {} | {} | {} |".format(
            c["id"], c["round"], " | ".join("{:.4f}".format(c["params"][k]) for k in sorted(best["params"])),
            c["score"], c["status"]))
    path = os.path.join(best_dir, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _overlay_figure(best_dir, st, cfg, best, refs, redact=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    roles = [("speed", "vehicle speed [km/h]"), ("torque_front", "front motor torque [Nm]"),
             ("torque_rear", "rear motor torque [Nm]"), ("pack_power", "pack power [kW]"),
             ("pedal", "pedal [%]")]
    jobs = [j for j in best["jobs"] if j.get("run_dir")]
    fig, axes = plt.subplots(len(roles), len(jobs), figsize=(6 * len(jobs), 2.6 * len(roles)),
                             squeeze=False, sharex="col")
    for col, job in enumerate(jobs):
        ref = refs[job["window"]]
        mf4s = glob.glob(os.path.join(best_dir, "window{}_*.mf4".format(job["window"])))
        model = logmatch.model_from_mf4(mf4s[0]) if mf4s else None
        lag = (job.get("score") or {}).get("lag_s", 0.0) or 0.0
        for row, (role, ylabel) in enumerate(roles):
            ax = axes[row][col]
            if ref["has"].get(role):
                ax.plot(ref["t"] + lag, ref[role], color="#444", lw=1.0, label="log")
            if model is not None and model["has"].get(role):
                ax.plot(model["t"], model[role], color="#d9480f", lw=1.0, label="model (tuned)")
            ax.set_ylabel(ylabel, fontsize=8)
            ax.grid(alpha=0.3)
            if row == 0:
                ax.set_title("window {}: {}-{} s".format(job["window"], cfg["windows"][job["window"]]["t0"],
                                                           cfg["windows"][job["window"]]["t1"]), fontsize=9)
                ax.legend(fontsize=7, loc="upper right")
            if redact:
                ax.set_yticklabels([]); ax.set_xticklabels([])
        axes[-1][col].set_xlabel("time from window start [s]", fontsize=8)
    fig.suptitle("{}: {}".format(st["name"], ", ".join(
        "{} {:.3f}".format(k, v) for k, v in best["params"].items())), fontsize=10)
    fig.tight_layout()
    path = os.path.join(best_dir, "overlay{}.png".format("_redacted" if redact else ""))
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
