"""
rl_gym_bridge.py — SimBuilder's RL Gym tab backend (Bible 29.9).
Launches gym training/scoring as SUBPROCESSES (training takes ~10-40 min,
so nothing blocks the UI) and serves state + live log tails to the tab.
"""
import json
import os
import shutil
import subprocess
import sys

APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
           else os.path.dirname(os.path.abspath(__file__)))
GYM = os.path.join(APP_DIR, "rl_gym")
LOG = os.path.join(GYM, "ui_session.log")

KNOB_META = {
    "c_jerk": {"label": "Jerk penalty", "default": 0.02, "step": 0.01,
        "tip": "How much the trainee is punished for LURCH (fast changes in "
               "acceleration). Turn UP for a limo, DOWN if you only care "
               "about range. Default 0.02 = the weight used for every "
               "result in the Bible."},
    "c_engage": {"label": "Axle wake-up penalty", "default": 0.05, "step": 0.05,
        "tip": "The fee for waking/sleeping the rear axle (the clunk AVL "
               "rates as 'motor activation'). Turn UP and graduates will "
               "guard the rear axle jealously."},
    "c_rate": {"label": "Torque slew penalty", "default": 0.02, "step": 0.01,
        "tip": "The fee for yanking torque around quickly. Turn UP for "
               "silk-smooth delivery at some energy cost."},
}
WORKOUTS = {
    "george_demand": "George Demand - launches, WOT passes, sprints (221 s). "
                     "The high-demand workout where the split matters most.",
    "pedal_creep": "Pedal steps + creep holds (124 s). AVL-style tip-ins at "
                   "named pedal levels plus the crawl regime. The "
                   "drivability workout.",
}

_proc = {"p": None, "kind": None}


def _python():
    """Real python even when SimBuilder runs frozen (sys.executable is the
    exe then). Same resolver chain as build_installer.bat."""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    py = shutil.which("py")
    if py:
        return [py, "-3.12"]
    cand = os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe")
    if os.path.isfile(cand):
        return [cand]
    return ["python"]


def state():
    hist_path = os.path.join(GYM, "gym_history.json")
    hist = []
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path))
        except Exception:
            hist = []
    running = _proc["p"] is not None and _proc["p"].poll() is None
    return {"knobs": KNOB_META, "workouts": WORKOUTS, "history": hist,
            "running": running, "kind": _proc["kind"],
            "gym_ok": os.path.isdir(GYM)}


def train(cfg):
    if _proc["p"] is not None and _proc["p"].poll() is None:
        return {"ok": False, "error": "a session is already running"}
    with open(os.path.join(GYM, "ui_train_config.json"), "w") as f:
        json.dump(cfg, f)
    logf = open(LOG, "w")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = env["MKL_NUM_THREADS"] = "4"
    _proc["p"] = subprocess.Popen(
        _python() + [os.path.join(GYM, "train_ui.py")], cwd=GYM,
        stdout=logf, stderr=subprocess.STDOUT, env=env, creationflags=flags)
    _proc["kind"] = "train"
    return {"ok": True}


def rescore():
    if _proc["p"] is not None and _proc["p"].poll() is None:
        return {"ok": False, "error": "a session is already running"}
    logf = open(LOG, "w")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _proc["p"] = subprocess.Popen(
        _python() + [os.path.join(GYM, "rescore_all.py")], cwd=GYM,
        stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
    _proc["kind"] = "score"
    return {"ok": True}


def tail(n=14):
    running = _proc["p"] is not None and _proc["p"].poll() is None
    lines = []
    if os.path.exists(LOG):
        try:
            with open(LOG, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-n:]
        except OSError:
            pass
    return {"running": running, "kind": _proc["kind"],
            "lines": [ln.rstrip() for ln in lines]}


def stop():
    if _proc["p"] is not None and _proc["p"].poll() is None:
        _proc["p"].kill()
        return {"ok": True}
    return {"ok": False, "error": "nothing running"}
