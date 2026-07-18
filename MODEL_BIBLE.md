# THE MODEL BIBLE — how to run a simulation you can defend

Every rule in here was paid for with a real failure or a real near-miss on
this project. Newest lessons at the bottom of each section. Sibling docs:
README.md (how the app works), CAMPAIGN.md (the plan),
ENGINEERING_NOTES.md (the raw session log this distills).

---

## 1. The Ten Commandments

1. **Lock the vehicle, write down the serial.** Never touch the vehicle
   mid-campaign. Same spec = same serial, always; any change = new serial =
   new campaign. The serial in the MF4 is the arbiter of every "which
   config was this?" argument.
2. **One campaign, one machine, one solver version.** Home = Altair 2025,
   lab = 2025.1: both run fine, but they are different solver builds.
   Never mix their results in one comparison figure.
3. **A run whose tracking RMSE fails the gate (> ~2 km/h on a cycle) is
   INVALID for efficiency numbers.** Rerun it. No exceptions.
4. **Compare like with like.** Unadjusted lab cycle ≠ EPA window sticker
   (×~0.7 harshness adjustment) ≠ wall-to-wheel (adds ~10% charging loss).
   Our MF4 numbers are UNADJUSTED, BATTERY-OUT. Convert before comparing
   to any published figure (see §5).
5. **Your data only governs where your data exists.** An efficiency map
   with empty cells is silently ideal in those cells. Check map coverage
   against the cycle's operating region BEFORE trusting a Wh/km number
   (see §4 — this one cost us the first HWFET).
6. **Read solver logs top-down: the FIRST error is the cause.** The last
   line ("Error encountered in processing xml input file!") is a generic
   wrapper printed by every failed run and means nothing by itself.
7. **Never start a scenario at exactly v = 0.** The model cannot
   initialize there (DASPK dies on step one). The ADF generators floor
   VX0 at 0.9 km/h automatically — do not "fix" that floor away.
   Mid-run stops are fine, just slow.
8. **Deterministic solver: never repeat an identical run expecting new
   information.** Spend the compute on a new variable instead.
9. **Keep every run folder.** They are self-contained, reproducible
   evidence: patched deck, ADF, FMU, vehicle.json, log, MF4.
10. **When a result looks *too* good, audit it before celebrating.**
    "Matches the stock LYRIQ almost exactly" turned out to be two large
    errors cancelling (§4, §5).

## 2. Pre-flight checklist (before every campaign night)

- [ ] Vehicle Builder: correct vehicle loaded, **serial matches your
      campaign log** (a stray checkbox click = different serial = the run
      chip will show it — look at it).
- [ ] Per-motor "map file is truth" checkboxes are the way you intend
      (they are part of the serial).
- [ ] 🏁 "Run deck as-is" is OFF for campaign runs, ON only for
      model-validation-vs-real-drive runs.
- [ ] EMS card: strategy + enable toggle as the experiment demands.
- [ ] Timestep: 10 ms (confirm popup — anything else is a deliberate,
      documented decision).
- [ ] Runs folder has disk space; no other solve is running unless you
      intend to run concurrently (concurrency is licensed and works).
- [ ] Note wall-clock budget: HWFET ≈ 11 h; UDDS ≈ 15–20 h (its 17
      standstill dwells run at ~4–5 wall-min per parked sim-second);
      prefer the 505 s UDDS Phase-1 variant unless the full cycle is
      required.

## 3. Know your layers (what governs what)

| Layer | Source | Changes when… |
|---|---|---|
| Suspension, kinematics, chassis mass distribution | MotionView-exported deck (.xml) | you re-export from MotionView. Nothing else can change these. |
| Tire | .tir file referenced by deck (Vehicle Builder can override) | you point at a different .tir |
| Aero | .aae file referenced by deck | you edit/replace the .aae (no UI override yet) |
| Motor envelopes + efficiency/regen maps | run-local FMU copy, rebuilt per run from the motor cards | fields, uploaded files, or "map is truth" checkboxes change |
| Torque split (EMS) | run-local FMU copy (`opt_trq_ratio`) | EMS card enable + strategy |
| Driver behaviour | ADF (generated per scenario/cycle) | scenario settings; cycle-driver tuning lives in drive_cycles.py / app.js templates |
| Everything else per run | pipeline patching (paths, versions, ADF re-point, XML safety) | automatic; read the run log to see what it did |

