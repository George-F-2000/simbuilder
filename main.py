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

def web_index():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "web", "index.html")
    return os.path.join(BASE, "web", "index.html")   # in-repo since the move


class Api:
    def __init__(self):
        import pipeline
        self.pipeline = pipeline
        self.settings = pipeline.load_settings()
        self.running = False
        self.stop_requested = False
        self.proc_holder = {"proc": None}
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
            file_types=("MotionSolve deck (*.xml)|*.xml", "All files (*.*)|*.*"))
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
            file_types=(filter_spec, "All files (*.*)|*.*"))
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

                try:
                    run_dir, mf4 = self.pipeline.run_scenario(
                        self.settings, r["name"], r["adf"], log=self._log,
                        progress=prog, proc_holder=self.proc_holder,
                        vehicle=vehicle, viewer_launcher=False)
                    self.last_run_dir, self.last_mf4 = run_dir, mf4
                    ok += 1
                except Exception as exc:
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

    def _worker(self, scenario_name, adf_text, vehicle=None):
        try:
            self._status("running")
            run_dir, mf4 = self.pipeline.run_scenario(
                self.settings, scenario_name, adf_text,
                log=self._log, progress=self._progress,
                proc_holder=self.proc_holder, vehicle=vehicle,
                viewer_launcher=lambda path: subprocess.Popen(
                    self_command("--viewer", path)))
            self.last_run_dir, self.last_mf4 = run_dir, mf4
            self._js("msPipe.done(true, {}, {})".format(
                json.dumps(mf4), json.dumps(run_dir)))
        except Exception as exc:
            if self.stop_requested:
                self._log("Run stopped by user.")
                self._status("stopped")
            else:
                self._log("ERROR: {}: {}".format(type(exc).__name__, exc))
            self._js("msPipe.done(false, null, {})".format(
                json.dumps(self.last_run_dir)))
        finally:
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
    webview.start()


# ----------------------------------------------------------------------------
#  Dispatcher
# ----------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--viewer":
        # hand the remaining args (mf4 paths) to the viewer, which reads
        # them from sys.argv itself
        sys.argv = [sys.argv[0]] + argv[1:]
        import viewer
        viewer.main()
    elif argv and argv[0] == "--plt-converter":
        sys.argv = [sys.argv[0]] + argv[1:]
        import plt_gui
        plt_gui.main()
    else:
        run_pipeline_window()


if __name__ == "__main__":
    main()
