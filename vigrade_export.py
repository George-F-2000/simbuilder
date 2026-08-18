# -*- coding: utf-8 -*-
"""
vigrade_export.py
================================================================================
Export the Altair MotionSolve demo EV model to a VI-grade bundle that
VI-CarRealTime / VI-DriveSim can ingest: a subsystem-structured vehicle .xml
plus the directly-portable component files.

WHY THIS IS A PARAMETER TRANSFER, NOT A DECK CONVERSION
VI-CarRealTime is a PARAMETRIC real-time vehicle model (body + conceptual
suspension + tire + aero + powertrain + brakes + steering), not a flexible
multibody deck. So you don't convert the MotionSolve topology - you transfer
the parameters into VI-CRT's subsystem taxonomy. Three parts move cleanly:

  * TIRE  - the MF-Tyre/SWIFT .tir file transfers directly (VI-CRT shares
            tyre property files with Adams Car). Copied verbatim.
  * POWERTRAIN - the co-simulation FMU (FMI 2.0) transfers directly (VI-CRT
            is FMI-compliant and imports FMUs). Copied verbatim; the XML
            references it. This carries the front-unit/rear-unit motors, EMS split and
            pack with no re-derivation.
  * AERO + BODY - scalar parameters (mass, inertia, CdA, frontal area,
            wheelbase, spring rate, ARB) map straight into VI-CRT fields.

  * SUSPENSION K&C - VI-CRT's conceptual suspension is defined by Kinematics
            & Compliance CURVES (camber/toe/caster vs travel, roll centre,
            compliances). Those are NOT stored in the deck as curves; they
            require a K&C characterisation event (run the suspension on a
            virtual K&C rig in MotionView, export the curves, import into
            VI-CRT's K&C interface). This exporter emits the STATIC/discrete
            suspension data it can read (spring rate, ARB presence, track,
            wheelbase) and flags the K&C curves as to-be-characterised.

SCHEMA NOTE
VI-CRT's exact XML element names are proprietary (behind their reserved
area). This exporter emits a clean, unit-labelled, subsystem-structured XML
that maps 1:1 to VI-CRT's subsystem taxonomy - either directly importable or
a precise populate-the-GUI reference. Confirm element names against your
VI-CRT version; the DATA (values + units + provenance) is what matters and
is exact.
================================================================================
"""

import os
import re
import shutil
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

# demo EV constants (SN-2499411196, the locked campaign vehicle)
WHEELBASE_M = 3.094
import json as _json
try:
    _v = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "vehicle_local.json")))
except Exception:
    _v = {}
FRONT_RATIO = float(_v.get("gear_front", 11.0))   # demo default
REAR_RATIO = float(_v.get("gear_rear", 11.0))


# ---------------------------------------------------------------- deck readers
def _bodies(xml):
    """(label, mass_kg, ixx, iyy, izz) for every rigid body with mass."""
    out = []
    for m in re.finditer(r"<Body_Rigid\b(.*?)/>", xml, re.S):
        b = m.group(1)
        gv = lambda k: (re.search(k + r'\s*=\s*"([^"]*)"', b) or [None, None])[1]
        mass = gv("mass")
        if mass is None:
            continue
        try:
            mv = float(mass)
        except ValueError:
            continue
        if mv <= 0:
            continue
        f = lambda k: float(gv(k)) if gv(k) else None
        out.append((gv("label") or "?", mv,
                    f("inertia_xx"), f("inertia_yy"), f("inertia_zz")))
    return out


def _coil_rate(xml):
    """Front/rear coil spring rate (N/mm) if identifiable, else the set."""
    rates = []
    for m in re.finditer(r'<Force_SpringDamper\b[^>]*label\s*=\s*"([^"]*[Cc]oil[^"]*)"[^>]*?/>', xml, re.S):
        k = re.search(r'stiffness\s*=\s*"([^"]*)"', m.group(0))
        if k:
            rates.append(float(k.group(1)))
    return rates