## 4. Input fidelity — the four pillars of an absolute Wh/km

An efficiency number is only as real as its four biggest inputs. State of
each as of 2026-07-18:

1. **Mass** — deck solves at 2,710 kg vs real LYRIQ AWD curb ≈ 2,648 kg
   (5,838 lb). CLOSE ENOUGH. ✅
2. **Tire** — deck references a scaled generic **205/60R15** TNO car tire;
   the real car wears **265/50R22** (~820 mm dia vs ~627 mm). Wrong
   rolling resistance AND wrong radius (skews every motor-speed↔road-speed
   relationship). ❌ **Biggest suspected Wh/km error.** Fix: obtain or
   dimension-scale a proper 265/50R22 MF-Swift .tir, set it as the
   Vehicle Builder tire override (⚡), update the tire-spec text.
3. **Aero** — deck references Altair's **generic library**
   `aerodynamic_frc.aae`, not the LYRIQ's CdA (~0.28 × ~2.6 m²). ❌
   Fix: copy the .aae next to the deck, edit coefficients to LYRIQ
   values, re-export or re-point the deck ref.
4. **Motor maps — THE COVERAGE RULE.** The FMU treats empty (zero) map
   cells as ~lossless. Highway cycles live at LIGHT LOAD (the first
   HWFET's AAM median operating point: **13 Nm @ 10,440 rpm — a zero
   cell**), so an uncovered low-load region makes the whole cycle run on
   ideal motors. Before any efficiency campaign:
   - overlay the cycle's operating points on the map's covered region;
   - fill uncovered cells honestly (measured data preferred; physics-based
     loss model as a disclosed fallback — SimBuilder feature pending);
   - re-check after ANY map upload.

## 5. Comparison bases (the units bible)

To compare our MF4 numbers with published LYRIQ figures:

```
our number:      unadjusted lab cycle, battery-out      [Wh/km net]
EPA sticker:     adjusted (×~0.7 harsher), wall-to-wheel (+~10% charging)
```

- Model HWFET (first run): 255.6 Wh/km battery-out, unadjusted.
- Real LYRIQ AWD sticker: 379 Wh/mi ≈ 235 Wh/km — but that is adjusted +
  wall-to-wheel. Same-basis (unadjusted, battery-out) real ≈ 130–150
  Wh/km. **The model is currently ~1.7–1.9× thirstier than stock on equal
  basis** (expected: pillars 2–4 above are not yet fixed; near-ideal
  motors partially masked it).
- RELATIVE comparisons (EMS A vs EMS B on the same locked vehicle) remain
  valid under these caveats. ABSOLUTE claims need the pillars fixed.

## 6. Numerics

- **h_max = 10 ms.** The floor and the law. The slider will not go finer;
  going coarser triggers the confirm popup for a reason.
- **Creep start**: ADF generators floor VX0 at 250 mm/s (0.9 km/h). The
  model initializes rolling, then the driver regulates to the demand.
- **Standstill dwells** integrate at H ≈ 1e-5 s: budget ~4–5 wall-minutes
  per parked sim-second. Rolling scenarios run ~1000× faster.
- **Concurrent solving works** (license verified, 3 simultaneous): each
  instance uses ~4 threads; the i9 comfortably hosts 4–6. Throughput
  scales with instances, not threads — never chase `-nt`.

## 7. Reading a run

Order of trust: run log (first ERROR) → MF4 channels → Results tab row.

