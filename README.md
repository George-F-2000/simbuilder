# SimBuilder (unified app)

One seamless flow in ONE executable: **define the vehicle → build a
scenario → RUN IN MOTIONSOLVE (live log + progress bar + STOP button) →
PLT→MF4 → viewer opens with the results.** The MF4 viewer and the PLT→MF4
converter are inside the same exe, reachable from the header buttons.

## One exe, multiple processes

`dist\SimBuilder.exe` dispatches on its own command line and relaunches
itself for the tkinter tools (pywebview and tkinter each need their own GUI
loop - the Chrome multi-process pattern):

```
SimBuilder.exe                     builder + pipeline (default)
SimBuilder.exe --viewer [x.mf4 …]  MF4 viewer
SimBuilder.exe --plt-converter     PLT→MF4 converter
```

The "MF4 Viewer" / "PLT → MF4" header buttons and the automatic
viewer-on-finish all spawn the exe this way. Copy the single exe anywhere -
all four tools travel together. (The standalone exes in csv-to-mf4-app and
plt-to-mf4-app still exist and work; this bundles the same code.)

## The two tabs

**Vehicle Builder** (first tab) - defines the car every run uses; the chip
next to RUN IN MOTIONSOLVE ("runs vehicle: <name>") is the reminder.

**Scenario Builder** - phase-based maneuver definition, point-mass preview,
live .adf generation (unchanged).

**🏁 Run deck as-is (model validation)** — the master toggle at the top of
the Vehicle card. When on, EVERY ⚡ override below is skipped and the model
runs exactly as exported from MotionView (only the scenario, path healing
and XML safety touch the run). Use it when overlaying the stock model on
real drive data; the run manifest states the mode and the serial changes
with it.

**Vehicle Builder** - the vehicle's spec sheet plus the pipeline's
per-run overrides, with two honestly-labelled kinds of fields:

- **⚡ affects sim** - injected into every run:
  - **Motor specs** (peak power/torque/max rpm): with "Write these specs
    into the motor parameter files" checked, motor_gen.py generates the
    FMU's .mat files from the fields - torque/power envelope, corner-speed
    ratings, and the efficiency map (uploaded per motor as a CSV grid or
    .mat, re-interpolated onto the model's 15x14 grid; synthetic PMSM map
    when none is uploaded).
  - **Drive ratios**: each motor card's ratio patches that axle's
    "final drive ratio" coupler in the deck - verified to be the complete
    motor→wheel reduction (measured EM/wheel speed equals the coefficient).
  - **Mass**: with "Apply mass to the model" checked, the run's deck is
    patched - the heaviest rigid body (chassis ballast) absorbs the
    difference and its inertia scales proportionally.
  - **Tire property file** (every .tir reference in the deck re-pointed),
    per-file **.mat overrides** (win over generated files), and **pack
    voltage** (EM current estimate).
- **📋 spec sheet** - suspension types, wheelbase/track, Cd/frontal area
  (the model has no aero force element, so there is nothing to patch),
  rated current/voltage, rims/tire-size text, notes. Recorded as
  `vehicle.json` in every run folder (provenance), drives the live Garage
  panel (derived stats: tire diameter, wheel torque, gearing top speed,
  power-to-weight, CdA) and the top-view car diagram, and can be pushed
  into the scenario preview model with one click. Suspension/geometry
  changes for real still mean re-exporting a deck from MotionView.

Vehicles save/load as `.vehicle.json` files and persist in the app between
sessions, like scenarios.

**Serial number (spec fingerprint):** every vehicle carries a serial like
`SN-2606118982` — a deterministic hash of everything that defines the car
(motors, gearing, mass, tire, pack, EMS; notes excluded). Any change makes a
new serial; the identical spec always reproduces the identical serial. It is
shown in the Garage and the run chip, logged in the run manifest, stored in
`vehicle.json`, and written into every MF4 as a constant **VehicleSerial**
channel — so a result file can always be matched, beyond doubt, to the exact
vehicle configuration that produced it (plot it in the viewer and compare
the number with the app).

## How the pieces fit

