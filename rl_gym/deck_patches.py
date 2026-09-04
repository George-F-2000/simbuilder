"""deck_patches.py - per-run deck repairs shared by the rl_gym runners.

regen_slip_limiter(deck_text) -> (text, n_patched)
    The deck applies the powertrain FMU's torques through two Reference_
    Variables ("FMU torque - front" / "- rear"). Nothing in the model reduces
    regenerative torque when a wheel starts to slide, so a full lift-off at
    speed locks and reverses the front wheels for every entrant (Bible 30.19).
    A production inverter/VCU slip-limits regen; this patch adds that at the
    deck level, equally for stock and learned FMUs: NEGATIVE torque on an axle
    is scaled by STEP5(r, 0.5, 0, 0.9, 1) where r is that axle's wheel speed
    over the other axle's (the un-driven reference an ABS would use) - full
    regen while the wheel turns within 10% of the vehicle, none below 50%.
    Driving torque is untouched.
"""
import re

_FRONT_WY = "WY(36403030,33601010,33601010)"
_REAR_WY = "WY(36503030,34001010,34001010)"


def _limiter(torque_expr, own_wy, ref_wy):
    ratio = "ABS(%s)/(ABS(%s)+0.5)" % (own_wy, ref_wy)
    return "%s*IF(%s: STEP5(%s, 0.5, 0, 0.9, 1), 1, 1)" % (torque_expr, torque_expr.split("*")[0], ratio)


def regen_slip_limiter(text):
    n_total = 0
    for var_id, aryval, own, ref in (("33200500", "ARYVAL(33200300,6)*1000", _FRONT_WY, _REAR_WY),
                                     ("33200800", "ARYVAL(33200300,1)*1000", _REAR_WY, _FRONT_WY)):
        pat = (r'(id\s+=\s+"%s"\s*\n\s*label\s+=\s+"[^"]*"\s*\n\s*type\s+=\s+"EXPRESSION"\s*\n\s*expr\s+=\s+")%s(")'
               % (var_id, re.escape(aryval)))
        text, n = re.subn(pat, lambda m: m.group(1) + _limiter(aryval, own, ref) + m.group(2), text)
        n_total += n
    return text, n_total
