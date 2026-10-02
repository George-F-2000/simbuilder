"""
plant_repairs.py - plant repairs toward physical values, applied to the
exported deck by the pipeline (settings 'plant_repairs', default on).

The RECORDED values are vehicle-specific and live in rl_gym/plant.local.json
(gitignored): {"FRONT_LEN", "REAR_LEN"} (the spring length strings that tell
front from rear), "SPRINGS" {front_k, front_preload, rear_k, rear_preload},
"CG_SHIFT" {marker, pos_x}, "TIR" (tyre file override or null), "BRAKE_BAND".
Without that file every repair is off and the deck runs exactly as exported.

Per-run env overrides: PR_FRONT_K, PR_FRONT_P, PR_REAR_K, PR_REAR_P, PR_CG_X,
PR_BRAKE_BAND - unset keeps the recorded value, "off" disables one, a number
overrides it.
"""
import re

import json as _json
import os as _os


def _local(name, default=None):
    """A recorded repair value from rl_gym/plant.local.json (gitignored)."""
    import sys as _sys
    here = (_os.path.join(_os.path.dirname(_os.path.abspath(_sys.executable)), "rl_gym")
            if getattr(_sys, "frozen", False) else _os.path.dirname(_os.path.abspath(__file__)))
    try:
        with open(_os.path.join(here, "plant.local.json"), encoding="utf-8") as fh:
            return _json.load(fh).get(name, default)
    except (OSError, ValueError):
        return default


FRONT_LEN, REAR_LEN = _local("FRONT_LEN"), _local("REAR_LEN")

# repaired values (None = leave the deck's value); filled in by the static study
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# standstill fail (fore-aft rocking on the tyres' carcass stiffness with the ESP FMU
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
SPRINGS = _local("SPRINGS")


def apply_springs(text, front_k=None, front_preload=None, rear_k=None, rear_preload=None):
    """patch stiffness/preload on the four 'Coil spring-*' Force_SpringDamper elements"""
    n = {"front": 0, "rear": 0}

    def sub(m):
        blk = m.group(0)
        if 'label               = "Coil spring-' not in blk:
            return blk
        if 'length              = "%s"' % FRONT_LEN in blk:
            n["front"] += 1; k, p = front_k, front_preload
        elif 'length              = "%s"' % REAR_LEN in blk:
            n["rear"] += 1; k, p = rear_k, rear_preload
        else:
            return blk
        if k is not None:
            blk = re.sub(r'(stiffness\s*=\s*")[^"]*(")', r'\g<1>%s\g<2>' % k, blk)
        if p is not None:
            blk = re.sub(r'(preload\s*=\s*")[^"]*(")', r'\g<1>%s\g<2>' % p, blk)
        return blk
    text = re.sub(r"<Force_SpringDamper.*?/>", sub, text, flags=re.S)
    return text, n


# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
CG_SHIFT = _local("CG_SHIFT")

# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
TIR = _local("TIR")


def apply_cg_shift(text, marker_id=None, pos_x=None):
    """move one CG marker's pos_x (Reference_Marker id=marker_id)"""
    marker_id = marker_id or CG_SHIFT["marker_id"]
    if pos_x is None:
        return text, 0
    pat = re.compile(r'(<Reference_Marker\s+id\s*=\s*"' + str(marker_id) + r'".*?pos_x\s*=\s*")[^"]*(")', re.S)
    return pat.subn(lambda m: m.group(1) + str(pos_x) + m.group(2), text)


def apply_tir(text, tir=None):
    """repoint the deck's four tyre-file strings"""
    tir = tir or TIR
    if not tir:
        return text, 0
    return re.subn(r'"[^"]*LYRIQ_PS4SUV_265_50R20[^"]*\.tir"', '"' + tir.replace("\\", "/") + '"', text)


# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# (recorded value: see plant.local.json)
# a brake-held standstill (the DAE landmine that killed every rear-off-its-bump-stop hold
# and fed the ESP's pressure pulsing). Widening the band to +/-BRAKE_BAND rad/s makes the
# (recorded value: see plant.local.json)
BRAKE_BAND = _local("BRAKE_BAND")


def apply_brake_band(text, band=None):
    if band is None:
        return text, 0
    pat = re.compile(r'(-STEP5\(WZ\(\d+,\d+,\d+\),)-0\.001,-1,0\.001,1(\)\*VARVAL\(3630\d{4}\))')
    return pat.subn(lambda m: "%s-%g,-1,%g,1%s" % (m.group(1), band, band, m.group(2)), text)


def _env(name, default):
    """per-run override of a recorded repair value: PR_<NAME>=off disables it,
    PR_<NAME>=<number> replaces it (used by the discrimination probes)"""
    import os
    v = os.environ.get("PR_" + name)
    if v is None:
        return default
    return None if v.lower() == "off" else float(v)


def apply_all(text):
    """every repair with its recorded value (env-overridable); returns (text, counts)"""
    springs = dict(front_k=_env("FRONT_K", SPRINGS["front_k"]), front_preload=_env("FRONT_P", SPRINGS["front_preload"]),
                   rear_k=_env("REAR_K", SPRINGS["rear_k"]), rear_preload=_env("REAR_P", SPRINGS["rear_preload"]))
    n = {"front": 0, "rear": 0}
    if any(v is not None for v in springs.values()):
        text, n = apply_springs(text, **springs)
    text, n["cg"] = apply_cg_shift(text, pos_x=_env("CG_X", CG_SHIFT["pos_x"]))
    text, n["tir"] = apply_tir(text)
    text, n["brake"] = apply_brake_band(text, _env("BRAKE_BAND", BRAKE_BAND))
    return text, n

_apply_all_recorded = apply_all


def apply_all(text):
    """No local file -> no repair: the deck as exported, with zero counts."""
    if SPRINGS is None and CG_SHIFT is None and TIR is None and BRAKE_BAND is None:
        return text, {"front": 0, "rear": 0, "cg": 0, "tir": 0, "brake": 0}
    return _apply_all_recorded(text)

