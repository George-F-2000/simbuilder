# -*- coding: utf-8 -*-
"""PEDAL CALIBRATION LAYER  (v2, fitted 2026-07-26)

Maps REAL-car pedal % -> MODEL pedal % so that "10% pedal" means the same
thing in the model as in the prototype. The model's VCU squares the pedal
(traction_gamma = 2, compiled into the FMU and unpatchable), so its pedal
axis is compressed relative to the real car's near-linear one.

This is a CALIBRATION LAYER, not a physics change: in a real vehicle the
pedal map IS a software layer between pedal position and torque request.
We put ours in front of the sealed FMU. Logged AccelPdlPos remains the FOOT
position (what a real CAN logs); the raw FMU input is kept as PedalCmd_FMU.

FIT BASIS (two independent methods that AGREE at the low end):
  TRANSIENT (primary, matches what AVL Drive scores) - real pedal -> p90
    accel while accelerating, from the MCT dyno log, vs model pedal -> peak
    accel in the rolling tip-in phase (from 20 km/h):
        real  7.5% (0.32 m/s2) -> model 29.6%
        real 12.5% (0.61)      -> model 43.8%
        real 32.5% (0.96)      -> model 51.2%
        real 37.5% (1.26)      -> model 56.5%
        real 42.5% (1.47)      -> model 60.0%
  STEADY (cross-check) - equal sustained speed:
        real 10% -> model 31.5%  (both hold ~42 km/h)   <-- agrees with 7.5->29.6
        real 22% -> model 40.0%  (both hold ~77 km/h)

CONFIDENCE:
  real 5-45%  : FITTED (the MCT log's whole pedal range)
  real >45%   : EXTRAPOLATED - the real car never exceeded 46% pedal in 3.5 h,
                and its max filtered LngAccel was 1.59 m/s2. Nothing in our
                measured data constrains aggressive pedal. Treat model
                behaviour above real ~45% as UNCALIBRATED.
  The 15-30% real plateau in the raw fit is a cycle-following artifact (the
  driver modulates pedal to HOLD a speed trace, not to maximise accel), so
  the map is smoothed monotone through it.

TO CLOSE THE GAP: a 10-minute CAN log of the prototype in REGEN-OFF mode -
a pedal staircase (hold 10/20/30/40/50% for a few s each) plus a few
deliberate tip-ins. That is the correct calibration reference for a
regen-off model and would replace the extrapolated region with data."""

# (real_pct, model_pct) - monotone, smoothed through the fitted anchors
_ANCHORS = [
    (0.0, 0.0),
    (5.0, 22.0),      # below the fit's floor; keeps the curve continuous
    (10.0, 31.0),     # transient 29.6 + steady 31.5 agree here
    (20.0, 44.0),
    (30.0, 49.0),
    (40.0, 58.0),
    (45.0, 61.0),     # last FITTED anchor
    (100.0, 100.0),   # EXTRAPOLATED beyond 45
]
FIT_LIMIT_REAL = 45.0


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
