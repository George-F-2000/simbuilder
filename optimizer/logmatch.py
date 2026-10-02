"""
optimizer/logmatch.py
================================================================================
The real-vehicle log and the comparison against the model.

  ROLES          what the optimizer needs from a log (speed, pedal, ...) with
                 the units it accepts; the channel NAMES are never in code -
                 the user maps them once in the UI and the mapping is saved to
                 channel_aliases.local.json (gitignored), keyed by the log's
                 channel-set fingerprint.
  Log            an MF4 opened with asammdf, channels listed, signals fetched.
  suggest_map    a first guess from role words in channel names and units.
  reference      one window of the log resampled onto a uniform grid, in the
                 canonical units the model side uses (km/h, %, Nm, kW, %).
  find_windows   candidate replay windows: moving, optionally brake-free,
                 bounded in length, with a tip-in count.
  model_from_plt the model run's channels straight from the .plt (no MF4),
                 in the same canonical units.
  score          lag search on speed, then RMSE / normalised RMSE /
                 correlation per signal and a weighted total.
================================================================================
"""
import hashlib
import json
import os
import re
import time
from collections import OrderedDict

import numpy as np

# hints are role WORDS and abbreviations, matched case-insensitively against
# channel names; `(?=...)` pairs mean "both somewhere in the name"
_TRQ = r"(?=.*(trq|torq|tq(?![a-z])))"
_FRONT = r"(?=.*(^|[^a-z])(front|frnt|frt|fr|f)(?![a-z]))"
_REAR = r"(?=.*(^|[^a-z])(rear|rr|r)(?![a-z]))"
ROLES = OrderedDict([
    ("speed",        {"label": "Vehicle speed", "required": True, "kind": "speed",
                      "hint": r"spe{0,2}d|veloc|(^|[^a-z])vx?(?![a-z])|kph|km_?h"}),
    ("pedal",        {"label": "Accelerator pedal", "required": True, "kind": "pct",
                      "hint": r"pedal|pdl|accel.?p|throttle|apps|acc.?pos|(^|[^a-z])app(?![a-z])"}),
    ("brake",        {"label": "Brake pedal / pressure", "required": False, "kind": "pct",
                      "hint": r"brake|brk|bpp"}),
    ("torque_front", {"label": "Front motor torque", "required": False, "kind": "torque",
                      "hint": _TRQ + _FRONT}),
    ("torque_rear",  {"label": "Rear motor torque", "required": False, "kind": "torque",
                      "hint": _TRQ + _REAR}),
    ("pack_power",   {"label": "Battery pack power", "required": False, "kind": "power",
                      "hint": r"(batt|pack|hv|ress|ess).*(pow|pwr|kw)|(^|[^a-z])power(?![a-z])"}),
    ("pack_voltage", {"label": "Pack voltage", "required": False, "kind": "voltage",
                      "hint": r"(batt|pack|hv|ress|ess).*(volt|(^|[^a-z])[vu](?![a-z]))"}),
    ("pack_current", {"label": "Pack current", "required": False, "kind": "current",
                      "hint": r"(batt|pack|hv|ress|ess).*(curr|amp|(^|[^a-z])i(?![a-z]))"}),
    ("soc",          {"label": "State of charge", "required": False, "kind": "soc",
                      "hint": r"(^|[^a-z])soc(?![a-z])|state.?of.?charge"}),
])

# unit -> factor to the canonical unit of each kind
UNITS = {
    "speed":   {"km/h": 1.0, "kph": 1.0, "kmh": 1.0, "m/s": 3.6, "mps": 3.6,
                "mph": 1.609344, "mm/s": 0.0036},
    "pct":     {"%": 1.0, "pct": 1.0, "0-1": 100.0, "frac": 100.0, "on/off": 100.0},
    "torque":  {"Nm": 1.0, "N-m": 1.0, "N*m": 1.0, "N.m": 1.0, "kNm": 1000.0,
                "Nmm": 0.001, "N-mm": 0.001, "lbf-ft": 1.3558179},
    "power":   {"kW": 1.0, "W": 0.001, "MW": 1000.0, "hp": 0.7456999},
    "voltage": {"V": 1.0, "kV": 1000.0},
    "current": {"A": 1.0, "kA": 1000.0},
    "soc":     {"%": 1.0, "0-1": 100.0, "frac": 100.0},
}
CANON = {"speed": "km/h", "pct": "%", "torque": "Nm", "power": "kW",
         "voltage": "V", "current": "A", "soc": "%"}

