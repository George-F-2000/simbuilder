"""
live_procs.py
================================================================================
Find MotionSolve runs by PROCESS, not by folder.

The Live tab used to discover runs only by walking the configured scan roots
for fresh .log files, so a solve launched from a script into some other folder
(or from a second SimBuilder, or from MotionView) was invisible until the user
added its parent folder. Solving is a process, though: every live run has an
msolve.exe / mbd_d.exe on this machine, and that process knows where it is
working. So: enumerate the solver processes, recover each one's run folder
(the absolute deck path on its command line, else the process's current
directory read from its PEB - what psutil does, done here with ctypes so the
app has no new dependency), then read the folder like any other run: newest
.log -> last Time=, the .adf -> total simulated time, the .mf4 when the
converter has landed it. Everything else (Watch / Open / View MF4) is the
existing folder machinery - discovery is the only new part.

Records returned by scan():
  dir, name, via="process", pid (the busiest solver process), root_pid (the top
  of the launcher chain: cmd/tclsh/msolve - what to kill), pids, image,
  started (epoch), wall_s, ram_mb, cpu_s, sim_last, sim_total, frac, rate
  (sim s per wall s), eta_s, log, deck, mf4, live=True, done=False.

Standalone check:  python live_procs.py   -> prints what it sees right now.
================================================================================
"""
import glob
import json
import os
import re
import struct
import subprocess
import time

SOLVER_IMAGES = ("msolve.exe", "mbd_d.exe", "mbd_j.exe")
LAUNCHER_IMAGES = ("tclsh85t.exe", "tclsh.exe", "cmd.exe")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_TIME_RE = re.compile(r"Time=([\d.eE+-]+)")


# ---- process snapshot -------------------------------------------------------

def _is_launcher(name, cmd):
    c = (cmd or "").lower()
    return name in LAUNCHER_IMAGES and ("hwsolver" in c or "motionsolve" in c)


def _snapshot_psutil():
    import psutil
    rows = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline",
                                  "create_time"]):
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or [])
            if name not in SOLVER_IMAGES and not _is_launcher(name, cmd):
                continue
            cwd = None
            try:
                cwd = p.cwd()
            except Exception:
                pass
            mi = p.memory_info()
            ct = p.cpu_times()
            rows.append({"pid": p.pid, "ppid": p.info["ppid"], "name": name,
                         "cmd": cmd, "cwd": cwd,
                         "started": float(p.info["create_time"] or 0),
                         "rss": int(mi.rss),
                         "cpu_s": float(ct.user + ct.system)})
        except Exception:
            continue
    return rows


# PowerShell CIM snapshot: pid, parent, name, command line, working set, CPU
# seconds, start (unix seconds). Filtered to the solver + launcher images.
_PS = (
    "$n = '^(msolve|mbd_d|mbd_j|tclsh85t|tclsh|cmd)\\.exe$'; "
    "$r = Get-CimInstance Win32_Process | Where-Object { $_.Name -match $n } | "
    "ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; ppid = $_.ParentProcessId; "
    "name = $_.Name.ToLower(); cmd = $_.CommandLine; rss = $_.WorkingSetSize; "
    "cpu = ($_.UserModeTime + $_.KernelModeTime) / 1e7; "
    "started = $(if ($_.CreationDate) { [math]::Round(((Get-Date $_.CreationDate).ToUniversalTime() - [datetime]'1970-01-01').TotalSeconds, 2) } else { 0 }) } }; "
    "if ($r) { ConvertTo-Json -InputObject @($r) -Compress } else { '[]' }"
)