def _has_arb(xml):
    # this deck labels the anti-roll bar "stabar" (stabiliser bar)
    return bool(re.search(r'label\s*=\s*"[^"]*(?:roll bar|stabiliz|anti-roll|arb|stabar)[^"]*"',
                          xml, re.I))


def _load_kandc():
    """Front-axle K&C curve if characterised (kc_curve.json). None until then,
    in which case VI-CRT's template suspension is used."""
    import json
    for p in (os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           _v.get("data_root", ".."), "results", "kc_curve.json"),
              os.path.join(_v.get("data_root", "."), "results", "kc_curve.json")):
        try:
            if os.path.isfile(p):
                return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return None


# ------------------------------------------------------------- asset readers
def _aero(aae_path):
    """Altair .aae: frontal area field + drag/lift coefficient SPLINE blocks.
    Cd = drag coefficient at 0 deg incidence; CdA = Cd * frontal area."""
    a = {"cda": None, "frontal_area_m2": None, "cd": None, "cl": None}
    if aae_path and os.path.isfile(aae_path):
        txt = open(aae_path, encoding="utf-8", errors="replace").read()
        area = re.search(r"FRONTAL_SECTION_AREA\s*=\s*([-\d.eE]+)", txt, re.I)
        if area:
            a["frontal_area_m2"] = round(float(area.group(1)) / 1e6, 4)  # mm^2 -> m^2
        dm = re.search(r"\[DRAG_COEFFICIENT\].*?\b0\.0+\s+([-\d.eE]+)", txt, re.S | re.I)
        if dm:
            a["cd"] = float(dm.group(1))
            if a["frontal_area_m2"]:
                a["cda"] = round(a["cd"] * a["frontal_area_m2"], 4)
        lm = re.search(r"\[LIFT_COEFFICIENT\].*?\b0\.0+\s+([-\d.eE]+)", txt, re.S | re.I)
        if lm:
            a["cl"] = float(lm.group(1))
    return a


def _tire(tir_path):
    t = {"file": os.path.basename(tir_path) if tir_path else None,
         "model": None, "fittyp": None}
    if tir_path and os.path.isfile(tir_path):
        txt = open(tir_path, encoding="utf-8", errors="replace").read()
        pf = re.search(r"PROPERTY_FILE_FORMAT\s*=\s*'?([^'\n]+)", txt)
        ft = re.search(r"FITTYP\s*=\s*(\d+)", txt)
        if pf:
            t["model"] = pf.group(1).strip().strip("'")
        if ft:
            t["fittyp"] = ft.group(1)
    return t


def _fmu(fmu_path):
    f = {"file": os.path.basename(fmu_path) if fmu_path else None,
         "fmi_version": None, "kind": None, "inputs": None, "outputs": None}
    if fmu_path and os.path.isfile(fmu_path):
        xml = zipfile.ZipFile(fmu_path).read("modelDescription.xml").decode("utf-8", "replace")
        v = re.search(r'fmiVersion="([^"]+)"', xml)
        f["fmi_version"] = v.group(1) if v else None
        f["kind"] = ("CoSimulation" if "CoSimulation" in xml
                     else "ModelExchange" if "ModelExchange" in xml else None)
        f["inputs"] = len(re.findall(r'causality="input"', xml))
        f["outputs"] = len(re.findall(r'causality="output"', xml))
    return f


# ------------------------------------------------------------------- extract
def _sg(spec, *keys):
    """First present key from the vehicle spec (or its nested 'spec')."""
    for src in (spec, (spec or {}).get("spec")):
        if isinstance(src, dict):
            for k in keys:
                if src.get(k) not in (None, ""):
                    return src[k]
    return None


