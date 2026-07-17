"""
pipeline.py
================================================================================
The sequencing engine of the unified app: scenario (.adf) -> MotionSolve ->
.plt -> MF4 -> viewer, each run in its own self-contained folder.

A run works like this:
  1. A fresh run folder is created under the runs root:
         <runs_dir>/<scenario-name>_<timestamp>/
  2. The solver deck (.xml exported once from MotionView) is COPIED into it,
     renamed to the scenario name (MotionSolve names every output after the
     input deck, so results come out as <scenario>.plt etc.), and PATCHED:
       - relative file references (../../..) are resolved against the deck's
         original folder and rewritten as absolute paths, so the run folder
         can live anywhere;
       - absolute references that don't exist on this machine (e.g. paths
         from another computer) are healed by finding a file with the same
         name next to the source deck, copying it into the run folder and
         rewriting the reference. This is what fixes decks exported on the
         lab machine.
  3. The Scenario Builder's .adf text is written into the run folder under
     the exact file name the deck references ("Driver task file").
  4. The model's .nam companion (request names/units - written by MotionView
     at export time, not by the solver, and scenario-independent) is copied
     in as <scenario>.nam so the PLT converter can find it.
  5. motionsolve.bat runs the deck (subprocess, output streamed line by
     line to the UI).
  6. The fresh .plt is converted to MF4 via the same converter module the
     standalone PLT app uses (converter.py / avl_extract.py / plt_reader.py
     are verbatim copies from plt-to-mf4-app).
  7. The MF4 viewer exe is launched with the new file preloaded.
================================================================================
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

from converter import convert, DEFAULT_PACK_VOLTAGE


def app_dir():
    """Folder the app runs from: exe folder when frozen, source folder
    otherwise. settings.json lives here."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS_PATH = os.path.join(app_dir(), "settings.json")

DEFAULT_SETTINGS = {
    "deck": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\CSV to MDF Converter"
            r"\Test Run For PY Script\Model_Run_doublelane_0.xml",
    "runs_dir": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulation Runs",
    "motionsolve": r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat",
    "viewer": r"C:\Users\George\OneDrive\Desktop\PhD Thesis\CSV to MDF Converter"
              r"\csv-to-mf4-app\dist\MF4Viewer.exe",
    "pack_voltage": DEFAULT_PACK_VOLTAGE,
}


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            settings.update(json.load(fh))
    except (OSError, ValueError):
        pass   # first launch (or broken file): defaults, saved on next change
    return settings


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)


def safe_name(name):
    name = re.sub(r"[^\w\- ]+", "", name).strip().replace(" ", "_")
    return name or "scenario"


# ----------------------------------------------------------------------------
#  Deck patching
# ----------------------------------------------------------------------------

# a token inside a string="..." value that looks like a file path:
# optional drive or ../ climb, then something with an extension we care about
PATH_TOKEN = re.compile(
    r'(?:[A-Za-z]:/|(?:\.\./)+)[^";\r\n]+?\.(?:fmu|mat|tir|rdf|csv|txt|h3d)',
    re.IGNORECASE)

ADF_REF = re.compile(
    r'label\s*=\s*"Driver task file"[\s\S]{0,200}?string\s*=\s*"([^"]+)"')


def patch_deck(deck_text, source_dir, run_dir, log):
    """Rewrite every file reference in the deck so it resolves from run_dir.
    Returns the patched text. Missing files are logged as warnings, not
    fatal - MotionSolve gives the authoritative error if something truly
    can't be found."""

    def fix_token(match):
        token = match.group(0)
        if token.startswith(("../", "..\\")):
            # relative climb: resolve against the deck's ORIGINAL folder
            resolved = os.path.normpath(os.path.join(source_dir, token))
            if os.path.exists(resolved):
                return resolved.replace("\\", "/")
            log("  WARNING: relative ref not found: {} -> {}".format(
                token, resolved))
            return token
        # absolute path: fine if it exists; otherwise heal by file name
        native = token.replace("/", os.sep)
        if os.path.exists(native):
            return token
        base = os.path.basename(native)
        candidate = os.path.join(source_dir, base)
        if os.path.exists(candidate):
            dest = os.path.join(run_dir, base)
            if not os.path.exists(dest):
                shutil.copy2(candidate, dest)
            log("  healed stale path: {} (copied {} into run folder)".format(
                token, base))
            return dest.replace("\\", "/")
        log("  WARNING: referenced file not found anywhere: " + token)
        return token

    return PATH_TOKEN.sub(fix_token, deck_text)