Known-benign log lines (present in fully successful runs — do not chase):
- `WARNING: Error in principal J for body [10704/20704]: Ji+Jj<Jk!`
- `WARNING: Residual stiffness (CCX/CCY) is (almost) zero.`
- `WARNING: Unable to get user function [GET_CG_LOC / MOTION_RATIO]`
- `WARNING: Vertical load is above tire file maximum FZMAX` (fix arrives
  with the proper 22" tire)
- `Maximum initial residual=…` (the passing runs have BIGGER ones than
  the failing runs — it means nothing on its own)

Validity gates per run:
- solver completed (a failed maneuver now raises — partial MF4s are no
  longer silently converted);
- cycle runs: tracking RMSE < ~2 km/h;
- serial cross-check ✓ on the Results tab;
- eyeball VehicleSpeed + EM torques in the viewer for driver chatter.

## 8. Known artifacts & open items (2026-07-18)

- **ΔSOC column is fiction**: the FMU's internal pack is ~9 kWh (SOC fell
  75→28% on one HWFET). Use integrated kWh; ignore SOC % until scaled.
- **Driver pedal chatter (4–5 Hz) during decels**: the driver bang-bangs
  between 0% pedal (hard regen) and ~18% because gentle decels sit between
  its two levers. Pollutes jerk/chatter drivability metrics. KEY FACT: on
  this EV deck the driver logs "No solver info found for engine -
  Feedforward traction controller ignored" and silently instantiates an
  internal feedback PID with DEFAULT gains (Kp 0.5, Ki 0.1, Kd 0) —
  LOOK_AHEAD_TIME is therefore a DEAD knob; the real levers are the pedal
  SMOOTHING_FREQUENCY and an explicit `TAG='PID'` controller block with
  tuned KP/KI/KD (grammar: ADFtemplates writePIDControllerBlock).
  Measured so far: smoothing 10→2 Hz alone halves chatter (6.4→2.8
  torque reversals/s) and improves RMSE (0.41→0.30 km/h). PID-gain round
  in progress; winning tune goes into drive_cycles.py + app.js. NOTE the
  driver tune measurably changes regen energy — freeze it BEFORE the
  campaign; it is part of the experimental setup like the vehicle.
  Until then: drivability metrics from cycle runs are NOT meaningful.
- **BattPower at light load**: overall traction chain efficiency 0.62 vs
  0.87 at cruise points — suggests a constant parasitic draw worth
  auditing before absolute efficiency claims.
- **loss_optimal EMS** assumes equal drive ratios; LYRIQ is 18 vs 9.59 —
  its optimum is approximate on this vehicle. Disclose if headline.
- **Advanced .mat overrides** cannot reach in-FMU files (motor cards and
  EMS card are the supported paths on the LYRIQ).

## 9. When a run fails or looks weird — the diagnostic ladder

1. Read the run log top-down; find the FIRST error. Check §7's benign list.
2. Diff against the nearest run that worked: what ONE thing changed?
   (vehicle? scenario? machine? deck? checkbox → check the serial!)
3. Bisect empirically: change ONE variable per run, use short scenarios
   (rolling start, 5–10 sim-s) — a verdict costs ~2 minutes, a theory
   costs nothing but proves nothing.
4. Trust measurements over hypotheses: the standstill bug survived five
   plausible theories (h_max, injection, tire VXLOW, ENGINE_INIT_SPEED,
   eff-map zeros) before the bisection found VX0=0. All five sounded
   right. None were.
5. When the sim output looks wrong, audit what the run ACTUALLY contained:
   the run folder's FMU/deck/vehicle.json are ground truth, not what you
   intended to configure.

## 10. Provenance & reproducibility

- Every run folder is court-admissible: patched deck, ADF, run-local FMU
  (bytes = exactly what solved), vehicle.json (config incl. every
  checkbox), solver log, MF4 with VehicleSerial channel.
- The campaign log (keep it in CAMPAIGN.md) records: date, serial,
  scenario, machine, solver version, purpose, verdict.
- The vehicle also lives as a .vehicle.json export next to the model data
  (`MBD - Copy For Testing\LYRIQ_AAM_SRM_real_maps.vehicle.json`) —
  re-loadable on any machine, reproducing the identical serial.
