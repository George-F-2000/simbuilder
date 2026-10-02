# -*- coding: utf-8 -*-
"""
pedal_map.py - the calibration layer between the real pedal and the model
pedal: a monotone piecewise-linear map real_pct -> model_pct, fitted from a
logged drive against the demand law of the powertrain FMU (which cannot be
patched: its pedal shaping is compiled in).

The fitted anchors are vehicle-specific and live in pedal_anchors.local.json
(gitignored): {"anchors": [[real_pct, model_pct], ...], "fit_limit_real": pct}.
Without that file the map is the identity (demo) and is_extrapolated() is
never true.
"""

# (real_pct, model_pct) - monotone, smoothed through the fitted anchors
import json as _json
import os as _os


def _load_anchors():
    import sys as _sys
    here = (_os.path.dirname(_os.path.abspath(_sys.executable)) if getattr(_sys, "frozen", False)
            else _os.path.dirname(_os.path.abspath(__file__)))
    try:
        with open(_os.path.join(here, "pedal_anchors.local.json"), encoding="utf-8") as fh:
            d = _json.load(fh)
        anchors = [(float(a), float(b)) for a, b in d["anchors"]]
        return anchors, float(d.get("fit_limit_real", anchors[-1][0]))
    except (OSError, ValueError, KeyError, TypeError):
        return [(0.0, 0.0), (100.0, 100.0)], 100.0     # demo: identity


_ANCHORS, FIT_LIMIT_REAL = _load_anchors()


def real_to_model(real_pct):
    """Model pedal % that emulates the given real-car pedal %."""
    r = max(0.0, min(100.0, float(real_pct)))
    for (r0, m0), (r1, m1) in zip(_ANCHORS, _ANCHORS[1:]):
        if r <= r1:
            return round(m0 + (r - r0) * (m1 - m0) / (r1 - r0), 2)
    return 100.0


def model_to_real(model_pct):
    """Inverse: what real-car pedal the given model pedal corresponds to."""
    m = max(0.0, min(100.0, float(model_pct)))
    for (r0, m0), (r1, m1) in zip(_ANCHORS, _ANCHORS[1:]):
        if m <= m1:
            return round(r0 + (m - m0) * (r1 - r0) / (m1 - m0), 2)
    return 100.0


def is_extrapolated(real_pct):
    """True if this request is outside the measured calibration range."""
    return float(real_pct) > FIT_LIMIT_REAL


if __name__ == "__main__":
    print("real%  -> model%   (E = extrapolated, uncalibrated)")
    for r in (5, 10, 20, 30, 40, 45, 50, 70, 100):
        print("  %3d   ->  %5.1f    %s" % (r, real_to_model(r),
                                           "E" if is_extrapolated(r) else ""))