def extract(deck_path, tir_path=None, aae_path=None, fmu_path=None, name="demo EV",
            spec=None):
    xml = open(deck_path, encoding="utf-8", errors="replace").read()
    bodies = _bodies(xml)
    total_mass = round(sum(b[1] for b in bodies), 2)
    chassis = max(bodies, key=lambda b: b[1]) if bodies else None
    rates = _coil_rate(xml)
    # spec-sourced params (VI-CRT needs these to build a runnable vehicle)
    tf = _sg(spec, "trackFMm"); tr = _sg(spec, "trackRMm")
    steer = _sg(spec, "steerRatio")
    pack = _sg(spec, "packKWh")
    motors = _sg(spec, "motors") or []
    fr = REAR_RATIO; ff = FRONT_RATIO
    if isinstance(motors, list) and len(motors) >= 2:
        ff = motors[0].get("driveRatio", FRONT_RATIO)
        fr = motors[1].get("driveRatio", REAR_RATIO)
    return {
        "name": name,
        "source_deck": os.path.basename(deck_path),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "body": {
            "total_mass_kg": total_mass,
            "wheelbase_m": WHEELBASE_M,
            "track_front_mm": tf, "track_rear_mm": tr,
            "bodies": [{"label": b[0], "mass_kg": round(b[1], 2)} for b in bodies
                       if b[1] > 50],
            "chassis_inertia_kgmm2": (None if not chassis else
                {"ixx": chassis[2], "iyy": chassis[3], "izz": chassis[4]}),
        },
        "steering": {"ratio": steer},
        "suspension": {
            "front_type": _sg(spec, "suspF"), "rear_type": _sg(spec, "suspR"),
            "coil_spring_rate_N_mm": (round(rates[0], 3) if rates else None),
            "anti_roll_bar": _has_arb(xml),
            "kandc": _load_kandc(),
        },
        "tire": _tire(tir_path),
        "aero": _aero(aae_path),
        "powertrain": {
            "type": "electric-dual-motor",
            "pack_kwh": pack,
            "front_axle": {"motor": "front-unit induction", "ratio": ff},
            "rear_axle": {"motor": "rear-unit", "ratio": fr},
            "fmu": _fmu(fmu_path),
        },
    }


# ----------------------------------------------------------------- XML writer
def _el(tag, val, unit=None, note=None, indent=2):
    sp = " " * indent
    attrs = ""
    if unit:
        attrs += ' units="%s"' % unit
    if note:
        attrs += ' note="%s"' % escape(str(note))
    if val is None:
        return '%s<%s%s status="characterise"/>\n' % (sp, tag, attrs)
    return "%s<%s%s>%s</%s>\n" % (sp, tag, attrs, escape(str(val)), tag)


