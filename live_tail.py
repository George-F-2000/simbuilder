"""
live_tail.py
================================================================================
Stream a MotionSolve .plt AS IT IS BEING WRITTEN, for the live "watch it solve"
viewer (CANape-style). The .plt is ASCII with the channel directory at the HEAD
and one appended block per timestep, so it can be tailed like a growing log:
read the header+directory once, then decode appended data tokens into frames and
hand batched frames to a callback for the UI.

Design notes
------------
* The risky part is decoding a file mid-write: a read can land in the middle of a
  number ("12.3" now, "45" next read). `TokenDecoder` holds an incomplete
  trailing token between reads and only emits COMPLETE (1 + n_req*6)-token
  blocks - byte-for-byte the same grouping plt_reader.read_plt uses, so a live
  frame equals the final file's row exactly (verified in __main__).
* Channel labels come from the .nam companion (already written at export), via
  plt_reader.read_nam - same names the offline parser/viewer use.

Standalone test:  python live_tail.py <run_dir_or_plt>
  replays a FINISHED file through the streaming path in randomly-sized chunks and
  asserts the streamed frames match plt_reader.read_plt value-for-value.

*** KNOWN LIMITATION (verified 2026-07-20, against a live 96 km/h solve) ***
For the LYRIQ deck, MotionSolve does NOT flush the .plt incrementally during a
run - it buffers channel data to the binary .mrf (the growing working file) and
only writes the ASCII .plt/.abf at run END (deck ResOutput plt_file=TRUE). So at
t=20s of a 34s run the .plt is 0 bytes while the .mrf is ~17 MB and climbing.
CONSEQUENCE: this tailer streams correctly, but for THIS deck it only "streams"
a FINISHED run (or one that flushed the .plt) - it cannot show an in-progress
solve, because the live data isn't in the .plt yet. (The earlier "partial .plt"
sightings were FAILED runs flushed at abort, which misled the original design.)
TO MAKE IT TRULY LIVE: parse the growing binary .mrf, or add a MotionSolve output
user-subroutine that emits channels per step (the Tier-3 path). Until then the
Live tab is best used to replay a completed run, or as a live SOLVER-VITALS view
(Time/H/Order/Phi are streamed live in the solver stdout - see run_motionsolve).
================================================================================
"""

import glob
import os
import re
import subprocess
import threading
import time

import numpy as np

import plt_reader


# ---- live SOLVER VITALS from any run's .log (works for external runs) ------
# MotionSolve writes the same "Time=..; Order=..; H=.. [Max Phi=..]" step lines
# to the run's .log as to stdout, live. So we can tail ANY run's .log - even one
# the app did not launch - for the solver progress/health view.

_VITALS_RE = re.compile(
    r"Time=([\d.eE+-]+).*?Order=(\d+).*?H=([\d.eE+-]+).*?Max Phi=([\d.eE+-]+)")
_SOLVER_IMAGES = ("mbd_d.exe", "mbd_j.exe", "msolve.exe")


def find_log(run_dir):
    logs = glob.glob(os.path.join(run_dir, "*.log"))
    return max(logs, key=os.path.getmtime) if logs else None


def solver_running():
    """True if a MotionSolve solver process is running (Windows tasklist)."""
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
            timeout=6, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ).stdout.lower()
        return any(img in out for img in _SOLVER_IMAGES)
    except Exception:
        return False