| Piece | Where it comes from |
|---|---|
| SimBuilder UI | `web\` (index.html/app.js/vehicle.js/motorbuilder.js/style.css) — loaded live from source, bundled snapshot in the exe. RUN/STOP, progress bar, run panel, tool-launcher buttons and ⚡ override pickers only appear inside this app (feature-detected via `window.pywebview`); in a plain browser the builder works minus those. `web\ScenarioBuilder.exe` is the old standalone chromeless launcher (still works from that folder). |
| `main.py` | Dispatcher + pywebview window + the JS↔Python bridge (`Api`), incl. stop_run (psutil kill of the whole solver process tree). |
| `pipeline.py` | The sequencing engine: run folder setup, deck patching, vehicle overrides, EMS map, motionsolve.bat subprocess with progress parsing, PLT→MF4 conversion (incl. the VehicleSerial channel), viewer launch. |
| MF4 viewer | Imported from `..\CSV to MDF Converter\mf4-viewer-app\viewer.py` — the canonical copy ([mf4-viewer repo](https://github.com/George-F-2000/mf4-viewer)), so viewer improvements arrive here automatically at the next exe build. |
| `plt_gui.py` | Copy of plt-to-mf4-converter's `app.py` (the converter window). |
| `plt_reader.py`, `avl_extract.py`, `converter.py` | Copies from [plt-to-mf4-converter](https://github.com/George-F-2000/plt-to-mf4-converter); this repo's `converter.py` additionally writes the VehicleSerial channel. Re-sync deliberately, not blindly. |
| `settings.json` | Created on first change (gitignored). Solver deck, motionsolve.bat, runs folder, pack voltage. **Per-machine**: each machine's choices live under `machines["<user>@<host>"]` in the one OneDrive-synced file, so home and lab never overwrite each other; missing paths from the other machine are healed (user profile and Altair version substitution). |

## Using it

Run from source:
```powershell
cd pipeline-app
"..\CSV to MDF Converter\csv-to-mf4-app\.venv\Scripts\python.exe" main.py
```

**RUN AVL CYCLE** (Scenario tab, preset card) runs every preset pedal
level (10, 20, 30, 40, 50, 60, 70, 100 %) back-to-back at the presets'
h_max of 0.01 s: one run folder + one MF4 per level, no viewer per run,
the runs folder opens when the batch finishes. Overall progress spans the
whole batch; STOP aborts the remaining runs; a failed run logs its error
and the batch continues with the next one. Note these presets launch from
standstill, which this model solves slowly — budget real time.

Define the vehicle (or load one), build the scenario, then press
**▶ RUN IN MOTIONSOLVE**. The run panel shows a progress bar driven by the
solver's own time steps, the live log, and a **STOP** button that kills the
whole solver process tree. When the run finishes, the MF4 viewer opens
preloaded with the fresh results; *Open run folder* jumps to the raw files.

Every run gets its own folder under `PhD Thesis\Simulation Runs\`:
`<scenario-name>_<timestamp>\` containing the patched deck (renamed to the
scenario, so outputs are `<scenario>.plt` etc.), the .adf, the model's .nam,
the healed/overridden .mat parameter files, `vehicle.json`, the full solver
outputs, and the final `_avldrive.mf4`. Self-contained and reproducible —
delete freely.

## The "current model"

The pipeline runs whatever solver deck the Pipeline setup card points at
(default: the double-lane deck in Test Run For PY Script). To use another
vehicle model: export the solver deck (.xml) from MotionView once, make
sure its `.nam` sits next to it, and pick it via *Change…*. The deck
patcher fixes machine-specific paths automatically:
- relative `../../` references are resolved against the deck's original
  folder and made absolute;
- absolute paths that don't exist (e.g. exported on the lab machine under a
  different user) are healed by finding the same file name next to the
  source deck and copying it into the run folder.

## Rebuilding the exe

```powershell
"..\CSV to MDF Converter\csv-to-mf4-app\.venv\Scripts\pyinstaller.exe" `
  --onefile --windowed --noconfirm --name SimBuilder `
  --icon assets\pipeline.ico --add-data "assets\pipeline.ico;." `
  --add-data "..\CSV to MDF Converter\mf4-viewer-app\assets\mf4viewer.ico;." `
  --add-data "..\CSV to MDF Converter\plt-to-mf4-app\assets\plttomf4.ico;." `
  --add-data "web;web" `
  --add-data "cycles;cycles" `
  --paths "..\CSV to MDF Converter\mf4-viewer-app" `
  --hiddenimport viewer --hiddenimport drive_cycles --collect-all tkinterdnd2 `
  main.py
```