# the model side: converter channel -> (role, scale from the raw .plt value)
MODEL_CHANNELS = {
    "VehicleSpeed":     ("speed", None),
    "AcceleratorPedal": ("pedal", None),
    "BrakePosition":    ("brake", None),
    "EM1Torque":        ("torque_front", None),
    "EM2Torque":        ("torque_rear", None),
    "BattPower":        ("pack_power", None),
    "BattSOC":          ("soc", None),
}

DEFAULT_WEIGHTS = {"speed": 1.0, "torque_front": 1.0, "torque_rear": 1.0,
                   "pack_power": 0.5}


def unit_factor(role, unit, full_scale=None):
    kind = ROLES[role]["kind"]
    if full_scale:
        if kind not in ("pct", "soc"):
            raise ValueError("full_scale only applies to pedal/brake/SOC roles")
        return 100.0 / float(full_scale)
    table = UNITS[kind]
    u = (unit or "").strip()
    for k, f in table.items():
        if k.lower() == u.lower():
            return f
    if not u:
        return 1.0   # unit unknown: assume canonical, flagged by the caller
    raise ValueError("unit '{}' not accepted for {} (one of {})".format(
        u, role, ", ".join(table)))


def roles_meta():
    return [{"role": r, "label": m["label"], "required": m["required"],
             "kind": m["kind"], "units": sorted(UNITS[m["kind"]]),
             "canonical": CANON[m["kind"]]} for r, m in ROLES.items()]


# -------------------------------------------------------------------- the log
class Log:
    """An MF4 opened read-only. Channel names are data, not code: nothing here
    assumes what they are."""

    def __init__(self, path):
        from asammdf import MDF
        self.path = path
        self._mdf = MDF(path)
        self._cache = {}
        masters = getattr(self._mdf, "masters_db", {})
        chans = []
        for name in sorted(self._mdf.channels_db, key=str.lower):
            for g, i in self._mdf.channels_db[name]:
                if masters.get(g) == i:
                    continue
                ch = self._mdf.groups[g].channels[i]
                chans.append({"name": name, "unit": getattr(ch, "unit", "") or "",
                              "samples": int(self._mdf.groups[g].channel_group.cycles_nr),
                              "group": g, "index": i})
                break
        self.channels = chans
        self._by_name = {c["name"]: c for c in chans}

    @property
    def fingerprint(self):
        h = hashlib.sha1("\n".join(sorted(self._by_name)).encode("utf-8"))
        return h.hexdigest()[:12]

    def names(self):
        return list(self._by_name)

    def get(self, name):
        """(timestamps, samples) as float arrays, cached."""
        if name in self._cache:
            return self._cache[name]
        c = self._by_name.get(name)
        if c is None:
            raise KeyError("channel '{}' not in {}".format(name, os.path.basename(self.path)))
        sig = self._mdf.get(name, group=c["group"], index=c["index"])
        t = np.asarray(sig.timestamps, float)
        y = np.asarray(sig.samples, float)
        n = min(len(t), len(y))
        t, y = t[:n], y[:n]
        order = np.argsort(t, kind="stable")
        if not np.all(np.diff(t) > 0):
            t, y = t[order], y[order]
            keep = np.concatenate([[True], np.diff(t) > 0])
            t, y = t[keep], y[keep]
        self._cache[name] = (t, y)
        return t, y

    def span(self, name):
        t, _ = self.get(name)
        return (float(t[0]), float(t[-1])) if t.size else (0.0, 0.0)

    def close(self):
        try:
            self._mdf.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def suggest_map(channels):
    """A first guess {role: {"name", "unit"} | None} from role words in the
    channel names plus unit agreement. The user confirms in the UI."""
    out = {}
    taken = set()
    for role, meta in ROLES.items():
        pat = re.compile(meta["hint"], re.I)
        table = UNITS[meta["kind"]]
        best, best_score = None, 0
        for c in channels:
            name, unit = c["name"], (c.get("unit") or "")
            if name in taken:
                continue
            s = 0
            if pat.search(name):
                s += 2
                # a brake-pedal channel must not be taken for the accelerator
                if role == "pedal" and re.search(r"brake|brk", name, re.I):
                    s = 0
            if s and unit and any(unit.lower() == u.lower() for u in table):
                s += 1
            if s and (s > best_score or (s == best_score and best and
                                         len(name) < len(best["name"]))):
                best, best_score = c, s
        if best and best_score >= 2:
            unit = best.get("unit") or ""
            if not any(unit.lower() == u.lower() for u in table):
                unit = CANON[meta["kind"]]   # unknown unit: assume canonical, user checks
            out[role] = {"name": best["name"], "unit": unit}
            taken.add(best["name"])
        else:
            out[role] = None
    return out