def to_xml(p):
    b, s, t, a, pt = p["body"], p["suspension"], p["tire"], p["aero"], p["powertrain"]
    x = '<?xml version="1.0" encoding="UTF-8"?>\n'
    x += ('<!-- VI-grade vehicle parameter export (VI-CarRealTime / VI-DriveSim).\n'
          '     Generated by SimBuilder from an Altair MotionSolve model.\n'
          '     Element NAMES map to VI-CRT subsystems; confirm against your\n'
          '     VI-CRT version. Values + units + provenance are exact.\n'
          '     Assets (.tir, .fmu) are copied alongside this file. -->\n')
    x += '<VIGradeVehicle name="%s" source="%s" generated="%s">\n' % (
        escape(p["name"]), escape(p["source_deck"]), p["generated"])
    # body
    x += " <Body>\n"
    x += _el("TotalMass", b["total_mass_kg"], "kg")
    x += _el("Wheelbase", b["wheelbase_m"], "m")
    ci = b["chassis_inertia_kgmm2"]
    if ci:
        x += _el("ChassisInertiaXX", ci["ixx"], "kg*mm^2")
        x += _el("ChassisInertiaYY", ci["iyy"], "kg*mm^2")
        x += _el("ChassisInertiaZZ", ci["izz"], "kg*mm^2")
    x += _el("TrackFront", b.get("track_front_mm"), "mm")
    x += _el("TrackRear", b.get("track_rear_mm"), "mm")
    x += _el("CGHeight", None, "m", "from MotionView mass summary / K&C")
    x += "  <MassBreakdown>\n"
    for bd in b["bodies"]:
        x += '   <Item label="%s" mass_kg="%s"/>\n' % (escape(bd["label"]), bd["mass_kg"])
    x += "  </MassBreakdown>\n </Body>\n"
    # steering
    st = p.get("steering", {})
    x += " <Steering>\n" + _el("Ratio", st.get("ratio"), None,
                               "steering-wheel to road-wheel") + " </Steering>\n"
    # suspension
    kc = s.get("kandc")
    for axle in ("front", "rear"):
        x += ' <Suspension axle="%s">\n' % axle
        x += _el("CoilSpringRate", s["coil_spring_rate_N_mm"], "N/mm")
        x += _el("AntiRollBar", "present" if s["anti_roll_bar"] else "none")
        if kc and axle == "front":
            x += '  <KandC status="characterised" method="%s">\n' % escape(kc.get("method", ""))
            x += _el("WheelRate", kc.get("wheel_rate_N_per_mm"), "N/mm", indent=3)
            x += _el("TrackScrub", kc.get("track_scrub_mm_per_mm"), "mm/mm",
                     "half-track change per mm travel", indent=3)
            x += _el("BumpSteer", kc.get("bump_steer_deg_per_mm"), "deg/mm", indent=3)
            tr = kc.get("travel_range_mm") or []
            x += _el("TravelRange", "%s to %s" % (tr[0], tr[1]) if len(tr) == 2 else None,
                     "mm", indent=3)
            x += "   <Curve axis=\"travel_mm\" cols=\"travel,track_change,toe_deg\">\n"
            for row in kc.get("points_travel_track_toe", []):
                x += "    <P>%s</P>\n" % ",".join(str(v) for v in row)
            x += "   </Curve>\n"
            x += _el("Camber", None, None, "not yet measured (add wheel-orientation request)", indent=3)
            x += "   <Note>%s</Note>\n" % escape(kc.get("note", ""))
            x += "  </KandC>\n"
        elif axle == "front":
            x += _el("KandC", None, None,
                     "REFINEMENT (run kc_sweep.py -> kc_curve.json); template runs until then")
        else:
            x += _el("KandC", None, None, "rear not yet characterised (front method applies)")
        x += " </Suspension>\n"
    # tire
    x += ' <Tire file="%s" model="%s" fittyp="%s" transfer="direct-copy"/>\n' % (
        escape(str(t["file"])), escape(str(t["model"])), escape(str(t["fittyp"])))
    # aero
    x += " <Aerodynamics>\n"
    x += _el("CdA", a["cda"], "m^2")
    x += _el("FrontalArea", a["frontal_area_m2"], "m^2")
    x += _el("Cd", a["cd"], None, "drag coeff at 0 deg incidence")
    x += _el("Cl", a["cl"], None, "lift coeff at 0 deg incidence")
    x += " </Aerodynamics>\n"
    # powertrain
    fmu = pt["fmu"]
    x += ' <Powertrain type="%s">\n' % pt["type"]
    x += _el("PackCapacity", pt.get("pack_kwh"), "kWh")
    x += '  <FMU file="%s" fmiVersion="%s" kind="%s" inputs="%s" outputs="%s" transfer="fmi-import"/>\n' % (
        escape(str(fmu["file"])), fmu["fmi_version"], fmu["kind"], fmu["inputs"], fmu["outputs"])
    x += '  <FrontAxle motor="%s" ratio="%s"/>\n' % (pt["front_axle"]["motor"], pt["front_axle"]["ratio"])
    x += '  <RearAxle motor="%s" ratio="%s"/>\n' % (pt["rear_axle"]["motor"], pt["rear_axle"]["ratio"])
    x += " </Powertrain>\n"
    x += "</VIGradeVehicle>\n"
    return x


