"""sweep_events.py - generate the AVL-Drive sweep events (Bible 30.10-30.12).
Three composite ADFs built on the AVLlit template's header/standards/tail,
ALL OPEN-LOOP (the driver's PID FOLLOW_VELOCITY on a step demand is
bang-bang on this deck - 2026-09-03 autopsy):
  acceleration  : OPENLOOP EXPRESSION STEP({%TIME},t0,h0,t1,h1) pedal step
                  with a LONG_VEL GT end condition (mm/s), tolerance 2.5 km/h
                  (the proven AVLlit band; 1 km/h was skipped at times)
  cruise        : constant pedal at the EQUILIBRIUM position p_eq(v) where the
                  measured demand law balances the repaired road load, so the
                  car holds speed with no controller (verified: a ~ 0.0)
  brake         : OPENLOOP CONSTANT (never EXPRESSION - channel-0 hijack);
                  brake fraction ~ decel/g, keep stops <= 0.4; the hold after
                  a stop keeps the SAME brake value (a brake step at zero
                  speed makes the integrator fail at h_max 0.01)
  h_max         : per maneuver - 0.001 for every low-speed maneuver (stops,
                  holds, launches from a dynamic stop, coasts to low speed);
                  the learned FMUs' runs failed only there at 0.01 while the
                  stock run at 0.001 sailed through (2026-09-03 overnight)
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
TOL = 2.5            # km/h end-condition band (proven)
ROAD = (197.0, 0.599, 0.0438)          # repaired road load: N, N/kph, N/kph^2 (Bible 30.10a)
R_WHEEL, G_FRONT = float(_lc.get("wheel_radius_m", 0.39)), float(_lc.get("gear_front", 18.0))
FINE, COARSE = 0.001, 0.01

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

    def _add(self, secs, thr, thr_const, brake, end, note, hmax):
        self.m.append(dict(secs=secs, thr=thr, thr_const=thr_const, brake=brake,
                           end=end, note=note, hmax=hmax))

    def hold(self, secs, brake, hmax=FINE):
        """standstill: pedal 0, brake held (use the SAME brake value as the stop before it)"""
        self._add(secs, "0", True, brake, None, "hold (brake %.2f)" % brake, hmax)

    def pedal(self, secs, target, hold_from="{THROTTLE_0}", delay=1.0, brake=0,
              end=None, note="", hmax=COARSE):
        """open-loop pedal step: hold current pedal `delay` s, then 0.3 s ramp to target (0-1)"""
        expr = "STEP({%%TIME},%g,%s,%g,%.4f)" % (delay, hold_from, delay + 0.3, target)
        self._add(secs, expr, False, brake, end, note or "pedal %.0f%%" % (100*target), hmax)

    def launch(self, secs, target, to_kph, note=""):
        """driveaway from a (dynamic or static) standstill, split in two: a 3 s
        fine-step start (brake release, creep-roll, pedal ramp - where the 10 ms
        runs failed) and the run at the coarse step with the GT end condition.
        A whole family at 1 ms costs ~1.5 min per simulated second (V3-1)."""
        nm = note or "launch %.0f%% to %g" % (100*target, to_kph)
        self.pedal(3, target, hold_from="0", note=nm + " (start, 1 ms)", hmax=FINE)
        expr = "STEP({%%TIME},0,{THROTTLE_0},0.1,%.4f)" % target
        self._add(secs, expr, False, 0, ("GT", to_kph, TOL), nm + " (run)", COARSE)

    def cruise(self, secs, kph):
        """hold speed with the equilibrium pedal (no controller); 0.5 s blend from the current pedal"""
        p = p_eq(kph)
        expr = "STEP({%%TIME},0,{THROTTLE_0},0.5,%.4f)" % p
        self._add(secs, expr, False, 0, None, "cruise %g km/h at p_eq %.1f%%" % (kph, 100*p), COARSE)

    def stop(self, secs, brake):
        """open-loop brake to (near) standstill; fine step; ends in the 0.5-3.5 km/h band"""
        self._add(secs, "0", True, brake, ("LT", 2.0, 1.5), "brake stop %.2f" % brake, FINE)

    def render(self, template):
        head = template[:template.index("[MANEUVERS_LIST]")]
        head = re.sub(r"(VX0\s*=\s*)\S+", r"\g<1>%d" % self.vx0, head)
        head = head.replace("$ Scenario: AVLlit_tipin_50pct - tip-in/out 50% pedal (REGEN-OFF: lift to coast pedal, 5s standstill dwell)",
                            "$ Scenario: %s - AVL-Drive sweep event (generated by sweep_events.py)" % self.name)
        tail = template[re.search(r"\$-+OL_STEER\s*\n\[OL_STEER\]", template).start():]
        out = head
        out += sep("MANEUVERS_LIST") + "[MANEUVERS_LIST]\n{name            simulation_time      h_max           print_interval }\n"
        for i, mv in enumerate(self.m, 1):
            out += "'MANEUVER_%d'     %-20g %-15g 0.01            \n" % (i, mv["secs"], mv["hmax"])
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
    # 1) driveaway family as FOUR separate static-start events. A learned FMU
    #    at a DYNAMIC standstill under brake fails the integrator (its creep
    #    floor pushes against the brake at zero tyre speed - stock has no
    #    creep and survives the same stop/hold); the static start is proven.
    for ped, target in ((0.20, 12), (0.40, 30), (0.70, 40), (1.00, 50)):
        d = Event("sweep_driveaway_%d" % round(100*ped))
        d.hold(5, 0.35)
        d.launch(45, ped, target, note="driveaway %.0f%%" % (100*ped))
        d.pedal(4, 0.00, note="lift after the launch")
        ev.append(d)
    # 2) tip-in / tip-out ladder around equilibrium-pedal cruises (v2 = valid
    #    for all three entrants; kept identical except the tolerance band)
    l = Event("sweep_tipin_ladder")
    l.hold(5, 0.35)
    l.launch(30, 0.35, 30, note="launch 35% to 30")
    l.cruise(15, 30)
    l.pedal(25, 0.50, end=("GT", 50, TOL), note="tip-in 50% at 30")
    l.cruise(15, 50)
    l.pedal(20, 1.00, end=("GT", 80, TOL), note="tip-in 100% at 50")
    l.cruise(15, 80)
    # corrected law: lift-off regen is ~-4 m/s2, a 6 s lift from 80 reaches crawl and
    # the re-tip-in became a launch (failed at 10 ms). Short lift, fine-step tip-in.
    l.pedal(3, 0.00, note="lift-off at 80 (3 s, to ~45 km/h)")
    l.pedal(8, 0.35, note="small tip-in 35% from the lift", hmax=FINE)
    l.pedal(25, 0.70, end=("GT", 100, TOL), note="tip-in 70% to 100")
    l.cruise(15, 100)
    l.pedal(4, 0.00, note="lift-off at 100 (4 s)")
    l.cruise(6, 100)
    ev.append(l)
    # 3) coast-down: static start, lift at 100, re-accelerate from the coast,
    #    moderate stop ends the event in the 0.5-3.5 km/h band (no hold at a
    #    dynamic standstill - see 1)
    c = Event("sweep_coast")
    c.hold(5, 0.35)
    c.launch(40, 0.70, 100, note="launch 70% to 100")
    c.cruise(10, 100)
    c.pedal(150, 0.00, end=("LT", 6, TOL), note="lift at 100, regen coast to ~6 km/h", hmax=FINE)
    c.launch(30, 0.50, 80, note="accelerate 50% to 80 from the coast")
    c.cruise(8, 80)
    c.stop(40, 0.2)
    ev.append(c)
    # 4) braking: static start, launch 40% to 50, cruise, firm stop ends the event
    b = Event("sweep_brake")
    b.hold(5, 0.35)
    b.launch(25, 0.40, 50, note="launch 40% to 50")
    b.cruise(8, 50)
    b.stop(30, 0.4)
    ev.append(b)
    for e in ev:
        p = os.path.join(OUT, e.name + ".adf")
        open(p, "w", encoding="utf-8").write(e.render(T))
        cap = sum(mv["secs"] for mv in e.m)
        fine = sum(mv["secs"] for mv in e.m if mv["hmax"] == FINE)
        print("%-20s %2d maneuvers, time cap %4.0f s (%.0f s at h_max 0.001) -> %s"
              % (e.name, len(e.m), cap, fine, p))


if __name__ == "__main__":
    build()