def _snapshot_cim():
    """Dependency-free snapshot through PowerShell CIM (cwd via _cwd_of)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
        capture_output=True, text=True, timeout=25,
        creationflags=_NO_WINDOW).stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    rows = []
    for d in data:
        name = (d.get("name") or "").lower()
        cmd = d.get("cmd") or ""
        if name not in SOLVER_IMAGES and not _is_launcher(name, cmd):
            continue
        rows.append({"pid": int(d["pid"]), "ppid": int(d.get("ppid") or 0),
                     "name": name, "cmd": cmd, "cwd": None,
                     "started": float(d.get("started") or 0),
                     "rss": int(d.get("rss") or 0),
                     "cpu_s": float(d.get("cpu") or 0)})
    for r in rows:
        if r["name"] in SOLVER_IMAGES:
            r["cwd"] = _cwd_of(r["pid"])
    return rows


def _cwd_of(pid):
    """Current directory of another (same-user, 64-bit) process: PEB ->
    ProcessParameters -> CurrentDirectory.DosPath. psutil's own route, in
    ctypes, so the app needs no new dependency."""
    if os.name != "nt" or struct.calcsize("P") != 8:
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        k32, nt = ctypes.windll.kernel32, ctypes.windll.ntdll
        k32.OpenProcess.restype = wt.HANDLE
        k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_size_t,
                                          ctypes.POINTER(ctypes.c_size_t)]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        nt.NtQueryInformationProcess.argtypes = [
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong)]
        h = k32.OpenProcess(0x0400 | 0x0010, False, pid)   # QUERY | VM_READ
        if not h:
            return None
        try:
            class PBI(ctypes.Structure):
                _fields_ = [("r1", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                            ("r2", ctypes.c_void_p * 2),
                            ("upid", ctypes.c_void_p), ("r3", ctypes.c_void_p)]
            pbi, rl = PBI(), ctypes.c_ulong()
            if nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi),
                                            ctypes.sizeof(pbi),
                                            ctypes.byref(rl)) != 0:
                return None

            def read(addr, n):
                buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
                if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n,
                                             ctypes.byref(got)):
                    return None
                return buf.raw[:got.value]
            pp = read(pbi.peb + 0x20, 8)                 # PEB.ProcessParameters
            if not pp:
                return None
            pp = struct.unpack("<Q", pp)[0]
            us = read(pp + 0x38, 16)                    # CurrentDirectory.DosPath
            if not us:
                return None
            length, _max, addr = struct.unpack("<HH4xQ", us)
            raw = read(addr, length) if length else b""
            s = (raw or b"").decode("utf-16-le", "replace").rstrip("\\")
            return s or None
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def snapshot():
    try:
        import psutil  # noqa: F401
    except ImportError:
        return _snapshot_cim()
    try:
        return _snapshot_psutil()
    except Exception:
        return _snapshot_cim()


# ---- run folder + progress --------------------------------------------------

_ABS_DECK = re.compile(r'"?([A-Za-z]:[^"\s]+?\.(?:xml|py|adf))"?', re.I)


def _run_dir_from(row):
    """Absolute deck path on the command line wins; else the process cwd."""
    for m in _ABS_DECK.finditer(row.get("cmd") or ""):
        p = m.group(1).replace("/", os.sep)
        if os.path.isfile(p):
            return os.path.dirname(p), os.path.basename(p)
    cwd = row.get("cwd")
    if cwd and os.path.isdir(cwd):
        m = re.search(r'([^\s"\\/]+\.xml)', row.get("cmd") or "", re.I)
        return cwd, (m.group(1) if m else None)
    return None, None


def total_sim_time(run_dir):
    """Sum of the [MANEUVERS_LIST] caps in the run's .adf (the pipeline's
    definition of 'total'), else the deck's Param_Simulation end time."""
    try:
        for adf in sorted(glob.glob(os.path.join(run_dir, "*.adf"))):
            text = open(adf, encoding="utf-8", errors="replace").read()
            block = re.search(r"\[MANEUVERS_LIST\][\s\S]*?(?=\$-|\Z)", text)
            if block:
                caps = re.findall(r"^\s*'[^']+'\s+([0-9.]+)", block.group(0),
                                  re.M)
                tot = sum(float(c) for c in caps)
                if tot:
                    return tot
        for xml in sorted(glob.glob(os.path.join(run_dir, "*.xml"))):
            with open(xml, encoding="utf-8", errors="replace") as fh:
                head = fh.read(400000)
            m = re.search(r"<Param_Simulation[^>]*?\bend\s*=\s*\"([0-9.eE+-]+)\"",
                          head)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return None


def last_sim_time(logf):
    try:
        sz = os.path.getsize(logf)
        with open(logf, "r", errors="replace") as f:
            f.seek(max(0, sz - 8192))
            vals = _TIME_RE.findall(f.read())
        return round(float(vals[-1]), 2) if vals else None
    except Exception:
        return None


