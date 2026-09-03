"""sweep_events.py - generate the AVL-Drive sweep events (Bible 30.10/30.11).
Three composite ADFs built on the AVLlit template's header/standards/tail,
ALL OPEN-LOOP (the driver's PID FOLLOW_VELOCITY on a step demand is
bang-bang on this deck - 2026-09-03 autopsy):
  acceleration  : OPENLOOP EXPRESSION STEP({%TIME},t0,h0,t1,h1) pedal step
                  with a LONG_VEL GT end condition (mm/s)
  cruise        : constant pedal at the EQUILIBRIUM position p_eq(v) where the
                  measured demand law balances the repaired road load, so the
                  car holds speed with no controller
  brake         : OPENLOOP CONSTANT (never EXPRESSION - channel-0 hijack);
                  brake fraction ~ decel/g, keep stops <= 0.4
Usage: python sweep_events.py  -> writes rl_gym/sweep/<event>.adf"""
import json
import os
import re

import numpy as np
from scipy.io import loadmat

_lc = {}
try:
    _lc = json.load(open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "vehicle_local.json")))
except Exception:
    pass
DATA_ROOT = _lc.get("data_root", "C:/demo_data")
TEMPLATE = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106/custom_event_tipout_10.adf"
DEMAND_LAW = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\stock_demand_law.mat"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep")

KPH = 1000.0 / 3.6   # mm/s per km/h
# repaired road load (Bible 30.10a) and the front-axle drive geometry used
# to turn it into a demand torque at cruise
ROAD = (197.0, 0.599, 0.0438)          # N, N/kph, N/kph^2
R_WHEEL, G_FRONT = float(_lc.get("wheel_radius_m", 0.39)), float(_lc.get("gear_front", 18.0))

CTRL_OL = ("(CONTROLLERS)\n"
           "{DRIVER_SIGNAL             PRIMARY_CONTROLLER        ADDITIONAL_CONTROLLER    }\n"
           " STEER                     OL_STEER                  NONE                     \n"
           " THROTTLE                  OL_THROTTLE_%d             NONE                     \n"
           " BRAKE                     OL_BRAKE_%d                NONE                     \n"
           " GEAR                      GEAR_CLUTCH_CONTROL       NONE                     \n"
           " CLUTCH                    GEAR_CLUTCH_CONTROL       NONE                     \n")


def p_eq(kph):
    """Pedal [0-1] at which the measured demand law holds `kph` on the repaired
    road load (front-only cruise). Inverse-interpolated from stock_demand_law."""
    d = loadmat(DEMAND_LAW)
    ped = np.asarray(d["ped_bp"]).ravel(); spd = np.asarray(d["spd_bp"]).ravel()
    T = np.asarray(d["Tmap"], float)                    # (pedal, speed) in Nm
    v = kph / 3.6
    need = (ROAD[0] + ROAD[1]*kph + ROAD[2]*kph**2) * R_WHEEL / G_FRONT
    col = np.array([np.interp(v, spd, T[i, :]) for i in range(len(ped))])
    idx = np.where(np.diff(np.sign(col - need)) > 0)[0]
    if not len(idx):
        raise ValueError("no equilibrium pedal for %g km/h" % kph)
    i = idx[0]
    return float(np.interp(need, col[i:i+2], ped[i:i+2])) / 100.0


def sep(name):
    return "$" + "-" * max(1, 84 - len(name)) + name + "\n"


def end_cond(op, kph, tol_kph):
    return ("(END_CONDITIONS) \n"
            "{SIGNAL     GROUP      ABS        OPERATOR   VALUE      TOLERANCE  WATCH_TIME}\n"
            " LONG_VEL   0          Y          %-10s %-10.3f %-10.3f 0.001     \n"
            % (op, kph * KPH, tol_kph * KPH))