def patch_mass(deck_text, target_kg, log):
    """Adjust total vehicle mass by patching the heaviest rigid body (the
    chassis/ballast body) and scaling its inertia proportionally. This is
    the standard 'ballast' approach - weight distribution shifts slightly
    toward the chassis CG, which is logged so it's never a surprise."""
    bodies = []
    for m in re.finditer(r"<Body_Rigid\b.*?/>", deck_text, re.S):
        mm = re.search(r'\bmass\s*=\s*"([0-9.eE+-]+)"', m.group(0))
        if mm:
            bodies.append((float(mm.group(1)), m.group(0)))
    if not bodies:
        log("  WARNING: no rigid-body masses found - mass not applied")
        return deck_text

    total = sum(b[0] for b in bodies)
    delta = float(target_kg) - total
    if abs(delta) < 0.5:
        log("  vehicle: total mass already {:.1f} kg - nothing to patch"
            .format(total))
        return deck_text

    heaviest_mass, block = max(bodies, key=lambda b: b[0])
    new_mass = heaviest_mass + delta
    if new_mass < 25.0:
        log("  WARNING: mass target {:.0f} kg would drive the chassis body "
            "to {:.1f} kg - not applied".format(target_kg, new_mass))
        return deck_text

    ratio = new_mass / heaviest_mass
    new_block = re.sub(
        r'(\bmass\s*=\s*")[0-9.eE+-]+(")',
        lambda m: "{}{:.6g}{}".format(m.group(1), new_mass, m.group(2)),
        block)
    for attr in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz"):
        new_block = re.sub(
            r'(\b{}\s*=\s*")([0-9.eE+-]+)(")'.format(attr),
            lambda m: "{}{:.6g}{}".format(
                m.group(1), float(m.group(2)) * ratio, m.group(3)),
            new_block)
    log("  vehicle: total mass {:.1f} -> {:.1f} kg (chassis body "
        "{:.1f} -> {:.1f} kg, inertia scaled x{:.3f})".format(
            total, target_kg, heaviest_mass, new_mass, ratio))
    return deck_text.replace(block, new_block, 1)


def patch_gear_ratios(deck_text, spec, log):
    """Patch the per-axle final-drive couplers. Verified against the model:
    the 'Pinion to Carrier (final drive ratio)' coupler coefficient IS the
    complete motor->wheel reduction (measured EM/wheel speed ratio == the
    coefficient). Front coupler = lower id, rear = higher; the coefficient
    sign encodes rotation direction and is preserved."""
    motors = (spec.get("motors") or [])[:int(spec.get("motorCount") or 1)]
    ratios = [float(m.get("gearRatio") or 0) for m in motors]
    if not ratios:
        return deck_text
    if len(ratios) == 1:
        ratios = ratios * 2   # single-motor spec on a dual-axle deck

    couplers = [(int(re.search(r'\bid\s*=\s*"(\d+)"', m.group(0)).group(1)),
                 m.group(0))
                for m in re.finditer(r"<Constraint_Coupler\b.*?/>", deck_text, re.S)
                if re.search(r'label\s*=\s*"[^"]*final drive[^"]*"',
                             m.group(0), re.I)]
    if not couplers:
        log("  WARNING: no 'final drive ratio' couplers in the deck - gear "
            "ratios not applied")
        return deck_text
    couplers.sort()   # front axle first (lower id)

    old_ratios = [None, None]
    for i, ((cid, block), ratio, axle) in enumerate(
            zip(couplers, ratios, ("front", "rear"))):
        if ratio <= 0:
            log("  WARNING: {} gear ratio {} invalid - skipped".format(axle, ratio))
            continue
        cm = re.search(r'coefficients\s*=\s*"([^"]+)"', block)
        parts = cm.group(1).split()
        old = float(parts[-1])
        old_ratios[i] = abs(old)
        parts[-1] = "{:.6g}".format(ratio if old >= 0 else -ratio)
        new_block = block.replace(cm.group(0),
                                  'coefficients            = "{}"'.format(" ".join(parts)))
        deck_text = deck_text.replace(block, new_block, 1)
        log("  vehicle: {} final drive {:.4g}:1 -> {:.4g}:1 (coupler {})".format(
            axle, abs(old), ratio, cid))

    # The couplers only constrain the shaft kinematics. The POWER path is
    # expression-based: 'Torque from Gear Box' (FMU torque * ratio * gear
    # spline * 0.99) and 'Gear Box Input Staft Speed' (wheel speed * ratio)
    # embed the same ratio as a literal - patch those too, or the motor
    # never feels the new gearing. Front/rear told apart by the marker /
    # spline ids inside the expression.
    n_expr = 0
    for m in list(re.finditer(
            r'<Reference_Variable\b[^>]*?label\s*=\s*"(?:Torque from Gear Box'
            r'|Gear Box Input Staft Speed)"[^>]*?/>', deck_text, re.S)):
        block = m.group(0)
        if re.search(r"336001|3640\d+", block):
            idx = 0
        elif re.search(r"340001|3650\d+", block):
            idx = 1
        else:
            log("  WARNING: gearbox expression with unknown axle - skipped")
            continue
        ratio, old = ratios[idx], old_ratios[idx]
        if ratio <= 0 or old is None:
            continue
        pattern = r"\*\s*{}\s*\*".format(re.escape("{:g}".format(old)))
        if not re.search(pattern, block):
            log("  WARNING: ratio literal {:g} not found in gearbox "
                "expression - not patched".format(old))
            continue
        new_block = re.sub(pattern, "*{:.6g}*".format(ratio), block)
        if new_block != block:   # unchanged text = ratio already correct
            deck_text = deck_text.replace(block, new_block, 1)
        n_expr += 1
    if n_expr:
        log("  vehicle: {} gearbox torque/speed expressions re-geared".format(n_expr))
    return deck_text