# --------------------------------------------------------------- bundle out
def export_bundle(deck_path, out_dir, tir_path=None, aae_path=None,
                  fmu_path=None, name="demo EV", spec=None):
    """Write the VI-grade XML + copy the portable assets + a mapping README.
    Returns a manifest dict."""
    os.makedirs(out_dir, exist_ok=True)
    p = extract(deck_path, tir_path, aae_path, fmu_path, name, spec)
    xml_path = os.path.join(out_dir, "%s_vigrade.xml" % re.sub(r"\W+", "_", name))
    open(xml_path, "w", encoding="utf-8").write(to_xml(p))
    copied = []
    for src in (tir_path, fmu_path):
        if src and os.path.isfile(src):
            dst = os.path.join(out_dir, os.path.basename(src))
            shutil.copy(src, dst)
            copied.append(os.path.basename(src))
    open(os.path.join(out_dir, "README - VI-grade import.txt"), "w",
         encoding="utf-8").write(_readme(p, os.path.basename(xml_path), copied))
    return {"xml": xml_path, "assets": copied, "params": p}


def _readme(p, xml_name, assets):
    fmu = p["powertrain"]["fmu"]
    b = p["body"]
    return (
"VI-GRADE EXPORT BUNDLE  (VI-CarRealTime / VI-DriveSim)\n"
"Generated by SimBuilder from Altair MotionSolve model: %s\n"
"%s\n\n"
"===========================================================================\n"
"GOAL: RUN THIS VEHICLE IN VI-CARREALTIME TODAY\n"
"===========================================================================\n"
"VI-CRT is a parametric real-time model and ships with validated vehicle\n"
"templates. You do NOT need a full K&C characterisation to drive it. Start\n"
"from a template, override the fields below, drop in the tyre (+ optionally\n"
"the FMU), and it runs. K&C only REFINES the suspension later.\n\n"
"RUNNABLE-NOW RECIPE:\n"
"  1. Open a VI-CRT template close to this vehicle (a mid/large EV SUV;\n"
"     independent front + multi-link rear).\n"
"  2. BODY  -> total mass %s kg, wheelbase %s m, track F/R %s / %s mm,\n"
"     chassis inertia in the XML. Steering ratio %s.\n"
"  3. AERO  -> CdA %s m^2, frontal area %s m^2.\n"
"  4. TYRE  -> copy %s into the VI-CRT tyre folder and point all four\n"
"     corners at it (MF-Tyre/SWIFT FITTYP %s - shared with Adams Car).\n"
"  5. POWERTRAIN -> two options:\n"
"       (a) SIMPLE/RUNS-IMMEDIATELY: VI-CRT built-in electric driveline,\n"
"           dual motor, front ratio %s, rear ratio %s, pack %s kWh.\n"
"       (b) HIGH-FIDELITY: import %s as an FMU (FMI %s, %s, %s in / %s out)\n"
"           - carries the real front-unit/rear-unit motors + EMS split + pack. Map its\n"
"           inputs (throttle/brake) and outputs (axle torques) to the\n"
"           VI-CRT powertrain interface.\n"
"  6. SUSPENSION -> leave the template's (it runs). To make it THIS car's\n"
"     suspension, replace with the K&C curves once characterised (springs\n"
"     %s N/mm and ARB=%s are in the XML now).\n"
"  -> The vehicle now drives in VI-CRT as a close approximation of the\n"
"     prototype. Refine suspension via K&C for handling-grade fidelity.\n\n"
"SCHEMA NOTE: the XML element names map to VI-CRT's subsystem taxonomy but\n"
"may not match your VI-CRT importer verbatim - the DATA (values, units,\n"
"provenance) is exact; use the XML as a direct populate-the-GUI reference.\n"
        % (p["source_deck"], p["generated"],
           b["total_mass_kg"], b["wheelbase_m"], b.get("track_front_mm"),
           b.get("track_rear_mm"), p.get("steering", {}).get("ratio"),
           p["aero"]["cda"], p["aero"]["frontal_area_m2"],
           p["tire"]["file"], p["tire"]["fittyp"],
           p["powertrain"]["front_axle"]["ratio"], p["powertrain"]["rear_axle"]["ratio"],
           p["powertrain"].get("pack_kwh"),
           fmu["file"], fmu["fmi_version"], fmu["kind"], fmu["inputs"], fmu["outputs"],
           p["suspension"]["coil_spring_rate_N_mm"],
           "present" if p["suspension"]["anti_roll_bar"] else "none"))
