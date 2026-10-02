"""
optimizer/plant.py
================================================================================
The two tunables and how they reach the plant.

Both are SCALES applied to copies of the files the deck already uses, so the
study tunes relative to whatever road-load repair the base files carry:

  lmy_scale   [SCALING_COEFFICIENTS] LMY in the tyre file (.tir) is multiplied.
              LMY scales the Magic Formula rolling-resistance moment, so this
              is the constant / load-proportional road-load term.
  aero_scale  the COEFFICIENT column of the [DRAG_COEFFICIENT] spline table in
              the aero file (.aae) is multiplied - the v^2 road-load term.

File formats are the ones MotionView's autoentities ship (TeimOrbit-style
blocks: [BLOCK], KEY = value lines, (SPLINE_DATA) tables). Every edit asserts
its substitution count and raises on zero matches: a candidate whose files did
not change must never be scored as if they had.

PARAMS is the complete registry. validate_params() rejects any other key -
that is where the "physics is locked" rule lives in code.
================================================================================
"""
import os
import re

PARAMS = {
    "lmy_scale": {
        "label": "Rolling resistance x (tyre LMY)",
        "default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05,
        "file": "tire",
        "tip": "Multiplies LMY in a copy of the tyre file. LMY scales the "
               "rolling-resistance moment of every tyre, i.e. the constant / "
               "load-proportional part of the road load. 1.0 = the base file.",
    },
    "aero_scale": {
        "label": "Aero drag x (Cd table)",
        "default": 1.0, "min": 0.5, "max": 1.6, "step": 0.05,
        "file": "aero",
        "tip": "Multiplies the drag-coefficient column of the [DRAG_COEFFICIENT] "
               "table in a copy of the aero file: the v^2 part of the road load. "
               "1.0 = the base file.",
    },
}

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?"


class PlantEditError(RuntimeError):
    """A file edit did not find its target - the candidate must not run."""


# --------------------------------------------------------------------- params
def validate_params(params, bounds=None):
    """Return {name: float} for a candidate. Unknown names raise (physics
    lock); values are clipped to the registry bounds, or to `bounds`
    {name: (lo, hi)} when given (which must themselves lie inside the
    registry's)."""
    out = {}
    for k, v in (params or {}).items():
        if k not in PARAMS:
            raise KeyError("'{}' is not a tunable parameter; the registry is {}"
                           .format(k, sorted(PARAMS)))
        meta = PARAMS[k]
        lo, hi = meta["min"], meta["max"]
        if bounds and k in bounds:
            blo, bhi = float(bounds[k][0]), float(bounds[k][1])
            if blo < lo or bhi > hi or blo >= bhi:
                raise ValueError("bounds for {} must lie inside [{}, {}] "
                                 "and be ordered".format(k, lo, hi))
            lo, hi = blo, bhi
        out[k] = float(min(max(float(v), lo), hi))
    return out


def full_params(params):
    """Fill the registry defaults for parameters a candidate leaves out."""
    p = {k: meta["default"] for k, meta in PARAMS.items()}
    p.update(validate_params(params))
    return p


# ---------------------------------------------------------------- text edits
def _fmt(x):
    s = "{:.6g}".format(x)
    return s if ("." in s or "e" in s or "E" in s) else s + ".0"


def scale_keyword(text, keyword, factor):
    """Multiply the number after `KEYWORD =` (first match, any block).
    Returns (text, old_value). Raises PlantEditError on zero matches."""
    pat = re.compile(r"^(\s*%s\s*=\s*)(%s)" % (re.escape(keyword), NUM),
                     re.M | re.I)
    found = {}

    def repl(m):
        old = float(m.group(2).replace("D", "E").replace("d", "e"))
        found["old"] = old
        return m.group(1) + _fmt(old * factor)

    new, n = pat.subn(repl, text, count=1)
    if n != 1:
        raise PlantEditError("keyword '{}' not found".format(keyword))
    return new, found["old"]