def scan_runs(roots, max_age_h=48, max_depth=3):
    """Find run folders under `roots` that hold a MotionSolve .log. Classify a
    run as LIVE (log written in the last ~12 s and no finished .plt yet) or
    DONE. Returns newest-first, each: {dir, name, mtime, age_s, live, done,
    sim_last}."""
    now = time.time()
    seen, runs = set(), []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root = os.path.abspath(root)
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirs, files in os.walk(root):
            if dirpath.count(os.sep) - base_depth > max_depth:
                dirs[:] = []
                continue
            logs = [f for f in files if f.lower().endswith(".log")]
            if not logs or dirpath in seen:
                continue
            lg = max((os.path.join(dirpath, f) for f in logs),
                     key=os.path.getmtime)
            age = now - os.path.getmtime(lg)
            if age > max_age_h * 3600:
                continue
            seen.add(dirpath)
            plt = find_plt(dirpath)
            done = bool(plt and os.path.getsize(plt) > 2000)
            runs.append({
                "dir": dirpath, "name": os.path.basename(dirpath),
                "mtime": os.path.getmtime(lg), "age_s": int(age),
                "live": (age < 12 and not done), "done": done,
                "sim_last": _last_sim_time(lg),
            })
    runs.sort(key=lambda r: -r["mtime"])
    return runs[:50]


def _last_sim_time(logf):
    """Cheap read of the last Time= value in a log (tail a few KB)."""
    try:
        sz = os.path.getsize(logf)
        with open(logf, "r", errors="replace") as f:
            f.seek(max(0, sz - 8192))
            tail = f.read()
        vals = _VITALS_RE.findall(tail)
        return round(float(vals[-1][0]), 2) if vals else None
    except Exception:
        return None