`--add-data "web;web"` bundles the whole UI folder, so newly added web
files can never be forgotten. The exe still carries a **snapshot** —
rebuild after editing the UI; running from source uses the live files.
Close a running copy of the exe before rebuilding (Windows locks it).

## Energy management (EMS Builder)

The Vehicle Builder has an **Energy management (EMS)** card that regenerates
the dual-motor torque-split map (`optimal_torque_ratio_map`, the `r_ch`
grid) per run — verified consumed by `Motor_PMSM_dual.fmu` at this model's
`vcu_type`. An **Enable EMS Builder** toggle (default off) leaves the deck's
built-in map untouched when you don't need it.

Strategies (`ems_builder.py`), all producing the same map interface:
- **loss_optimal** — at each (motor speed, demand) picks the split that
  minimises combined electrical loss from both motors' efficiency maps
  (instantaneous ECMS). Reads the Motor Builder efficiency maps, so it
  re-optimises when the motors change.
- **rule** — single motor below a demand threshold, ramp to sharing above.
- **fuzzy** — fuzzy-logic blend of demand/speed memberships.
- **even** / **single_motor** — 50/50 and one-axle baselines.

Compare strategies by running each (same vehicle, same scenario) and viewing
`EM1Torque`/`EM2Torque` and motor efficiency in the MF4 viewer. The chosen
strategy is written into `vehicle.json` and the run manifest.

## Roadmap

- **MotorBuilder tab**: interactively build efficiency maps / lookup tables
  (draw or edit the grid, export to the motor .mat pipeline) instead of
  uploading CSVs.
- Tire picker: dropdown of compatible MF_SWIFT .tir files with dimensions
  parsed from inside each file, auto-syncing the tire-spec text.
- Steering ratio ⚡: the rack coupler (8.5) is identified and patchable.

## Results tab

The campaign leaderboard: one row per run in the runs folder, computed
from the MF4 + `vehicle.json` (cached by MF4 mtime; "Recompute all"
ignores the cache). Metrics: distance, net battery energy, **Wh/km**,
ΔSOC, drive-cycle tracking RMSE (UDDS/HWFET runs), jerk RMS, motor
on/off **chatter per minute**, Vmax, and a ✓/⚠ serial cross-check
between `vehicle.json` and the MF4's VehicleSerial channel. Sortable
columns; per-row open-folder / open-in-viewer buttons; Wh/km bar chart
colored by EMS strategy; the efficiency-vs-drivability scatter (bottom-
left wins); CSV export for publication plots.

## Import a real drive

Scenario tab → **Import real drive**: pick an MF4 logged in the actual
car, map the channels (speed + unit; optional steering source), and the
drive becomes a runnable scenario. When the run finishes, the viewer opens
with BOTH the sim result and the source real MF4 preloaded — overlay
VehicleSpeed (and friends) directly to judge the model. Steering/path sources:
- **None** — speed-only, straight line (any drive length).
- **Yaw rate** — dead-reckoned path (∫yaw, ∫v); great for maneuvers of
  minutes, drifts over long drives.
- **Steering wheel** — bicycle-model yaw from steer angle, the Vehicle
  Builder's steer ratio + wheelbase; same drift caveat.
- **GPS lat/lon** — drift-free path.

**Honesty note on path following:** the DDF grammar is Altair's own
(Snet_path example) and the driver reads and instantiates it — but in THIS
deck the steering then follows it with zero output and the run stops early
(confirmed even with the proven stock doublelane ADF surgically re-pointed
at a DDF). Path runs are therefore behind an "(experimental)" checkbox,
default off: imports run as speed-followers (proven, 0.42 km/h RMSE class)
while the steering source still powers the red→green travel map. Revisit
when the Altair driver's DDF handling is fixed or the missing requirement
is found.

With a path source, the importer writes a **DDF** companion
(`[DEMAND_VECTORS] {X Y Z DV}` — path points in meters + demanded speed,
~2 m spacing, Altair's own Snet_path grammar) and an ADF whose
FEEDFORWARD_STEERING follows it (`PATH='DDF'`) while traction follows the
DV column. The path-vs-odometer percentage in the import stats is the
sanity check (⚠ if off by >5 %). Both files land in the run folder.
