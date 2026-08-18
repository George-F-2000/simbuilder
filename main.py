"""
main.py
================================================================================
The unified app: Scenario Builder + MotionSolve pipeline + PLT->MF4
converter + MF4 viewer, all inside ONE executable.

One exe, multiple processes (the Chrome pattern). pywebview (the builder
window) and tkinter (viewer / converter windows) each need to own a GUI
event loop, so instead of fighting over one process they get one each: the
exe dispatches on its own command line and relaunches ITSELF for the
tkinter tools.

    MotionSolvePipeline.exe                    -> builder + pipeline window
    MotionSolvePipeline.exe --viewer [f.mf4..] -> MF4 viewer (tkinter)
    MotionSolvePipeline.exe --plt-converter    -> PLT->MF4 converter (tkinter)

Where the tools come from:
  - viewer:    imported from ..\\CSV to MDF Converter\\csv-to-mf4-app\\viewer.py
               (the canonical copy - all viewer features arrive automatically)
  - converter: plt_gui.py (copy of plt-to-mf4-app\\app.py)

The pipeline (Api below) streams into the page via evaluate_js and supports
stopping a run: motionsolve.bat spawns a small process tree (tclsh ->
msolve), so Stop uses `taskkill /T /F` on the root pid to take out the
whole tree.
================================================================================
"""

import json
import os
import re
import time
import subprocess
import sys
import threading

BASE = (os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))

# running from source: make the canonical viewer module importable.
# NOTE: must point at mf4-viewer-app (viewer.py only) - pointing at a
# folder that also has a converter.py would shadow this app's converter.
if not getattr(sys, "frozen", False):
    sys.path.append(os.path.normpath(os.path.join(
        BASE, "..", "CSV to MDF Converter", "mf4-viewer-app")))


def self_command(*args):
    """Command line that re-launches this same app with different args."""
    if getattr(sys, "frozen", False):
        return [sys.executable] + list(args)
    return [sys.executable, os.path.abspath(__file__)] + list(args)


# ----------------------------------------------------------------------------
#  Pipeline window (default mode)
# ----------------------------------------------------------------------------

def file_filter(spec):
    """pywebview >= 5 validates file filters strictly ('Name (*.ext)') and
    raises on the old WinForms-style 'Name (*.ext)|*.ext' - which kills the
    dialog silently (the JS promise rejects, no popup). Accept both by
    dropping the pipe tail."""
    return spec.split("|")[0].strip()


def web_index():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "web", "index.html")
    return os.path.join(BASE, "web", "index.html")   # in-repo since the move


def _vehicle_prefix():
    try:
        import json as _vj, os as _vo
        _c = _vj.load(open(_vo.path.join(_vo.path.dirname(_vo.path.abspath(__file__)), 'vehicle_local.json')))
        return _c.get('run_prefix', 'RUN_')
    except Exception:
        return 'RUN_'

def _vehicle_name():
    try:
        import json as _vj, os as _vo
        _c = _vj.load(open(_vo.path.join(_vo.path.dirname(_vo.path.abspath(__file__)), 'vehicle_local.json')))
        return _c.get('vehicle_name', 'demo_vehicle')
    except Exception:
        return 'demo_vehicle'