class Event:
    def __init__(self, name, vx0_mm=10):
        self.name, self.vx0, self.m = name, vx0_mm, []

    def hold(self, secs, brake):
        """standstill: pedal 0, brake held"""
        self.m.append(dict(secs=secs, thr="0", thr_const=True, brake=brake, end=None, note="hold"))

    def pedal(self, secs, target, hold_from="{THROTTLE_0}", delay=1.0, brake=0, end=None, note=""):
        """open-loop pedal step: hold current pedal `delay` s, then 0.3 s ramp to target (0-1)"""
        expr = "STEP({%%TIME},%g,%s,%g,%.4f)" % (delay, hold_from, delay + 0.3, target)
        self.m.append(dict(secs=secs, thr=expr, thr_const=False, brake=brake, end=end,
                           note=note or "pedal %.0f%%" % (100*target)))

    def cruise(self, secs, kph):
        """hold speed with the equilibrium pedal (no controller); 0.5 s blend from the current pedal"""
        p = p_eq(kph)
        expr = "STEP({%%TIME},0,{THROTTLE_0},0.5,%.4f)" % p
        self.m.append(dict(secs=secs, thr=expr, thr_const=False, brake=0, end=None,
                           note="cruise %g km/h at p_eq %.1f%%" % (kph, 100*p)))

    def stop(self, secs, brake):
        """open-loop brake to (near) standstill"""
        self.m.append(dict(secs=secs, thr="0", thr_const=True, brake=brake,
                           end=("LT", 0.7, 0.4), note="brake stop %.2f" % brake))

    def render(self, template):
        head = template[:template.index("[MANEUVERS_LIST]")]
        head = re.sub(r"(VX0\s*=\s*)\S+", r"\g<1>%d" % self.vx0, head)
        head = head.replace("$ Scenario: AVLlit_tipin_50pct - tip-in/out 50% pedal (REGEN-OFF: lift to coast pedal, 5s standstill dwell)",
                            "$ Scenario: %s - AVL-Drive sweep event (generated by sweep_events.py)" % self.name)
        tail = template[re.search(r"\$-+OL_STEER\s*\n\[OL_STEER\]", template).start():]
        out = head
        out += sep("MANEUVERS_LIST") + "[MANEUVERS_LIST]\n{name            simulation_time      h_max           print_interval }\n"
        for i, mv in enumerate(self.m, 1):
            out += "'MANEUVER_%d'     %-20g 0.01            0.01            \n" % (i, mv["secs"])
        for i, mv in enumerate(self.m, 1):
            out += sep("MANEUVER_%d" % i) + "$ %s\n[MANEUVER_%d]\nTASK = 'STANDARD'\n" % (mv["note"], i)
            out += CTRL_OL % (i, i)
            if mv["end"]:
                out += end_cond(*mv["end"])
            out += sep("OL_THROTTLE_%d" % i) + "[OL_THROTTLE_%d]\nTAG                    = 'OPENLOOP'\n" % i
            if mv["thr_const"]:
                out += "TYPE                   = 'CONSTANT'\nVALUE                  = %s\n" % mv["thr"]
            else:
                out += ("TYPE                   = 'EXPRESSION'\nEXPRESSION             = '%s'\n"
                        "SIGNAL_CHANNEL         = 0\n" % mv["thr"])
            out += sep("OL_BRAKE_%d" % i) + ("[OL_BRAKE_%d]\nTAG                    = 'OPENLOOP'\n"
                                            "TYPE                   = 'CONSTANT'\nVALUE                  = %g\n" % (i, mv["brake"]))
        out += tail
        return out


def build():
    T = open(TEMPLATE, encoding="utf-8", errors="replace").read()
    os.makedirs(OUT, exist_ok=True)
    ev = []
    # 1) driveaway family: 20 / 40 / 70 / 100 % from brake-held standstill,
    #    gentle 0.2 stops between (0.5 = -5 m/s2 locked-wheel stop that rolled
    #    the car back and aborted the solver, 2026-09-02)
    d = Event("sweep_driveaway")
    d.hold(5, 0.35)
    for ped, target in ((0.20, 15), (0.40, 30), (0.70, 40), (1.00, 50)):
        d.pedal(45, ped, hold_from="0", end=("GT", target, 1.0), note="driveaway %.0f%%" % (100*ped))
        d.stop(40, 0.2)
        d.hold(4, 0.35)
    ev.append(d)
    # 2) tip-in / tip-out ladder around equilibrium-pedal cruises
    l = Event("sweep_tipin_ladder")
    l.hold(5, 0.35)
    l.pedal(30, 0.35, hold_from="0", end=("GT", 30, 1.0), note="launch 35% to 30")
    l.cruise(15, 30)
    l.pedal(25, 0.50, end=("GT", 50, 1.5), note="tip-in 50% at 30")
    l.cruise(15, 50)
    l.pedal(20, 1.00, end=("GT", 80, 1.5), note="tip-in 100% at 50")
    l.cruise(15, 80)
    l.pedal(6, 0.00, note="lift-off at 80")
    l.pedal(8, 0.35, note="small tip-in 35% from the lift")
    l.pedal(25, 0.70, end=("GT", 100, 1.5), note="tip-in 70% to 100")
    l.cruise(15, 100)
    l.pedal(6, 0.00, note="lift-off at 100")
    l.cruise(6, 100)
    ev.append(l)
    # 3) coast-down and braking stops
    c = Event("sweep_coast_brake")
    c.hold(5, 0.35)
    c.pedal(40, 0.60, hold_from="0", end=("GT", 100, 1.5), note="launch 60% to 100")
    c.cruise(10, 100)
    c.pedal(150, 0.00, end=("LT", 5, 1.0), note="lift at 100, regen coast to 5")
    c.pedal(30, 0.50, end=("GT", 80, 1.5), note="accelerate 50% to 80")
    c.cruise(8, 80)
    c.stop(40, 0.2)
    c.hold(4, 0.35)
    c.pedal(25, 0.40, hold_from="0", end=("GT", 50, 1.5), note="launch 40% to 50")
    c.cruise(8, 50)
    c.stop(30, 0.4)
    c.hold(4, 0.35)
    ev.append(c)
    for e in ev:
        p = os.path.join(OUT, e.name + ".adf")
        open(p, "w", encoding="utf-8").write(e.render(T))
        cap = sum(mv["secs"] for mv in e.m)
        print("%-20s %2d maneuvers, time cap %4.0f s -> %s" % (e.name, len(e.m), cap, p))
        for mv in e.m:
            if mv["note"].startswith("cruise"):
                print("      " + mv["note"])


if __name__ == "__main__":
    build()