def scale_spline_column(text, block, column, factor):
    """Inside `[BLOCK]`, multiply column `column` (0-based) of the numeric
    rows of its (SPLINE_DATA) table. The block ends at the next '[' header or
    at a '$---' rule line. Returns (text, n_rows). Raises PlantEditError when
    the block or table is missing."""
    head = re.search(r"^\s*\[%s\]\s*$" % re.escape(block), text, re.M | re.I)
    if not head:
        raise PlantEditError("block [{}] not found".format(block))
    start = head.end()
    tail = re.search(r"^\s*(?:\[|\$-{3,})", text[start:], re.M)
    end = start + tail.start() if tail else len(text)
    body = text[start:end]
    # one table row per line: only spaces/tabs between numbers, never newlines
    row_re = re.compile(r"^([ \t]*)(%s)((?:[ \t]+%s)+)[ \t]*$" % (NUM, NUM), re.M)
    n_rows = 0

    def repl(m):
        nonlocal n_rows
        nums = [m.group(2)] + m.group(3).split()
        if column >= len(nums):
            return m.group(0)
        vals = [float(x.replace("D", "E").replace("d", "e")) for x in nums]
        vals[column] = vals[column] * factor
        n_rows += 1
        return m.group(1) + "  ".join(_fmt(v) if i == column else nums[i]
                                      for i, v in enumerate(vals))

    new_body = row_re.sub(repl, body)
    if n_rows == 0:
        raise PlantEditError("no numeric table rows in [{}]".format(block))
    return text[:start] + new_body + text[end:], n_rows


# ---------------------------------------------------------------- file edits
def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def tire_with_lmy_scale(src, factor, dst):
    """Copy the tyre file with LMY multiplied by `factor`. Returns
    (dst, old_lmy)."""
    text, old = scale_keyword(_read(src), "LMY", factor)
    _write(dst, text)
    return dst, old


def aero_with_drag_scale(src, factor, dst, block="DRAG_COEFFICIENT"):
    """Copy the aero file with the drag-coefficient table scaled. Returns
    (dst, n_rows)."""
    text, n = scale_spline_column(_read(src), block, 1, factor)
    _write(dst, text)
    return dst, n


def candidate_files(plant_dir, cid, params, tire_src, aero_src):
    """Write this candidate's tyre and aero copies into plant_dir and return
    {"tire_path", "aero_path", "edits"}. A scale of exactly 1.0 still writes
    a copy (unchanged content), so every candidate's files are its own and the
    run folder provenance is uniform."""
    p = full_params(params)
    tag = "c{:02d}".format(int(cid))
    edits = {}
    tire_dst = os.path.join(plant_dir, "{}_{}".format(
        tag, os.path.basename(tire_src)))
    _, old_lmy = tire_with_lmy_scale(tire_src, p["lmy_scale"], tire_dst)
    edits["lmy"] = {"base": old_lmy, "scale": p["lmy_scale"],
                    "value": old_lmy * p["lmy_scale"]}
    aero_dst = os.path.join(plant_dir, "{}_{}".format(
        tag, os.path.basename(aero_src)))
    _, n_rows = aero_with_drag_scale(aero_src, p["aero_scale"], aero_dst)
    edits["aero"] = {"scale": p["aero_scale"], "rows": n_rows}
    return {"tire_path": tire_dst, "aero_path": aero_dst, "edits": edits}


# ------------------------------------------------------------ deck file refs
def deck_file_refs(deck_path, ext):
    """Absolute paths of the files with extension `ext` the deck references,
    resolved the way pipeline.patch_deck heals them at run time: relative
    climbs against the deck's own folder; a missing absolute path replaced by
    a same-named file next to the deck or by the same file under another
    installed Altair version. Returns a de-duplicated list; a path that could
    not be healed is kept so the caller can report it."""
    from pipeline import PATH_TOKEN, _heal_altair_version
    text = _read(deck_path)
    src_dir = os.path.dirname(os.path.abspath(deck_path))
    out = []
    for m in PATH_TOKEN.finditer(text):
        tok = m.group(0)
        if not tok.lower().endswith(ext.lower()):
            continue
        if tok.startswith(("../", "..\\")):
            path = os.path.normpath(os.path.join(src_dir, tok))
        else:
            path = os.path.normpath(tok.replace("/", os.sep))
        if not os.path.exists(path):
            beside = os.path.join(src_dir, os.path.basename(path))
            healed = _heal_altair_version(path)
            if os.path.exists(beside):
                path = beside
            elif healed:
                path = healed
        if path not in out:
            out.append(path)
    return out


def base_files(settings, vehicle=None):
    """The tyre and aero files a study scales: the vehicle payload's overrides
    when set, else the deck's own references. Returns
    {"tire": path|None, "aero": path|None, "tire_candidates": [...],
     "aero_candidates": [...]}."""
    veh = vehicle or {}
    deck = settings.get("deck") or ""
    tires = deck_file_refs(deck, ".tir") if os.path.isfile(deck) else []
    aeros = deck_file_refs(deck, ".aae") if os.path.isfile(deck) else []
    tire = veh.get("tire_path") or (tires[0] if tires else None)
    aero = veh.get("aero_path") or (aeros[0] if aeros else None)
    return {"tire": tire, "aero": aero,
            "tire_candidates": tires, "aero_candidates": aeros,
            "tire_ok": bool(tire and os.path.isfile(tire)),
            "aero_ok": bool(aero and os.path.isfile(aero))}
