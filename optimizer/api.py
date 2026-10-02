"""
optimizer/api.py
================================================================================
The optimizer's surface to the page - and the COMPLETE tool list of the local
agent, which may call nothing else. Every method returns {"ok": bool, ...}
like the rest of main.Api; main.Api forwards optim_* calls here.

A single study runs at a time. While it runs, main.Api.running is held so the
Scenario / Cycle / Calibration buttons refuse to start a competing solve
(the CPU is saturated by the study's own solver pool).
================================================================================
"""
import os
import time

import numpy as np

import pipeline
from . import logmatch, plant, replay
from . import study as study_mod


def _err(exc):
    return {"ok": False, "error": "{}: {}".format(type(exc).__name__, str(exc)[:300])}


class OptimizerApi:
    def __init__(self, api):
        self.api = api            # main.Api: settings, running, _log, _js
        self.study = None

    # ----------------------------------------------------------------- state
    def optim_state(self):
        try:
            s = self.api.settings
            aliases = logmatch.load_aliases()
            return {
                "ok": True,
                "params": plant.PARAMS,
                "roles": logmatch.roles_meta(),
                "weights": logmatch.DEFAULT_WEIGHTS,
                "defaults": {"step_s": replay.DEFAULT_STEP_S, "hmax": replay.DEFAULT_HMAX,
                             "smoothing_hz": replay.DEFAULT_SMOOTHING_HZ, "settle_s": 3.0,
                             "max_lag_s": 2.0,
                             "max_workers": int(s.get("optim_max_workers") or 6),
                             "design": study_mod.DEFAULT_DESIGN,
                             "windows": {"min_len_s": 20, "max_len_s": 90, "v_floor_kph": 3.0,
                                         "brake_free": False}},
                "optim_dir": study_mod.optim_root(s),
                "base_files": plant.base_files(s),
                "deck_info": pipeline.deck_info(s),
                "history": study_mod.list_studies(s),
                "running": bool(self.study and self.study.is_running()),
                "study": self.study.status() if self.study else None,
                "aliases_file": logmatch.aliases_path(),
                "aliases_saved": len(aliases.get("by_fingerprint") or {}),
            }
        except Exception as exc:
            return _err(exc)

    # ------------------------------------------------------------------- log
    def optim_pick_log(self):
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Measurement (*.mf4;*.mdf)", "All files (*.*)"))
        if not result:
            return {"ok": False, "cancelled": True}
        return self.optim_inspect_log(result[0])

    def optim_inspect_log(self, path):
        """Channels, the resolved channel map (saved / last / suggested) and its
        problems, plus the span of the mapped speed channel."""
        try:
            with logmatch.Log(path) as log:
                cmap, source = logmatch.resolve_map(log)
                probs = logmatch.check_map(cmap, log)
                span = None
                sp = (cmap or {}).get("speed")
                if sp and sp.get("name") in log.names():
                    span = log.span(sp["name"])
                return {"ok": True, "path": path, "name": os.path.basename(path),
                        "fingerprint": log.fingerprint,
                        "channels": [{"name": c["name"], "unit": c["unit"], "samples": c["samples"]}
                                     for c in log.channels],
                        "map": cmap, "map_source": source, "problems": probs,
                        "span": span}
        except Exception as exc:
            return _err(exc)

    def optim_save_map(self, path, cmap):
        try:
            with logmatch.Log(path) as log:
                probs = logmatch.check_map(cmap, log)
                if any("required" in p or "not in this log" in p or "unit" in p for p in probs):
                    return {"ok": False, "error": "; ".join(probs), "problems": probs}
                f = logmatch.save_map(log.fingerprint, cmap, path)
            return {"ok": True, "file": f, "problems": probs}
        except Exception as exc:
            return _err(exc)

    def optim_find_windows(self, path, cmap, opts=None):
        """Candidate windows plus a downsampled trace of the whole log for the
        window picker (speed, pedal, brake; at most 1500 points)."""
        opts = opts or {}
        try:
            with logmatch.Log(path) as log:
                probs = logmatch.check_map(cmap, log)
                if probs:
                    return {"ok": False, "error": "; ".join(probs), "problems": probs}
                t0, t1 = log.span(cmap["speed"]["name"])
                ref = logmatch.reference(log, cmap, t0, t1, dt=0.05)
            wins = logmatch.find_windows(
                ref, min_len_s=float(opts.get("min_len_s", 20)),
                max_len_s=float(opts.get("max_len_s", 90)),
                v_floor_kph=float(opts.get("v_floor_kph", 3.0)),
                brake_free=bool(opts.get("brake_free", False)))
            step = max(1, len(ref["t"]) // 1500)
            prev = {"t": [round(float(x), 2) for x in (ref["t"] + ref["t0"])[::step]],
                    "speed": [round(float(x), 2) for x in ref["speed"][::step]],
                    "pedal": [round(float(x), 1) for x in ref["pedal"][::step]]}
            if ref["has"].get("brake"):
                prev["brake"] = [round(float(x), 1) for x in ref["brake"][::step]]
            return {"ok": True, "windows": wins, "preview": prev, "span": [t0, t1],
                    "has": {k: bool(v) for k, v in ref["has"].items()}, "notes": ref["notes"]}
        except Exception as exc:
            return _err(exc)

    # ----------------------------------------------------------------- study
    def optim_start(self, config):
        if self.study and self.study.is_running():
            return {"ok": False, "error": "A study is already running."}
        if self.api.running:
            return {"ok": False, "error": "A run is already in progress."}
        try:
            self.study = study_mod.Study(self.api.settings, config or {},
                                         app_log=self.api._log, on_running=self._set_running)
            d = self.study.start()
            return {"ok": True, "dir": d, "study": self.study.status()}
        except Exception as exc:
            self.study = None
            return _err(exc)

    def _set_running(self, flag):
        self.api.running = bool(flag)
        if not flag:
            try:
                st = self.study.status() if self.study else {}
                self.api._js("msPipe.optimEvent({})".format(__import__("json").dumps(
                    {"status": st.get("status"), "dir": st.get("dir")})))
            except Exception:
                pass

    def optim_status(self):
        try:
            if self.study is None:
                return {"ok": True, "study": None, "running": False}
            st = self.study.status()
            return {"ok": True, "study": st, "running": st.get("running", False)}
        except Exception as exc:
            return _err(exc)

    def optim_stop(self):
        if not (self.study and self.study.is_running()):
            return {"ok": False, "error": "no study is running"}
        try:
            self.study.stop()
            return {"ok": True}
        except Exception as exc:
            return _err(exc)

    def optim_export(self, study_dir=None, redact=False):
        """Convert the best candidate, collect the tuned model files, write
        the report and overlay figure, and copy a leaderboard-visible run into
        the runs folder. Synchronous (seconds); the page awaits it."""
        try:
            d = study_dir or (self.study.dir if self.study else None)
            if not d:
                return {"ok": False, "error": "no study to export"}
            if self.study and self.study.dir == d and self.study.is_running():
                return {"ok": False, "error": "the study is still running"}
            out = study_mod.export_best(d, self.api.settings, redact=bool(redact),
                                        log=self.api._log)
            out["ok"] = True
            return out
        except Exception as exc:
            return _err(exc)

    def optim_history(self):
        try:
            return {"ok": True, "studies": study_mod.list_studies(self.api.settings)}
        except Exception as exc:
            return _err(exc)

    def optim_study(self, study_dir):
        """A past study's state and config (for the history view)."""
        try:
            return {"ok": True, "state": study_mod.load_state(study_dir),
                    "config": study_mod.load_config(study_dir)}
        except Exception as exc:
            return _err(exc)

    def optim_overlay(self, study_dir=None, window=0):
        """Downsampled real-vs-model series of the best candidate for one
        window, read from the exported MF4 (export first)."""
        try:
            d = study_dir or (self.study.dir if self.study else None)
            st = study_mod.load_state(d)
            cfg = study_mod.load_config(d)
            best = st.get("best")
            if not best:
                return {"ok": False, "error": "no best candidate yet"}
            import glob
            mf4s = glob.glob(os.path.join(d, "best", "window{}_*.mf4".format(int(window))))
            if not mf4s:
                return {"ok": False, "error": "export the study first"}
            job = next((j for j in best["jobs"] if j["window"] == int(window)), None)
            w = cfg["windows"][int(window)]
            with logmatch.Log(cfg["log_path"]) as lg:
                ref = logmatch.reference(lg, cfg["channel_map"], w["t0"], w["t1"])
            model = logmatch.model_from_mf4(mf4s[0])
            lag = ((job or {}).get("score") or {}).get("lag_s", 0.0) or 0.0
            return {"ok": True, "window": int(window), "lag_s": lag,
                    "series": logmatch.overlay(model, ref, lag), "score": (job or {}).get("score")}
        except Exception as exc:
            return _err(exc)

    def optim_open(self, path):
        try:
            if path and os.path.exists(path):
                os.startfile(path)
                return {"ok": True}
            return {"ok": False, "error": "not found"}
        except Exception as exc:
            return _err(exc)

    def optim_set_dir(self):
        """Choose the study root (recommend a local, non-synced folder)."""
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            self.api.settings["optim_dir"] = result[0]
            pipeline.save_settings(self.api.settings)
        return self.optim_state()


TOOL_METHODS = ("optim_state", "optim_inspect_log", "optim_save_map", "optim_find_windows",
                "optim_start", "optim_status", "optim_stop", "optim_export", "optim_history",
                "optim_study", "optim_overlay")