class Api:
    def __init__(self):
        import pipeline
        self.pipeline = pipeline
        self.settings = pipeline.load_settings()
        self.running = False
        self.stop_requested = False
        self.proc_holder = {"proc": None}
        self.dir_holder = {"dir": None}
        self._tailer = None
        self.last_run_dir = None
        self.last_mf4 = None

    # ---- pushed to the page -------------------------------------------------

    def _js(self, call):
        import webview
        try:
            webview.windows[0].evaluate_js(call)
        except Exception:
            pass   # window closing mid-run

    def _log(self, line):
        self._js("msPipe.log({})".format(json.dumps(str(line))))

    def _status(self, text):
        self._js("msPipe.status({})".format(json.dumps(text)))

    def _progress(self, fraction, text):
        self._js("msPipe.progress({}, {})".format(
            json.dumps(fraction), json.dumps(text)))

    # ---- live "watch it solve" viewer (tails the growing .plt) --------------

    def _live_init(self, channels, picks, units):
        self._js("msPipe.liveInit({}, {}, {})".format(
            json.dumps(channels), json.dumps(picks), json.dumps(units)))

    def _live_frames(self, frames):
        self._js("msPipe.liveFrame({})".format(json.dumps(frames)))

    def _live_vitals(self, batch):
        self._js("msPipe.liveVitalsBatch({})".format(json.dumps(batch)))

    def _live_status(self, text, state):
        self._js("msPipe.liveStatus({}, {})".format(
            json.dumps(text), json.dumps(state)))

    def _attach(self, get_dir, external=False, t0=None):
        """Attach the Live tab to a run: tail its .log for solver vitals, and
        load channels from the .plt when it finishes. Works for app-launched
        runs (dir via holder) and scanned external runs (fixed dir)."""
        self._stop_live()
        try:
            import live_tail
            self._js("msPipe.liveReset()")

            def _done(run_dir):
                self._live_status("● Run finished — loading channels…",
                                  "done")
                self._load_final_channels(run_dir)

            self._tailer = live_tail.LogTailer(
                get_dir, self._live_vitals, _done,
                alive=lambda: (external or
                               (self.running and not self.stop_requested)),
                external=external, t0=t0)
            self._tailer.start()
        except Exception:
            self._tailer = None

    def _start_live(self):
        """Auto-attach the Live tab to the run the app is launching."""
        self._run_t0 = time.time()
        self._attach(lambda: self.dir_holder.get("dir"), external=False,
                     t0=self._run_t0)

    def _stop_live(self):
        t = getattr(self, "_tailer", None)
        self._tailer = None
        if t:
            try:
                t.stop()
            except Exception:
                pass

    # ---- called from the page: scan for / attach to ANY run -----------------

    def _scan_roots(self):
        roots = [self.settings.get("runs_dir")]
        roots += self.settings.get("scan_roots", [])
        return [r for r in roots if r]

    def scan_runs(self):
        """List MotionSolve runs (live + recent) found under the scan roots."""
        try:
            import live_tail
            return {"ok": True, "runs": live_tail.scan_runs(self._scan_roots()),
                    "solver_running": live_tail.solver_running(),
                    "roots": self._scan_roots()}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "runs": []}

    def attach_run(self, run_dir):
        """Attach the Live tab to an external run folder the user picked."""
        if not run_dir or not os.path.isdir(run_dir):
            return {"ok": False, "error": "not a folder"}
        self._attach(lambda d=run_dir: d, external=True)
        return {"ok": True, "dir": run_dir}

    def add_scan_folder(self):
        """Let the user add a folder to scan for runs (persisted in settings)."""
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            roots = self.settings.get("scan_roots", [])
            if result[0] not in roots:
                roots.append(result[0])
                self.settings["scan_roots"] = roots
                self.pipeline.save_settings(self.settings)
        return self.scan_runs()

    def _load_final_channels(self, run_dir):
        """When a run finishes, the .plt exists — read it and push the channels
        into the Live tab (downsampled). Best-effort; never breaks a run."""
        try:
            import live_tail
            import numpy as np
            plt = live_tail.find_plt(run_dir)
            if not plt:
                return
            hdr = live_tail.read_header(plt)
            if not hdr:
                return
            n_req, units, directory, _off = hdr
            nam = plt.rsplit(".", 1)[0] + ".nam"
            channels, picks = live_tail.build_channels(directory, nam)
            times, data, _dir, _u = self.pipeline_plt_read(plt)
            step = max(1, len(times) // 400)
            idx = range(0, len(times), step)
            sel = [c for c in channels if c["key"] in set(picks)]
            self._js("msPipe.liveInit({}, {}, {})".format(
                json.dumps(channels), json.dumps(picks), json.dumps(units)))
            frames = [{"t": round(float(times[i]), 3),
                       "vals": {c["key"]: float(data[i, c["col"], c["slot"]])
                                for c in sel}} for i in idx]
            for k in range(0, len(frames), 120):
                self._js("msPipe.liveFrame({})".format(
                    json.dumps(frames[k:k + 120])))
        except Exception:
            pass

    def pipeline_plt_read(self, plt):
        import plt_reader
        return plt_reader.read_plt(plt)

    # ---- called from the page -----------------------------------------------

    def get_state(self):
        return {
            "settings": self.settings,
            "running": self.running,
            "deck_ok": os.path.isfile(self.settings["deck"]),
            "motionsolve_ok": os.path.isfile(self.settings["motionsolve"]),
            "deck_info": self.pipeline.deck_info(self.settings),
        }

    def pick_deck(self):
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("MotionSolve deck (*.xml)", "All files (*.*)"))
        if result:
            self.settings["deck"] = result[0]
            self.pipeline.save_settings(self.settings)
        return self.get_state()

    def pick_runs_dir(self):
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            self.settings["runs_dir"] = result[0]
            self.pipeline.save_settings(self.settings)
        return self.get_state()

    def set_voltage(self, volts):
        try:
            self.settings["pack_voltage"] = float(volts)
            self.pipeline.save_settings(self.settings)
        except (TypeError, ValueError):
            pass
        return self.get_state()

    def pick_file(self, filter_spec):
        """Generic native open dialog; filter like 'Tire (*.tir)|*.tir'.
        Returns the chosen path or None."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=(file_filter(filter_spec), "All files (*.*)"))
        return result[0] if result else None

    def run_scenario(self, scenario_name, adf_text, vehicle=None):
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        if not adf_text or not adf_text.strip():
            return {"ok": False, "error": "The .adf output is empty."}
        if vehicle and vehicle.get("pack_voltage"):
            self.set_voltage(vehicle["pack_voltage"])
        self.running = True
        self.stop_requested = False
        threading.Thread(target=self._worker,
                         args=(scenario_name, adf_text, vehicle),
                         daemon=True).start()
        return {"ok": True}

    def import_drive_pick(self):
        """Pick a logged MF4 (the real car) and list its channels for the
        importer's channel-mapping UI."""
        import webview
        import drive_import
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Measurement (*.mf4;*.mdf)", "All files (*.*)"))
        if not result:
            return {"ok": False}
        path = result[0]
        try:
            return {"ok": True, "path": path,
                    "channels": drive_import.list_channels(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def import_drive_build(self, cfg):
        """Extract the drive per the channel mapping and build the scenario
        (ADF, plus a DDF companion when a path source is chosen). Stored as
        pending until run_imported()."""
        import drive_import
        try:
            d = drive_import.extract_drive(cfg["path"], cfg)
            name = re.sub(r"[^\w\-]+", "_",
                          cfg.get("name") or "RealDrive") or "RealDrive"
            # DDF path-following is EXPERIMENTAL: validated ADF/DDF grammar
            # (from Altair's own Snet_path example) is read and instantiated
            # by the driver, but in this deck the steering follows it with
            # zero output and the run terminates early - confirmed even with
            # the proven stock doublelane ADF surgically re-pointed at a DDF.
            # Default: the runnable scenario is the (proven) speed follower;
            # the path still powers the travel-map preview.
            if d["x"] is not None and cfg.get("experimental_ddf"):
                ddf_name = name + ".ddf"
                aux = {ddf_name: drive_import.build_ddf(
                    name, d["t"], d["v_ms"], d["x"], d["y"])}
                adf = drive_import.build_path_adf(name, ddf_name,
                                                  d["t"], d["v_ms"])
            else:
                aux = {}
                adf = drive_import.build_speed_adf(name, d["t"], d["v_ms"])
            self.pending_import = {"name": name, "adf": adf, "aux": aux,
                                   "src": cfg["path"]}

            # downsampled preview for the travel visualizer (≤600 points)
            import numpy as np
            t, v = d["t"], d["v_ms"]
            step = max(1, len(t) // 600)
            prev = {"v_kph": [round(float(x) * 3.6, 1) for x in v[::step]]}
            if d["x"] is not None:
                prev["x"] = [round(float(x), 1) for x in d["x"][::step]]
                prev["y"] = [round(float(x), 1) for x in d["y"][::step]]
            else:
                # no path: a straight ribbon along cumulative distance
                s = np.concatenate([[0.0], np.cumsum(
                    0.5 * (v[1:] + v[:-1]) * np.diff(t))])
                prev["x"] = [round(float(x), 1) for x in s[::step]]
                prev["y"] = [0.0] * len(prev["x"])
            return {"ok": True, "stats": d["stats"], "preview": prev}
        except Exception as exc:
            return {"ok": False, "error": "{}: {}".format(
                type(exc).__name__, exc)}

    def run_imported(self, vehicle=None):
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        pend = getattr(self, "pending_import", None)
        if not pend:
            return {"ok": False, "error": "Import a drive first."}
        self.running = True
        self.stop_requested = False
        if vehicle and vehicle.get("pack_voltage"):
            self.set_voltage(vehicle["pack_voltage"])
        threading.Thread(target=self._worker,
                         args=(pend["name"], pend["adf"], vehicle,
                               pend["aux"], pend.get("src")),
                         daemon=True).start()
        return {"ok": True}

    def get_results(self, force=False):
        """Scan the runs folder and return the campaign leaderboard rows."""
        import results
        rows = results.scan_runs(self.settings["runs_dir"], force=bool(force))
        return {"runs_dir": self.settings["runs_dir"], "rows": rows}

    def open_path(self, path):
        if path and os.path.exists(path):
            os.startfile(path)

    def view_mf4(self, path):
        if path and os.path.isfile(path):
            subprocess.Popen(self_command("--viewer", path))

    def export_results_csv(self):
        import csv as csvmod
        import webview
        import results
        rows = results.scan_runs(self.settings["runs_dir"])
        if not rows:
            return {"ok": False}
        dest = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG, save_filename="campaign_results.csv",
            file_types=("CSV (*.csv)",))
        if not dest:
            return {"ok": False}
        dest = dest if isinstance(dest, str) else dest[0]
        cols = ["folder", "when", "name", "vehicle", "serial", "serial_ok",
                "ems", "cycle", "duration_s", "dist_km", "energy_kwh",
                "wh_per_km", "soc_drop_pct", "track_rmse_kph", "jerk_rms",
                "chatter_per_min", "v_max_kph", "error"]
        with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
            w = csvmod.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return {"ok": True, "path": dest}

    def run_cycle(self, cycle_name, vehicle=None):
        """Run a standard drive cycle (UDDS / HWFET) as a closed-loop
        scenario - the efficiency benchmark runs for EMS comparisons."""
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        import drive_cycles
        try:
            adf = drive_cycles.build_cycle_adf(cycle_name)
        except Exception as exc:
            return {"ok": False, "error": "cycle generation failed: " + str(exc)}
        self.running = True
        self.stop_requested = False
        if vehicle and vehicle.get("pack_voltage"):
            self.set_voltage(vehicle["pack_voltage"])
        threading.Thread(target=self._worker,
                         args=(cycle_name.upper(), adf, vehicle),
                         daemon=True).start()
        return {"ok": True}

    def export_vigrade(self, vehicle=None):
        """Export the current model to a VI-grade (VI-CarRealTime / VI-DriveSim)
        bundle: a subsystem-structured vehicle XML + the portable .tir and
        powertrain FMU. Opens the output folder when done."""
        import glob as _glob
        import vigrade_export
        deck = self.settings.get("deck")
        if not deck or not os.path.isfile(deck):
            return {"ok": False, "error": "no master deck set in settings"}
        veh = vehicle or {}
        tir = veh.get("tire_path")
        aae = veh.get("aero_path")
        # newest injected powertrain FMU carries the real front-unit/rear-unit maps + EMS
        roots = [self.settings.get("runs_dir"),
                 os.path.join(os.environ.get("TEMP", ""), "demoev_runs")]
        fmus = []
        for r in roots:
            if r and os.path.isdir(r):
                fmus += _glob.glob(os.path.join(r, "**", "Motor_PMSM_dual.fmu"),
                                   recursive=True)
        fmu = max(fmus, key=os.path.getmtime) if fmus else None
        out_root = os.path.join(os.path.dirname(deck), "..", "VIgrade Export")
        try:
            out_root = self.settings.get("runs_dir") or out_root
            out = os.path.join(os.path.dirname(out_root), "VIgrade Export",
                               _vehicle_prefix() + time.strftime("%Y%m%d_%H%M%S"))
            man = vigrade_export.export_bundle(deck, out, tir, aae, fmu,
                                               name=_vehicle_name(),
                                               spec=veh.get("spec") or veh)
            try:
                os.startfile(out)
            except Exception:
                pass
            pw = man["params"]["powertrain"]["fmu"]
            return {"ok": True, "dir": out,
                    "xml": os.path.basename(man["xml"]),
                    "assets": man["assets"],
                    "mass_kg": man["params"]["body"]["total_mass_kg"],
                    "fmu_fmi": pw.get("fmi_version")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    # ---- Calibration tab ---------------------------------------------------

    def calib_state(self):
        """Knobs (with tooltip metadata), attempt history, reference status."""
        import calibration
        try:
            return calibration.get_state()
        except Exception as exc:
            return {"error": str(exc)[:160], "knobs": {}, "meta": {},
                    "history": [], "reference": {"ok": False}}

    def calib_run(self, knobs=None):
        """One calibration attempt: replay the reference window with the
        given knobs, score vs the real log, append to history. Blocking on
        purpose (the page disables the button); ~15 min."""
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        import calibration
        self.running = True
        try:
            row = calibration.run_calibration(self.settings, knobs or {},
                                              log=self._log)
            return {"ok": True, "row": row}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}
        finally:
            self.running = False


    def gym_state(self):
        """RL Gym tab: knobs, workouts, graduate history, running flag."""
        try:
            import rl_gym_bridge
            return rl_gym_bridge.state()
        except Exception as exc:
            return {"gym_ok": False, "error": str(exc)[:160], "knobs": {},
                    "workouts": {}, "history": [], "running": False}

    def gym_train(self, cfg=None):
        import rl_gym_bridge
        return rl_gym_bridge.train(cfg or {})

    def gym_rescore(self):
        import rl_gym_bridge
        return rl_gym_bridge.rescore()

    def gym_tail(self):
        import rl_gym_bridge
        return rl_gym_bridge.tail()

    def gym_stop(self):
        import rl_gym_bridge
        return rl_gym_bridge.stop()

    def run_performance(self, pct=100, vehicle=None):
        """Run the performance event: one WOT pull yielding 0-60 (1-foot
        rollout) and 50-70 mph. Metrics are computed from the MF4 and pushed
        to the page when the run finishes."""
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        import perf_event
        try:
            adf = perf_event.build_perf_adf("Performance_%d" % int(pct),
                                            int(pct))
        except Exception as exc:
            return {"ok": False, "error": "perf generation failed: " + str(exc)}
        self.running = True
        self.stop_requested = False
        if vehicle and vehicle.get("pack_voltage"):
            self.set_voltage(vehicle["pack_voltage"])
        threading.Thread(target=self._worker,
                         args=("Performance_%d" % int(pct), adf, vehicle),
                         kwargs={"on_mf4": self._perf_metrics},
                         daemon=True).start()
        return {"ok": True}

    def _perf_metrics(self, mf4_path):
        """Compute + push performance numbers from a finished pull's MF4."""
        try:
            import numpy as np
            from asammdf import MDF
            import perf_event
            m = MDF(mf4_path)
            t = m.get("VehicleSpeed").timestamps
            v = np.asarray(m.get("VehicleSpeed").samples[:len(t)], float)
            try:
                pb = np.asarray(m.get("BattPower").samples[:len(t)], float)
            except Exception:
                pb = None
            r = perf_event.extract_perf(t, v, pb)
            self._js("msPipe.perfResult({})".format(json.dumps(r)))
        except Exception as exc:
            self._js("msPipe.perfResult({})".format(
                json.dumps({"error": str(exc)[:160]})))

    def run_batch(self, runs, vehicle=None):
        """Run several scenarios back-to-back (the RUN AVL CYCLE button):
        each gets its own run folder + MF4; no viewer per run; the runs
        root opens at the end. STOP aborts the remaining runs."""
        if self.running:
            return {"ok": False, "error": "A run is already in progress."}
        if not runs:
            return {"ok": False, "error": "Nothing to run."}
        self.running = True
        self.stop_requested = False
        if vehicle and vehicle.get("pack_voltage"):
            self.set_voltage(vehicle["pack_voltage"])
        threading.Thread(target=self._batch_worker,
                         args=(list(runs), vehicle), daemon=True).start()
        return {"ok": True}

    def _batch_worker(self, runs, vehicle):
        n, ok, failed = len(runs), 0, 0
        try:
            for i, r in enumerate(runs):
                if self.stop_requested:
                    self._log("*** batch stopped by user - {} run(s) "
                              "skipped ***".format(n - i))
                    break
                self._log("")
                self._log("=" * 58)
                self._log("BATCH RUN {}/{}: {}".format(i + 1, n, r["name"]))
                self._log("=" * 58)
                self._status("batch {}/{}: {}".format(i + 1, n, r["name"]))

                def prog(frac, text, _base=float(i)):
                    self._progress((_base + (frac or 0.0)) / n,
                                   "run {}/{} — {}".format(i + 1, n, text))

                self.dir_holder["dir"] = None
                self._start_live()
                try:
                    run_dir, mf4 = self.pipeline.run_scenario(
                        self.settings, r["name"], r["adf"], log=self._log,
                        progress=prog, proc_holder=self.proc_holder,
                        vehicle=vehicle, viewer_launcher=False,
                        dir_holder=self.dir_holder)
                    self.last_run_dir, self.last_mf4 = run_dir, mf4
                    ok += 1
                except Exception as exc:
                    self.last_run_dir = (self.dir_holder.get("dir")
                                         or self.last_run_dir)
                    if self.stop_requested:
                        self._log("Run stopped by user.")
                        continue   # loop breaks at the top
                    failed += 1
                    self._log("ERROR in {}: {}: {} - continuing with the "
                              "next run".format(r["name"],
                                                type(exc).__name__, exc))
            self._log("")
            self._log("BATCH FINISHED: {} ok, {} failed, {} of {} attempted."
                      .format(ok, failed, ok + failed, n))
            if ok and not self.stop_requested:
                try:
                    os.startfile(self.settings["runs_dir"])
                except Exception:
                    pass
            self._status("stopped" if self.stop_requested else
                         "batch done — {} ok, {} failed".format(ok, failed))
            self._js("msPipe.done({}, {}, {})".format(
                "true" if ok and not failed and not self.stop_requested
                else "false",
                json.dumps(self.last_mf4), json.dumps(self.last_run_dir)))
        finally:
            self._stop_live()
            self.running = False

    def stop_run(self):
        """Kill the solver process tree. The worker thread then unwinds."""
        if not self.running:
            return {"ok": False}
        self.stop_requested = True
        proc = self.proc_holder.get("proc")
        if proc is not None and proc.poll() is None:
            self._log("")
            self._log("*** STOP requested - killing the solver process tree ***")
            self.pipeline.kill_process_tree(proc.pid, log=self._log)
        return {"ok": True}

    def _worker(self, scenario_name, adf_text, vehicle=None, aux_files=None,
                also_view=None, on_mf4=None):
        # also_view: extra MF4 opened alongside the result (the imported real
        # drive) so the sim overlays directly on the measurement it mimics
        # on_mf4: optional callback(mf4_path) run after a successful solve
        #         (the performance event uses it to compute + push metrics)
        extra = [also_view] if also_view and os.path.isfile(also_view) else []
        self.dir_holder["dir"] = None
        self._start_live()
        try:
            self._status("running")
            run_dir, mf4 = self.pipeline.run_scenario(
                self.settings, scenario_name, adf_text,
                log=self._log, progress=self._progress,
                proc_holder=self.proc_holder, vehicle=vehicle,
                aux_files=aux_files, dir_holder=self.dir_holder,
                viewer_launcher=lambda path: subprocess.Popen(
                    self_command("--viewer", path, *extra)))
            self.last_run_dir, self.last_mf4 = run_dir, mf4
            self._js("msPipe.done(true, {}, {})".format(
                json.dumps(mf4), json.dumps(run_dir)))
            if on_mf4:
                try:
                    on_mf4(mf4)
                except Exception:
                    pass
            self._load_final_channels(run_dir)   # fill the Live tab's channels
        except Exception as exc:
            if self.stop_requested:
                self._log("Run stopped by user.")
                self._status("stopped")
            else:
                self._log("ERROR: {}: {}".format(type(exc).__name__, exc))
            # a run that failed mid-setup still made its folder - expose it so
            # "Open run folder" works and the user can read the solver log
            self.last_run_dir = self.dir_holder.get("dir") or self.last_run_dir
            self._js("msPipe.done(false, null, {})".format(
                json.dumps(self.last_run_dir)))
        finally:
            self._stop_live()
            self.running = False

    def open_run_folder(self):
        if self.last_run_dir and os.path.isdir(self.last_run_dir):
            os.startfile(self.last_run_dir)

    def open_in_viewer(self):
        if self.last_mf4 and os.path.isfile(self.last_mf4):
            subprocess.Popen(self_command("--viewer", self.last_mf4))

    def open_runs_root(self):
        root = self.settings["runs_dir"]
        os.makedirs(root, exist_ok=True)
        os.startfile(root)

    # ---- Drive Quality (Results sub-tab) -----------------------------------

    def _dq_report(self, path):
        import drive_quality
        try:
            return drive_quality.dq_from_mf4(path)
        except Exception as exc:
            return {"file": os.path.basename(path), "error": str(exc)[:160]}

    def dq_score_file(self):
        """Score one MF4 against the EV Challenge Drive Quality targets."""
        import webview
        sel = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=(file_filter("MF4 files (*.mf4)"),))
        if not sel:
            return {"cancelled": True}
        return {"reports": [self._dq_report(p) for p in sel]}

    def dq_score_folder(self):
        """Score every MF4 in a folder (e.g. an AVL deliverable set)."""
        import webview
        sel = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not sel:
            return {"cancelled": True}
        import glob as _glob
        files = sorted(_glob.glob(os.path.join(sel[0], "*.mf4")))
        if not files:
            return {"reports": [], "error": "no MF4 files in that folder"}
        return {"reports": [self._dq_report(p) for p in files]}

    def open_viewer_app(self):
        subprocess.Popen(self_command("--viewer"))

    def open_plt_converter(self):
        subprocess.Popen(self_command("--plt-converter"))


def run_pipeline_window():
    import webview
    index = web_index()
    if not os.path.isfile(index):
        raise SystemExit("Scenario Builder web files not found: " + index)
    webview.create_window(
        "SimBuilder — MotionSolve Pipeline",
        index, js_api=Api(),
        width=1500, height=900, min_size=(1100, 700))
    # pywebview >= 4 defaults to private_mode=True: localStorage (stored
    # vehicles, scenarios, theme) silently evaporates on every app restart.
    # Persist it in a stable machine-local profile instead.
    storage = os.path.join(
        os.environ.get("LOCALAPPDATA") or BASE, "SimBuilder")
    webview.start(private_mode=False, storage_path=storage)


# ----------------------------------------------------------------------------
#  Dispatcher
# ----------------------------------------------------------------------------

def _launch_tool(mod_name):
    """Import and run a tkinter tool (viewer / plt_gui) with the two things
    that make it portable to OTHER machines:
      * MPLCONFIGDIR -> a writable temp dir, so matplotlib's font-cache build
        never fails on a locked-down machine (Windows home dir not writable).
      * a crash log + error dialog, so a failure shows the actual traceback
        instead of a bare Windows 'fault exception' box - the file can be
        sent back to diagnose a machine we can't touch.
    """
    import tempfile
    import traceback
    cfg = os.path.join(tempfile.gettempdir(), "simbuilder_mpl")
    try:
        os.makedirs(cfg, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", cfg)
    except Exception:
        pass
    try:
        mod = __import__(mod_name)
        mod.main()
    except Exception:
        tb = traceback.format_exc()
        log = os.path.join(tempfile.gettempdir(),
                           "simbuilder_%s_crash.log" % mod_name)
        try:
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(tb)
        except Exception:
            log = "(could not write log)"
        try:
            import tkinter as tk
            from tkinter import messagebox
            last = tb.strip().splitlines()[-1] if tb.strip() else "unknown error"
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "SimBuilder — %s could not open" % mod_name,
                "%s\n\nFull details saved to:\n%s\n\n(send this file to diagnose)"
                % (last, log))
            r.destroy()
        except Exception:
            pass
        raise


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--viewer":
        # hand the remaining args (mf4 paths) to the viewer, which reads
        # them from sys.argv itself
        sys.argv = [sys.argv[0]] + argv[1:]
        _launch_tool("viewer")
    elif argv and argv[0] == "--plt-converter":
        sys.argv = [sys.argv[0]] + argv[1:]
        _launch_tool("plt_gui")
    else:
        run_pipeline_window()


if __name__ == "__main__":
    main()