def apply_vehicle(vehicle, deck_text, source_dir, run_dir, log):
    """Apply the Vehicle Builder's ⚡ overrides to this run:
    - tire_path: every .tir reference in the deck is re-pointed at it;
    - mat_overrides {original basename: replacement}: the replacement file
      is copied into the run folder UNDER THE ORIGINAL NAME, shadowing the
      healed copy of the deck default;
    - the full vehicle spec is written to vehicle.json for provenance.
    Returns the (possibly modified) deck text."""
    if not vehicle:
        return deck_text

    # vehicle manifest: what car this run actually uses, stated up front
    spec0 = vehicle.get("spec") or {}
    if spec0:
        log("  ================ VEHICLE ================")
        log("  {}   {}".format(spec0.get("name", "unnamed"),
                               spec0.get("serial", "")))
        for i, m in enumerate((spec0.get("motors") or [])
                              [:int(spec0.get("motorCount") or 1)]):
            log("    motor {}: {}  {} kW / {} Nm / {} rpm, drive {}:1{}".format(
                i + 1, m.get("name", "?"), m.get("powerKW"), m.get("torqueNm"),
                m.get("maxRpm"), m.get("gearRatio"),
                "" if vehicle.get("generate_motors")
                else "  [NOT APPLIED - generation off]"))
        log("    mass: {} kg{}".format(
            spec0.get("massKg"),
            "" if vehicle.get("apply_mass") else "  [NOT APPLIED - toggle off]"))
        log("    tire: {}".format(
            os.path.basename(vehicle.get("tire_path") or "") or "deck default"))
        log("    pack voltage: {} V".format(vehicle.get("pack_voltage")))
        ems0 = vehicle.get("ems") or {}
        log("    EMS: {}".format(
            ems0.get("strategy", "deck_default")
            if ems0.get("enabled") else "deck default (builder off)"))
        log("  =========================================")

    tire = vehicle.get("tire_path")
    if tire:
        if os.path.isfile(tire):
            deck_text = re.sub(
                r'(?:[A-Za-z]:/|(?:\.\./)+)[^";\r\n]+?\.tir',
                tire.replace("\\", "/"), deck_text, flags=re.IGNORECASE)
            log("  vehicle: tire file -> " + os.path.basename(tire))
        else:
            log("  WARNING: tire override not found, using deck default: " + tire)

    spec = vehicle.get("spec") or {}

    # generated motor files (⚡): specs + optional uploaded efficiency maps
    # become the actual FMU parameter files for this run
    if vehicle.get("generate_motors") and spec.get("motors"):
        log("  generating motor parameter files from vehicle spec:")
        import motor_gen
        motor_gen.generate_motor_files(spec, run_dir, log=log)
        deck_text = patch_gear_ratios(deck_text, spec, log)

    # explicit whole-file overrides win over generated files
    for base, path in (vehicle.get("mat_overrides") or {}).items():
        base = os.path.basename(base)
        if path and os.path.isfile(path):
            shutil.copy2(path, os.path.join(run_dir, base))
            log("  vehicle: {} -> {}".format(base, path))
        else:
            log("  WARNING: override for {} not found, using deck default: {}"
                .format(base, path))

    # chassis-ballast mass patch (⚡)
    if vehicle.get("apply_mass") and spec.get("massKg"):
        deck_text = patch_mass(deck_text, spec["massKg"], log)

    # energy-management strategy (⚡): regenerate the torque-split map
    # (optimal_torque_ratio_map). Verified consumed by the FMU at vcu_type=4.
    if (vehicle.get("ems") or {}).get("enabled"):
        import ems_builder
        motors = (spec.get("motors") or [])[:int(spec.get("motorCount") or 1)]
        ems_builder.apply_ems(vehicle["ems"], run_dir, motors, log=log)

    spec = vehicle.get("spec")
    if spec:
        with open(os.path.join(run_dir, "vehicle.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(spec, fh, indent=2)
        log("  vehicle spec recorded: vehicle.json")
    return deck_text


def prepare_run(settings, scenario_name, adf_text, log, vehicle=None):
    """Set up a self-contained run folder. Returns (run_dir, deck_name)."""
    deck_src = settings["deck"]
    if not os.path.isfile(deck_src):
        raise FileNotFoundError("Solver deck not found: " + deck_src)
    source_dir = os.path.dirname(os.path.abspath(deck_src))

    stem = safe_name(scenario_name)
    run_dir = os.path.join(settings["runs_dir"],
                           "{}_{}".format(stem, time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(run_dir)
    log("Run folder: " + run_dir)

    with open(deck_src, encoding="utf-8", errors="replace") as fh:
        deck_text = fh.read()

    adf_match = ADF_REF.search(deck_text)
    if not adf_match:
        raise ValueError(
            "The deck has no 'Driver task file' reference - is this a model "
            "that uses Altair Driver?")
    adf_name = os.path.basename(adf_match.group(1))

    deck_text = patch_deck(deck_text, source_dir, run_dir, log)
    deck_text = apply_vehicle(vehicle, deck_text, source_dir, run_dir, log)

    deck_name = stem + ".xml"
    with open(os.path.join(run_dir, deck_name), "w", encoding="utf-8") as fh:
        fh.write(deck_text)

    with open(os.path.join(run_dir, adf_name), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(adf_text)
    log("Scenario written as {} (the name the deck references)".format(adf_name))

    # .nam companion: comes from the MotionView export, lists the model's
    # request names/units, does not depend on the scenario. Renamed to the
    # new deck stem so converter.find_nam picks it up next to the .plt.
    nam_src = os.path.splitext(deck_src)[0] + ".nam"
    if os.path.isfile(nam_src):
        shutil.copy2(nam_src, os.path.join(run_dir, stem + ".nam"))
    else:
        log("  WARNING: no .nam next to the source deck ({}). The PLT->MF4 "
            "step will fail without one.".format(os.path.basename(nam_src)))

    return run_dir, deck_name


# ----------------------------------------------------------------------------
#  Solver + conversion
# ----------------------------------------------------------------------------

def total_sim_time(adf_text):
    """Sum of the maneuver time caps in [MANEUVERS_LIST] - the upper bound
    of simulated time (end conditions can finish a maneuver earlier)."""
    block = re.search(r"\[MANEUVERS_LIST\][\s\S]*?(?=\$-|\Z)", adf_text)
    if not block:
        return None
    times = re.findall(r"^\s*'[^']+'\s+([0-9.]+)", block.group(0), re.M)
    total = sum(float(t) for t in times)
    return total or None


# transient integration step lines look like:  Time=1.077E+01; Order=3; ...
TIME_LINE = re.compile(r"^\s*Time=([0-9.Ee+-]+);")


def run_motionsolve(settings, run_dir, deck_name, log,
                    progress=None, sim_total=None, proc_holder=None):
    """Run the solver, streaming its output. `progress(fraction, text)` is
    fed from the solver's own Time= lines against the scenario's total
    simulated time. The Popen object is published through `proc_holder`
    so the UI's Stop button can taskkill the whole tree. Raises on failure."""
    bat = settings["motionsolve"]
    if not os.path.isfile(bat):
        raise FileNotFoundError("motionsolve.bat not found: " + bat)

    log("Launching MotionSolve (headless - no window will appear)...")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [bat, deck_name], cwd=run_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1,
        creationflags=creationflags)
    if proc_holder is not None:
        proc_holder["proc"] = proc
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        log(line)
        if progress and sim_total:
            m = TIME_LINE.match(line)
            if m:
                try:
                    t = float(m.group(1))
                except ValueError:
                    continue
                if t > 0:
                    progress(min(t / sim_total, 1.0),
                             "solving… t = {:.2f} / {:.0f} s (sum of phase "
                             "caps — finishes early when exit conditions "
                             "are met)".format(t, sim_total))
    code = proc.wait()
    if proc_holder is not None:
        proc_holder["proc"] = None
    if code != 0:
        raise RuntimeError("MotionSolve exited with code {}".format(code))

    plt_path = os.path.join(run_dir, os.path.splitext(deck_name)[0] + ".plt")
    if not os.path.isfile(plt_path):
        raise RuntimeError(
            "Solver finished but wrote no .plt - check the log above "
            "(license? early abort?)")
    return plt_path


def deck_info(settings):
    """What model is this? Inspect the solver deck and report the vehicle-
    defining ingredients: the FMUs (controllers/motors), the .mat motor
    parameter files, and the tire property file, plus .nam presence."""
    deck = settings.get("deck", "")
    info = {"deck": deck, "exists": os.path.isfile(deck)}
    if not info["exists"]:
        return info
    info["modified"] = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(deck)))
    info["nam_ok"] = os.path.isfile(os.path.splitext(deck)[0] + ".nam")
    try:
        with open(deck, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return info
    tokens = {m.group(0) for m in PATH_TOKEN.finditer(text)}
    def names(ext):
        return sorted({os.path.basename(t.replace("\\", "/")) for t in tokens
                       if t.lower().endswith(ext)})
    info["fmus"] = names(".fmu")
    info["mats"] = names(".mat")
    info["tires"] = names(".tir")
    return info


def kill_process_tree(pid, log=None):
    """Kill a process and ALL its descendants, children first.

    taskkill /T can lose the race walking the tree (killing a parent
    before enumerating its children orphans the grandchildren - observed
    with tclsh -> msolve -> mbd_d). psutil snapshots the whole descendant
    list up front, so nothing escapes."""
    import psutil
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = root.children(recursive=True) + [root]
    for p in procs:
        try:
            if log:
                log("  killing {} (pid {})".format(p.name(), p.pid))
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=10)


def launch_viewer(settings, mf4_path, log):
    viewer = settings["viewer"]
    if os.path.isfile(viewer):
        subprocess.Popen([viewer, mf4_path])
        log("Viewer launched with " + os.path.basename(mf4_path))
    else:
        log("WARNING: viewer exe not found ({}) - open the MF4 manually."
            .format(viewer))


def run_scenario(settings, scenario_name, adf_text, log, progress=None,
                 proc_holder=None, viewer_launcher=None, vehicle=None):
    """The full sequence. Returns (run_dir, mf4_path). Raises on failure.

    progress(fraction 0..1 or None, text) drives the UI progress bar;
    None as the fraction means 'indeterminate' (setup/conversion phases).
    proc_holder exposes the solver Popen for the Stop button.
    viewer_launcher(mf4_path) opens the results (defaults to the external
    viewer exe from settings when not given).
    """
    def report(frac, text):
        if progress:
            progress(frac, text)

    t0 = time.time()
    report(None, "preparing run folder…")
    run_dir, deck_name = prepare_run(settings, scenario_name, adf_text, log,
                                     vehicle=vehicle)
    report(0.0, "starting MotionSolve…")
    plt_path = run_motionsolve(settings, run_dir, deck_name, log,
                               progress=progress,
                               sim_total=total_sim_time(adf_text),
                               proc_holder=proc_holder)
    log("")
    report(1.0, "converting to MF4…")
    log("Converting {} to MF4...".format(os.path.basename(plt_path)))
    # vehicle serial -> constant VehicleSerial channel in the MF4, so the
    # result file itself proves which vehicle config produced it
    serial_number = None
    serial_text = ((vehicle or {}).get("spec") or {}).get("serial", "")
    digits = re.sub(r"\D", "", str(serial_text))
    if digits:
        serial_number = int(digits)
    mf4_path = convert(plt_path, log=log,
                       pack_voltage=float(settings.get(
                           "pack_voltage", DEFAULT_PACK_VOLTAGE)),
                       serial_number=serial_number)
    if viewer_launcher is False:
        log("Viewer not opened (batch mode).")
    elif viewer_launcher is not None:
        viewer_launcher(mf4_path)
        log("Viewer opened with " + os.path.basename(mf4_path))
    else:
        launch_viewer(settings, mf4_path, log)
    elapsed = time.time() - t0
    report(1.0, "done in {:.0f} s".format(elapsed))
    log("Pipeline finished in {:.0f} s.".format(elapsed))
    return run_dir, mf4_path
