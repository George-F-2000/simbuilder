"""plant_repairs.py - deck-level repairs toward physical values (Bible 30.21).
The healed deck's coil springs are template placeholders: 54.451007 N/mm at
both ends, front preload 12000 N, rear 2270 N. At rest the rear strut sits
14.5 mm into its jounce bumper (768 N per side) and the front has 19 mm of
jounce travel left; the front wheel rate is ~12.5 N/mm (0.67 Hz ride
frequency) so every lift-off dives ~110 mm onto the front bump stops, and a
50% tip-in at 25 km/h can put both front tyres in the air for 60 ms.
Repair: front spring rate to a physical ride frequency (~1.2 Hz for the
sprung corner load at the measured 0.48 motion ratio) and both preloads set
so the static position sits with the bump stops clear. Values are found with
ride_height_static.py and recorded here; every runner applies them."""
import re

FRONT_LEN, REAR_LEN = "141.06519", "156.4289"   # the deck's coil-spring reference lengths (front / rear)

# repaired values (None = leave the deck's value); filled in by the static study
# static study 2026-09-04 (ride_height_static.py runs A-C): at rest the wheel centres
# sit within 6 mm of the design position, both bump stops unloaded, pitch 0.07 deg,
# tyre loads 7.66 kN front / 5.86 kN rear per wheel (unchanged mass)
# FRONT ONLY: lifting the rear off its bump stop (rear_preload 5355) makes the brake-held
# standstill fail (fore-aft rocking on the tyres' carcass stiffness with the ESP FMU
# pulsing; DASPK stalls at 0.6-1.6 s; more tyre low-speed damping makes it worse).
# The rear sag (14.5 mm into the bump stop, 47 mm below design) stays a documented defect.
SPRINGS = dict(front_k=174.0, front_preload=17060.0, rear_k=None, rear_preload=None)


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


def apply_all(text):
    """every repair with its recorded value; returns (text, counts)"""
    if any(v is not None for v in SPRINGS.values()):
        return apply_springs(text, **SPRINGS)
    return text, {"front": 0, "rear": 0}