class LogTailer(threading.Thread):
    """Tail a run's .log for solver vitals and fire on_done when the run
    completes (a stable, non-growing .plt appears, or the app flags it done).
    `get_dir()` returns the run folder (or None while still resolving) - so the
    same tailer serves app-launched runs (dir via holder) and scanned external
    runs (fixed dir). on_vitals(list-of-{t,order,h,phi,wall})  on_done(run_dir).
    `alive()` False stops it; `external` skips the alive()-based done."""

    def __init__(self, get_dir, on_vitals, on_done, alive,
                 external=False, poll=0.4, t0=None):
        super().__init__(daemon=True)
        self.get_dir = get_dir
        self.on_vitals = on_vitals
        self.on_done = on_done
        self.alive = alive
        self.external = external
        self.poll = poll
        self.t0 = t0 or time.time()
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        lg = None
        while not self._stopped and self.alive():
            d = self.get_dir()
            if d:
                lg = find_log(d)
                if lg and os.path.isfile(lg):
                    break
            time.sleep(self.poll)
        if not lg:
            return
        pos, buf, pending, last_push = 0, "", [], 0.0
        plt_seen_size, stable = None, 0
        while not self._stopped:
            running = self.alive()
            try:
                with open(lg, "r", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except OSError:
                chunk = ""
            buf += chunk
            parts = buf.split("\n")
            buf = parts.pop()
            for ln in parts:
                m = _VITALS_RE.search(ln)
                if m:
                    pending.append({
                        "t": float(m.group(1)), "order": int(m.group(2)),
                        "h": float(m.group(3)), "phi": float(m.group(4)),
                        "wall": round(time.time() - self.t0, 1)})
            now = time.time()
            if pending and now - last_push >= 0.2:
                try:
                    self.on_vitals(pending)
                except Exception:
                    pass
                pending, last_push = [], now
            # ---- done detection ----
            d = self.get_dir()
            plt = find_plt(d) if d else None
            if plt and os.path.getsize(plt) > 2000:
                sz = os.path.getsize(plt)
                stable = stable + 1 if sz == plt_seen_size else 0
                plt_seen_size = sz
                if stable >= 2:
                    if pending:
                        try: self.on_vitals(pending)
                        except Exception: pass
                    try: self.on_done(d)
                    except Exception: pass
                    return
            if not self.external and not running and not chunk:
                # app-launched run flagged finished and log drained
                if pending:
                    try: self.on_vitals(pending)
                    except Exception: pass
                try: self.on_done(d)
                except Exception: pass
                return
            time.sleep(self.poll)


# ---------------------------------------------------------------- header ----

def find_plt(run_dir):
    """The newest .plt in a run folder (there is normally exactly one)."""
    plts = sorted(glob.glob(os.path.join(run_dir, "*.plt")),
                  key=os.path.getmtime)
    return plts[-1] if plts else None


def read_header(plt_path):
    """Read line0/1/2 + the n_req-entry directory. Returns
    (n_req, units_system, directory, data_offset) or None if the file does not
    yet hold a COMPLETE header+directory (still being written). directory is a
    list of (request_id, normalized_name) in file/column order; data_offset is
    the byte position where the data tokens begin."""
    try:
        with open(plt_path, "r", errors="replace") as f:
            f.readline()                       # line0: "MotionSolve ... Plot File"
            f.readline()                       # line1: timestamp
            header = f.readline().split()      # line2: n_req units scale
            if len(header) < 2:
                return None
            n_req = int(header[0])
            units_system = header[1]
            directory = []
            for _ in range(n_req):
                meta = f.readline().split()
                name = f.readline()
                if not meta or name == "":     # directory not fully flushed yet
                    return None
                directory.append((int(meta[0]), plt_reader.norm(name)))
            if len(directory) != n_req:
                return None
            return n_req, units_system, directory, f.tell()
    except (ValueError, IndexError, OSError):
        return None


def build_channels(directory, nam_path):
    """Map the .plt directory + .nam into a selectable channel list. Returns
    (channels, picks) where channels is a list of
    {key, label, unit, col, slot} (col = index into directory, slot 0..5) and
    picks is a shortlist of keys worth showing by default (speed / motor /
    battery / torque), best-effort by name match."""
    try:
        nam = plt_reader.read_nam(nam_path)
    except Exception:
        nam = {}
    channels = []
    for col, (rid, dname) in enumerate(directory):
        entry = nam.get(rid)
        comps = entry["components"] if entry else {"X": 0}
        base = entry["name"] if entry else dname
        units = entry["units"] if entry else {}
        for comp, slot in sorted(comps.items(), key=lambda kv: kv[1]):
            channels.append({
                "key": "{}:{}".format(rid, slot),
                "label": "{} - {}".format(base, comp),
                "unit": units.get(comp, ""),
                "col": col, "slot": slot,
            })
    wanted = ("veloc", "speed", "motor", "batt", "torque", "current",
              "soc", "accel")
    picks = [c["key"] for c in channels
             if any(w in c["label"].lower() for w in wanted)][:12]
    return channels, picks


# ------------------------------------------------------------ decoder ----

class TokenDecoder:
    """Feed raw text chunks; get back completed (time, values[n_req,6]) frames.
    Holds a partial trailing token and partial trailing block across feeds."""

    def __init__(self, n_req):
        self.n_req = n_req
        self.per_block = 1 + n_req * 6
        self._str = ""      # possibly-incomplete trailing token text
        self._tok = []       # complete tokens not yet forming a full block

    def feed(self, chunk):
        if not chunk:
            return []
        self._str += chunk
        ends_clean = self._str[-1].isspace()
        toks = self._str.split()
        if not ends_clean and toks:
            self._str = toks.pop()     # keep incomplete last token
        else:
            self._str = ""
        self._tok.extend(toks)
        frames = []
        pb = self.per_block
        while len(self._tok) >= pb:
            block = self._tok[:pb]
            del self._tok[:pb]
            t = float(block[0])
            vals = np.asarray(block[1:], dtype=float).reshape(self.n_req, 6)
            frames.append((t, vals))
        return frames


# -------------------------------------------------------------- tailer ----

class LiveTailer(threading.Thread):
    """Watches a run folder for its .plt, reads the header, then tails data and
    pushes frames. Callbacks:
        on_init(channels, picks, units_system)
        on_frames(list of {"t": float, "vals": {key: value}})   throttled
    `alive()` should return False to stop (e.g. run finished + short drain).
    `keys` (optional) limits decoding/push to those channel keys."""

    def __init__(self, dir_holder, on_init, on_frames, alive,
                 poll=0.25, push_hz=5.0, keys=None):
        super().__init__(daemon=True)
        self.dir_holder = dir_holder
        self.on_init = on_init
        self.on_frames = on_frames
        self.alive = alive
        self.poll = poll
        self.min_push_dt = 1.0 / push_hz
        self.keys = keys
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _wait_for_header(self):
        while not self._stopped and self.alive():
            run_dir = self.dir_holder.get("dir")
            plt = find_plt(run_dir) if run_dir else None
            if plt:
                hdr = read_header(plt)
                if hdr:
                    return (plt,) + hdr
            time.sleep(self.poll)
        return None

    def run(self):
        got = self._wait_for_header()
        if not got:
            return
        plt, n_req, units_system, directory, data_offset = got
        nam = plt.rsplit(".", 1)[0] + ".nam"
        channels, picks = build_channels(directory, nam)
        # send the FULL channel list to the UI (so the user can see every signal)
        # but only STREAM values for a light default set to keep the bridge cheap
        keyset = set(self.keys) if self.keys else set(picks)
        sel = [(c["key"], c["col"], c["slot"]) for c in channels
               if c["key"] in keyset]
        try:
            self.on_init(channels, picks, units_system)
        except Exception:
            pass

        dec = TokenDecoder(n_req)
        pos = data_offset
        pending = []
        last_push = 0.0
        drain_until = None
        while not self._stopped:
            running = self.alive()
            if not running and drain_until is None:
                drain_until = time.time() + 1.0   # final flush window
            try:
                with open(plt, "r", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except OSError:
                chunk = ""
            for t, vals in dec.feed(chunk):
                pending.append({"t": t,
                                "vals": {k: float(vals[col, slot])
                                         for k, col, slot in sel}})
            now = time.time()
            if pending and (now - last_push) >= self.min_push_dt:
                try:
                    self.on_frames(pending)
                except Exception:
                    pass
                pending = []
                last_push = now
            if not running and drain_until and now >= drain_until and not chunk:
                if pending:
                    try:
                        self.on_frames(pending)
                    except Exception:
                        pass
                break
            time.sleep(self.poll)


# ---------------------------------------------------------------- test ----

def _selftest(target):
    """Replay a finished .plt through the streaming decoder in random chunks and
    assert it reproduces plt_reader.read_plt exactly."""
    import random
    plt = target if target.endswith(".plt") else find_plt(target)
    assert plt, "no .plt found in " + target
    hdr = read_header(plt)
    assert hdr, "header not readable"
    n_req, units_system, directory, data_offset = hdr
    print("header OK: n_req={} units={} data_offset={}".format(
        n_req, units_system, data_offset))

    # ground truth
    times, data, gdir, gunits = plt_reader.read_plt(plt)
    print("ground truth: {} timesteps x {} requests".format(
        len(times), data.shape[1]))

    # stream the data section in random-sized chunks
    with open(plt, "r", errors="replace") as f:
        f.seek(data_offset)
        data_text = f.read()
    dec = TokenDecoder(n_req)
    i, N = 0, len(data_text)
    frames = []
    while i < N:
        step = random.randint(1, 4096)
        frames.extend(dec.feed(data_text[i:i + step]))
        i += step
    print("streamed frames: {}".format(len(frames)))
    assert len(frames) == len(times), \
        "frame count {} != {}".format(len(frames), len(times))
    max_t_err = max(abs(f[0] - times[k]) for k, f in enumerate(frames))
    max_v_err = max(float(np.max(np.abs(f[1] - data[k])))
                    for k, f in enumerate(frames))
    print("max time err = {:.3e}   max value err = {:.3e}"
          .format(max_t_err, max_v_err))
    assert max_t_err == 0 and max_v_err == 0, "streamed values differ!"

    nam = plt.rsplit(".", 1)[0] + ".nam"
    channels, picks = build_channels(directory, nam)
    print("channels: {}   default picks: {}".format(len(channels), len(picks)))
    for c in channels[:6]:
        print("   {:>7} {:<44} [{}]".format(c["key"], c["label"][:44],
                                            c["unit"]))
    print("PASS - streaming decoder matches plt_reader value-for-value.")


if __name__ == "__main__":
    import sys
    _selftest(sys.argv[1] if len(sys.argv) > 1 else ".")