def newest(run_dir, pattern):
    fs = glob.glob(os.path.join(run_dir, pattern))
    return max(fs, key=os.path.getmtime) if fs else None


def scan(now=None):
    """Live solver runs, one record per run folder (see the module doc)."""
    now = now or time.time()
    rows = snapshot()
    by_pid = {r["pid"]: r for r in rows}
    groups = {}
    for r in rows:
        if r["name"] not in SOLVER_IMAGES:
            continue
        run_dir, deck = _run_dir_from(r)
        if not run_dir:
            continue
        key = os.path.normcase(os.path.abspath(run_dir))
        g = groups.setdefault(key, {"dir": os.path.abspath(run_dir),
                                    "rows": [], "deck": deck})
        g["rows"].append(r)
        g["deck"] = g["deck"] or deck
    out = []
    for key, g in groups.items():
        rows_g = g["rows"]
        busiest = max(rows_g, key=lambda r: r["rss"])
        # walk up the launcher chain (mbd_d <- msolve <- tclsh <- cmd)
        root, seen = busiest, set()
        while root["ppid"] in by_pid and root["ppid"] not in seen:
            seen.add(root["pid"])
            root = by_pid[root["ppid"]]
        started = min([r["started"] for r in rows_g if r["started"]] or [now])
        run_dir = g["dir"]
        logf = newest(run_dir, "*.log")
        sim_last = last_sim_time(logf) if logf else None
        sim_total = total_sim_time(run_dir)
        wall = max(now - started, 1.0)
        rate = (sim_last / wall) if sim_last else None
        frac = (min(sim_last / sim_total, 1.0)
                if (sim_last and sim_total) else None)
        eta = ((sim_total - sim_last) / rate
               if (rate and sim_total and sim_last < sim_total) else None)
        deck = g["deck"] or os.path.basename(newest(run_dir, "*.xml") or "")
        out.append({
            "dir": run_dir, "name": os.path.basename(run_dir),
            "via": "process", "pid": busiest["pid"], "root_pid": root["pid"],
            "pids": sorted({r["pid"] for r in rows_g} | {root["pid"]}),
            "image": busiest["name"], "started": started,
            "wall_s": int(wall),
            "ram_mb": round(sum(r["rss"] for r in rows_g) / 1e6),
            "cpu_s": round(sum(r["cpu_s"] for r in rows_g)),
            "sim_last": sim_last, "sim_total": sim_total, "frac": frac,
            "rate": (round(rate, 4) if rate else None),
            "eta_s": (int(eta) if eta is not None else None),
            "log": logf, "deck": deck, "mf4": newest(run_dir, "*.mf4"),
            "mtime": (os.path.getmtime(logf) if logf else started),
            "age_s": (int(now - os.path.getmtime(logf)) if logf else 0),
            "live": True, "done": False,
        })
    out.sort(key=lambda r: -r["started"])
    return out


# ---- stopping ---------------------------------------------------------------

def kill_tree(pid, pids=None, log=None):
    """Kill a solver's whole launcher chain. psutil when present (snapshots the
    descendants first), else taskkill /T on the root and each known pid."""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        procs = []
        for p_id in [pid] + [x for x in (pids or []) if x != pid]:
            try:
                p = psutil.Process(p_id)
                for c in p.children(recursive=True) + [p]:
                    if c not in procs:
                        procs.append(c)
            except psutil.NoSuchProcess:
                pass
        for p in procs:
            try:
                if log:
                    log("  killing {} (pid {})".format(p.name(), p.pid))
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=10)
        return bool(procs)
    ok = False
    for p in [pid] + [x for x in (pids or []) if x != pid]:
        try:
            r = subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"],
                               capture_output=True, text=True, timeout=20,
                               creationflags=_NO_WINDOW)
            if log:
                log("  taskkill {}: {}".format(
                    p, (r.stdout or r.stderr).strip()[:120]))
            ok = ok or r.returncode == 0
        except Exception as exc:
            if log:
                log("  taskkill {} failed: {}".format(p, exc))
    return ok


if __name__ == "__main__":
    t0 = time.time()
    runs = scan()
    print("{} live solver run(s) in {:.1f} s".format(len(runs), time.time() - t0))
    for r in runs:
        print(json.dumps(r, indent=1, default=str))