# ------------------------------------------------------------- saved mappings
def aliases_path():
    import pipeline
    return os.path.join(pipeline.app_dir(), "channel_aliases.local.json")


def load_aliases():
    try:
        with open(aliases_path(), encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_map(fingerprint, cmap, log_name=""):
    d = load_aliases()
    d.setdefault("by_fingerprint", {})[fingerprint] = {
        "map": cmap, "log": os.path.basename(log_name),
        "saved": time.strftime("%Y-%m-%d %H:%M")}
    d["last"] = {"map": cmap, "fingerprint": fingerprint}
    with open(aliases_path(), "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2)
    return aliases_path()


def resolve_map(log):
    """(cmap, source): the saved map for this exact channel set, else the
    last saved map when every channel it names exists here, else a
    suggestion."""
    d = load_aliases()
    fp = log.fingerprint
    saved = (d.get("by_fingerprint") or {}).get(fp)
    if saved and isinstance(saved.get("map"), dict):
        return saved["map"], "saved"
    last = (d.get("last") or {}).get("map")
    if isinstance(last, dict):
        names = set(log.names())
        if all((not e) or e.get("name") in names for e in last.values()):
            return last, "last"
    return suggest_map(log.channels), "suggested"


def check_map(cmap, log=None):
    """Problems with a mapping: missing required roles, unknown channels,
    unknown units. Returns a list of strings (empty = fine)."""
    probs = []
    names = set(log.names()) if log is not None else None
    for role, meta in ROLES.items():
        ent = (cmap or {}).get(role)
        if not ent or not ent.get("name"):
            if meta["required"]:
                probs.append("{} is required".format(meta["label"]))
            continue
        if names is not None and ent["name"] not in names:
            probs.append("{}: channel not in this log".format(meta["label"]))
        try:
            unit_factor(role, ent.get("unit"), ent.get("full_scale"))
        except ValueError as exc:
            probs.append("{}: {}".format(meta["label"], exc))
    return probs


# ------------------------------------------------------------- the reference
def reference(log, cmap, t0, t1, dt=0.01):
    """One window of the log on a uniform grid, canonical units, time from
    the window start. Keys: t, <role> arrays, has {role: bool}, v0_kph,
    t0, t1, dt, notes."""
    probs = check_map(cmap, log)
    if probs:
        raise ValueError("channel map: " + "; ".join(probs))
    t = np.arange(0.0, float(t1) - float(t0) + 1e-9, dt)
    out = {"t": t, "t0": float(t0), "t1": float(t1), "dt": dt,
           "has": {}, "notes": []}
    for role in ROLES:
        ent = cmap.get(role)
        if not ent or not ent.get("name"):
            out["has"][role] = False
            continue
        tt, yy = log.get(ent["name"])
        f = unit_factor(role, ent.get("unit"), ent.get("full_scale"))
        sign = float(ent.get("sign", 1) or 1)
        if not ent.get("unit") and not ent.get("full_scale"):
            out["notes"].append("{}: no unit given, assumed {}".format(
                ROLES[role]["label"], CANON[ROLES[role]["kind"]]))
        out[role] = np.interp(t + float(t0), tt, yy) * f * sign
        out["has"][role] = True
    if not out["has"].get("pack_power") and out["has"].get("pack_voltage") \
            and out["has"].get("pack_current"):
        out["pack_power"] = out["pack_voltage"] * out["pack_current"] / 1000.0
        out["has"]["pack_power"] = True
        out["notes"].append("pack power derived as voltage x current")
    if not out["has"].get("brake"):
        out["brake"] = np.zeros_like(t)
        out["notes"].append("no brake channel: brake replayed as 0")
    out["v0_kph"] = float(out["speed"][0])
    return out


def _runs(mask):
    e = np.diff(np.r_[0, mask.astype(int), 0])
    return list(zip(np.where(e == 1)[0], np.where(e == -1)[0]))


def find_windows(ref, min_len_s=20.0, max_len_s=90.0, v_floor_kph=3.0,
                 brake_free=False, brake_thresh_pct=2.0):
    """Candidate replay windows from a reference covering the whole log.
    Moving the whole time (speed > floor), optionally brake-free, split
    into pieces no longer than max_len_s. Returns a list of dicts with
    absolute t0/t1 and descriptive stats."""
    t = ref["t"] + ref["t0"]
    v = ref["speed"]
    mask = v > float(v_floor_kph)
    if brake_free and ref["has"].get("brake"):
        mask &= ref["brake"] < float(brake_thresh_pct)
    pedal = ref["pedal"]
    out = []
    for i0, i1 in _runs(mask):
        dur = float(t[i1 - 1] - t[i0])
        if dur < min_len_s:
            continue
        k = max(1, int(np.ceil(dur / max_len_s)))
        bounds = np.linspace(i0, i1, k + 1).astype(int)
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a < 2 or float(t[b - 1] - t[a]) < min_len_s:
                continue
            seg_t, seg_v, seg_p = t[a:b], v[a:b], pedal[a:b]
            out.append({
                "t0": round(float(seg_t[0]), 2), "t1": round(float(seg_t[-1]), 2),
                "dur_s": round(float(seg_t[-1] - seg_t[0]), 1),
                "v0_kph": round(float(seg_v[0]), 1),
                "v_mean_kph": round(float(seg_v.mean()), 1),
                "v_max_kph": round(float(seg_v.max()), 1),
                "tipins": int(_count_tipins(seg_t, seg_v, seg_p)),
                "brake_frac": round(float(np.mean(ref["brake"][a:b] > brake_thresh_pct)), 3)
                if ref["has"].get("brake") else None,
                "regen_frac": round(float(np.mean(ref["torque_front"][a:b] < 0)), 3)
                if ref["has"].get("torque_front") else None,
            })
    return out


def _count_tipins(t, v_kph, pedal_pct, grad_min=60.0, pedal_min=5.0, gap_s=2.0):
    """Tip-ins: pedal rising faster than grad_min %/s while above pedal_min %,
    at least gap_s apart (the Drive Quality tab's detector, inlined so this
    module has no import that carries fitted data)."""
    if len(t) < 3:
        return 0
    grad = np.gradient(pedal_pct, t)
    hit = (grad > grad_min) & (pedal_pct > pedal_min)
    n, last = 0, -1e9
    for i in np.where(hit)[0]:
        if t[i] - last >= gap_s:
            n += 1
            last = t[i]
    return n


# ------------------------------------------------------------- the model side
def model_from_plt(plt_path, nam_path=None, pack_voltage=380.0, log=None):
    """The model run's channels from the solver output, in canonical units,
    time from the run start. Uses the converter's own request mapping and
    scale factors, so it agrees with the MF4 the converter would write."""
    import avl_extract
    nam_path = nam_path or os.path.splitext(plt_path)[0] + ".nam"
    times, raw, missing = avl_extract.extract(
        plt_path, nam_path, log=log or (lambda s: None), pack_voltage=pack_voltage)
    out = {"t": np.asarray(times, float) - float(times[0]), "has": {},
           "missing": [m[0] for m in missing]}
    for ch, (role, _) in MODEL_CHANNELS.items():
        if ch in raw:
            unit, scale, offset = avl_extract.CHANNEL_CONFIG[ch][:3]
            out[role] = np.asarray(raw[ch], float) * scale + offset
            out["has"][role] = True
        else:
            out["has"][role] = False
    return out


def model_from_mf4(path):
    """Same dict from a converted MF4 (units already physical)."""
    with Log(path) as m:
        names = set(m.names())
        base = None
        out = {"has": {}}
        for ch, (role, _) in MODEL_CHANNELS.items():
            if ch in names:
                t, y = m.get(ch)
                if base is None:
                    base = t
                    out["t"] = t - t[0]
                out[role] = np.interp(base, t, y) if t is not base else y
                out["has"][role] = True
            else:
                out["has"][role] = False
    return out


# ---------------------------------------------------------------- comparison
def best_lag(t_m, y_m, t_r, y_r, max_lag_s=2.0, dt=0.01, settle_s=0.0):
    """Lag (s) by which the model trails the reference: the shift that
    maximises the Pearson correlation of model(g) with reference(g - lag).
    Correlation, not RMSE, so a model that is merely too fast or too slow
    (a scaled or offset trace - exactly what a wrong road load produces) does
    not bias the alignment."""
    end = min(float(t_m[-1]), float(t_r[-1]))
    g = np.arange(max(settle_s, max_lag_s), end - max_lag_s, dt)
    if g.size < 10:
        return 0.0
    m = np.interp(g, t_m, y_m)
    m = m - m.mean()
    if not np.any(m):
        return 0.0
    lags = np.arange(-max_lag_s, max_lag_s + dt / 2, dt)
    best, best_c = 0.0, -np.inf
    for L in lags:
        r = np.interp(g - L, t_r, y_r)
        r = r - r.mean()
        denom = np.sqrt(np.sum(m * m) * np.sum(r * r))
        c = float(np.sum(m * r) / denom) if denom > 0 else -np.inf
        if c > best_c + 1e-12:
            best, best_c = float(L), c
    return 0.0 if abs(best) < dt / 2 else best


def score(model, ref, weights=None, settle_s=3.0, max_lag_s=2.0, dt=0.01,
          lag_on="speed"):
    """Per-signal RMSE, normalised RMSE (by the reference's robust range) and
    correlation after a lag search on `lag_on`; total = weighted mean of the
    normalised RMSEs over the signals present on both sides."""
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    t_m, t_r = np.asarray(model["t"], float), np.asarray(ref["t"], float)
    lag = 0.0
    if model["has"].get(lag_on) and ref["has"].get(lag_on) and max_lag_s > 0:
        lag = best_lag(t_m, model[lag_on], t_r, ref[lag_on], max_lag_s, dt, settle_s)
    g0 = max(settle_s, lag, 0.0)
    g1 = min(float(t_m[-1]), float(t_r[-1]) + lag)
    g = np.arange(g0, g1, dt)
    res = {"lag_s": round(lag, 3), "n": int(g.size), "signals": {}, "notes": [],
           "span_s": [round(g0, 2), round(g1, 2)], "model_end_s": round(float(t_m[-1]), 2),
           "ref_end_s": round(float(t_r[-1]), 2)}
    if g.size < 10:
        res["notes"].append("overlap too short to score")
        res["total"] = 10.0
        return res
    if float(t_m[-1]) < 0.9 * float(t_r[-1]):
        res["notes"].append("model run ended early ({:.1f} of {:.1f} s)".format(
            float(t_m[-1]), float(t_r[-1])))
    wsum, acc = 0.0, 0.0
    for role in ROLES:
        if role in ("pack_voltage", "pack_current"):
            continue
        if not (model["has"].get(role) and ref["has"].get(role)):
            if role in weights and weights[role] > 0:
                res["notes"].append("{} not on both sides - skipped".format(role))
            continue
        m = np.interp(g, t_m, model[role])
        r = np.interp(g - lag, t_r, ref[role])
        d = m - r
        rmse = float(np.sqrt(np.mean(d * d)))
        rng = float(np.percentile(r, 98) - np.percentile(r, 2))
        rng = max(rng, 1e-6 if not np.allclose(r, 0) else 1.0)
        nrmse = rmse / rng
        with np.errstate(invalid="ignore", divide="ignore"):
            c = np.corrcoef(m, r)[0, 1] if (m.std() > 0 and r.std() > 0) else 0.0
        res["signals"][role] = {
            "rmse": round(rmse, 4), "nrmse": round(nrmse, 4),
            "corr": round(float(0.0 if np.isnan(c) else c), 4),
            "ref_range": round(rng, 3), "mean_model": round(float(m.mean()), 3),
            "mean_ref": round(float(r.mean()), 3), "unit": CANON[ROLES[role]["kind"]],
            "weight": float(weights.get(role, 0.0))}
        w = float(weights.get(role, 0.0))
        if w > 0:
            wsum += w
            acc += w * nrmse
    if model["has"].get("soc") and ref["has"].get("soc"):
        res["soc_drop"] = {"model": round(float(model["soc"][0] - model["soc"][-1]), 3),
                           "ref": round(float(ref["soc"][0] - ref["soc"][-1]), 3)}
    res["total"] = round(acc / wsum, 5) if wsum > 0 else 10.0
    if wsum == 0:
        res["notes"].append("no weighted signal present on both sides")
    return res


def overlay(model, ref, lag_s=0.0, roles=("speed", "torque_front", "torque_rear",
                                           "pack_power", "pedal", "brake"), n=600):
    """Downsampled series for the page: {role: {t, model, ref, unit}}."""
    t_m, t_r = np.asarray(model["t"], float), np.asarray(ref["t"], float)
    end = min(float(t_m[-1]), float(t_r[-1]) + lag_s)
    g = np.linspace(0.0, end, min(n, max(2, int(end / 0.05))))
    out = {}
    for role in roles:
        if not (model["has"].get(role) or ref["has"].get(role)):
            continue
        e = {"t": [round(float(x), 2) for x in g],
             "unit": CANON[ROLES[role]["kind"]]}
        if model["has"].get(role):
            e["model"] = [round(float(x), 3) for x in np.interp(g, t_m, model[role])]
        if ref["has"].get(role):
            e["ref"] = [round(float(x), 3) for x in np.interp(g - lag_s, t_r, ref[role])]
        out[role] = e
    return out
