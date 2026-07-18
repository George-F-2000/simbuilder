# THE MODEL BIBLE — how to run a simulation you can defend

Every rule in here was paid for with a real failure or a real near-miss on
this project. **Part I** is the rules. **Part II is the Chronicle — the
full story of this model, told as it happened**, kept as raw material for
the thesis methodology chapter. When something teaches you (or Claude)
something new, add a story to Part II and, if it generalizes, a rule to
Part I. Sibling docs: README.md (how the app works), CAMPAIGN.md (the
plan), ENGINEERING_NOTES.md (the dense session log this distills).

---

# PART I — THE RULES

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
  RESOLVED 2026-07-18 — winning tune (baked into drive_cycles.py, used by
  cycles + real-drive imports; Scenario Builder keeps crisp open-loop
  pedal steps): **throttle/brake SMOOTHING_FREQUENCY = 1 Hz + declared
  PID Kp 0.3 / Ki 0.05 / Kd 0**. vs baseline: jerk RMS 58.9→12.6, EM1
  torque p99 step 30.7→13.8, RMSE 0.49 vs the 2.0 gate. Kp 0.15 was too
  soft (RMSE 0.91, micro-dither); Kp 0.3 @ 2 Hz smoothing made the
  integrator CRAWL (~30 µs steps, killed after 5 h at t=38/75) — a tune
  that slows the solver 10× is disqualified regardless of metrics. The
  driver tune measurably changes regen energy (chatter was throwing
  recuperation away), so it is FROZEN as part of the experimental setup.
  Cycle drivability metrics from runs BEFORE 2026-07-18 are not
  comparable to runs after.
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

---

# PART II — THE CHRONICLE

The story of this model, in order, with what each chapter taught. Dates
are real. Add new chapters at the bottom as they happen.

## Ch. 1 — Origins: a converter grows into a pipeline (June–July 2026)

It started as a small tool to convert CSV logs to MF4 for AVL Drive. Then
a PLT→MF4 converter for MotionSolve outputs. Then the realization: if the
outputs can be automated, so can the inputs — and SimBuilder was born
around the doublelane demo deck: scenario builder → deck patcher →
headless MotionSolve → MF4 → viewer, one exe. The builder's ADF format
was validated end-to-end on 2026-07-16 (hand-built 5 s scenario, correct
physics, regen on tip-out). First hard numerics lesson the same day: a
122-second standstill scenario crawled at H≈4e-5 and was killed — "runs
taking forever" was never the timestep setting, it was standstill
stiffness. *Moral: know which part of your scenario costs wall-time.*

## Ch. 2 — Making the vehicle real (2026-07-16)

Vehicle Builder fields stopped being decorative: the motor .mat schema
was reverse-engineered (envelope + efficiency + regen grids), the mass
patch verified against the solver's own "Total Mass" printout, and the
final-drive couplers PROVEN to be the complete motor→wheel reduction by
measuring EM/wheel speed ratios in the output. The serial-number
fingerprint was added the same day: FNV-1a over the whole spec, written
into every MF4. *Moral: never claim a field "affects the sim" until the
output proves it — and stamp every result with what produced it.*

## Ch. 3 — Decoding the EMS (2026-07-16)

The dual-motor torque split lives in `optimal_torque_ratio_map` (the
`r_ch` grid) inside the motor FMU. Semantics were established
empirically: inject r_ch=0 → EM2 carries nothing; r_ch=0.5 → even split —
tested at moderate throttle, because full throttle saturates both motors
and masks the split. Strategies built on those axes: loss_optimal (ECMS),
rule, fuzzy, even, single_motor. *Moral: FMU internals are knowable —
black boxes surrender to one well-designed A/B experiment.*

## Ch. 4 — The LYRIQ arrives, and everything breaks politely (2026-07-17, lab)

Pointing the pipeline at the real LYRIQ deck surfaced a day of ambushes:
runs died in 2 s on a bare `&` in a share-folder path (XML parser), the
file dialogs had been silently killed by that morning's pywebview
upgrade, a hi-DPI bug grew the canvases exponentially on the lab's 4K
display, and — the big one — this deck has NO external motor files: the
motor data lives INSIDE Motor_PMSM_dual.fmu. fmu_inject.py was born:
copy the FMU per run, rewrite its internal .mat resources, re-point the
deck. *Moral: a new deck is a new country; assume nothing imported.*

## Ch. 5 — The night of portability (2026-07-17, home)

"I just can't run the LYRIQ at home because everything points to the
lab." One evening fixed it forever: per-machine settings sections in the
synced settings.json, user-profile healing (George↔gfare), Altair
VERSION healing (lab 2025.1 ↔ home 2025) for FMUs/road/aero/DLLs, the
deck's ADF reference re-pointed into the run folder (it had silently
pointed at the ORIGINAL scenario — wrong-scenario risk on every machine),
and MotionView's animation sensor neutralized for headless runs. Then, at
last: THE FIRST COMPLETE LYRIQ SOLVE THROUGH THE PIPELINE — 6 sim-s in
114 s, physics verified down to the EM speed ratio matching the gearing.
*Moral: machine-portability is a set of specific, fixable failures, not
fate.*

## Ch. 6 — The gearing confession (2026-07-17)

The deck shipped front=18:1, rear=9.59:1; George had said the physical
car was the opposite, and the notes carried a standing "ASK GEORGE"
warning for a day. Resolution: "The AAM, in the front, is 18:1. The SRM,
in the rear, is the 9.59:1. That's my bad." The deck had been right all
along. *Moral: write down unresolved contradictions loudly — and let the
hardware answer beat the memory.*

## Ch. 7 — Real motors, honest precedence (2026-07-17, evening)

George's real scans arrived: a 49×50 AAM (induction) map to 23.5k rpm /
235 Nm / 94% peak, and a 14×21 SRM map to 9k rpm / 198 Nm / 91.5%.
Datasheet ratings arrived an hour later and DISAGREED with the files
(SRM: 318 Nm / 16k rpm rated vs 198 Nm / 9k measured). Rather than let
one silently win, precedence became explicit: fields build the envelope
by default; a per-motor "Map file is truth" checkbox hands it to the
file's measured curve; either way the choice is hashed into the serial.
Solver-validated both ways in the FMU bytes. *Moral: when two sources of
truth conflict, make the choice visible, recorded, and reversible.*

## Ch. 8 — "Will it go horribly wrong?" (2026-07-17, night)

George asked for a pre-flight audit instead of an overnight surprise. It
found the campaign-killer: on the LYRIQ, EMS was a SILENT NO-OP — the
builder only knew how to shadow an external map file, and this deck keeps
the map inside the FMU. Phase 1 would have produced six identical runs
labeled as six strategies. Fixed by FMU injection; proven with
single_motor collapsing EM2 to ~zero. The same audit run also exposed
that the exe forgot every vehicle on restart (pywebview 6 defaults to
ephemeral storage). *Moral: audits before campaigns; the most dangerous
failure is the one that still produces plausible-looking output.*

## Ch. 9 — The standstill bisection (2026-07-17, late night)

George's first real run died instantly; the log's last line blamed the
"xml input file" and nearly sent him deck-hunting. The FIRST error told
the truth: the integrator failed at t=2.236e-10. Eight runs bisected it:
not h_max, not the injection, not the tire's VXLOW, not
ENGINE_INIT_SPEED, not the stock deck being special — the model simply
cannot INITIALIZE at exactly v=0, in any configuration. Five plausible
theories died before the sixth run found it. Fix: a 0.9 km/h creep-start
floor in both ADF generators. The stop-and-go test then proved mid-run
v=0 crossings work (UDDS viable), and priced standstill dwells at ~4–5
wall-minutes per parked sim-second. *Moral: bisect with cheap runs;
theories are free and usually wrong.*

## Ch. 10 — The first HWFET, and the number that was too good (2026-07-17→18)

Eleven hours, completed, tracking clean — and Wh/km "almost exactly a
stock LYRIQ." The audit ruined the celebration properly: the sticker
figure it matched is adjusted wall-to-wheel (different units of test);
on equal basis the model is ~1.7–1.9× thirstier than stock. And the
motor scans barely participated — the AAM map is EMPTY at light load,
exactly where highway cycles live, and the FMU treats empty cells as
lossless. Meanwhile the signals were noisy at 4–5 Hz during decels: the
driver (its feedforward controller silently ignored on an engine-less
deck) was bang-banging its default-gain internal PID against one-pedal
regen. Also caught: the run's serial didn't match the campaign vehicle —
a stray "map is truth" checkbox, correctly fingerprinted. *Morals: §5's
units bases; §4's coverage rule; a result that matches expectations is
not yet a result.*

## Ch. 11 — Tuning the driver like a calibrator (2026-07-18)

The chatter fix was approached exactly like an HIL calibration task:
isolate a 75 s decel-rich HWFET segment, run variants concurrently
(three solvers side-by-side — which also proved the license supports
parallel solving, unlocking the sweep-farm plan). Round 1: pedal
smoothing 10→2 Hz halved chatter and IMPROVED tracking; "look-ahead" was
exposed as a dead knob (the FF controller it belongs to is ignored).
Round 2 declared explicit PID gains in the ADF and crowned the winner:
1 Hz smoothing + Kp 0.3/Ki 0.05 — jerk down 4.7×, tracking well inside
the gate. Two instructive losers: too-soft gains went sloppy, and one
combination (same gains, 2 Hz smoothing) made the integrator crawl at
30 µs steps for five hours before being killed — solver cost is a tuning
criterion too. The chatter had also been throwing away regen energy, so
the driver tune moves Wh/km: it gets frozen with the vehicle before the
campaign. *Moral: the virtual driver is part of the experiment, not
scenery — and an experiment that melts the solver is a failed experiment
even when its physics looks good.*

## Ch. 12 — (open) The road to defensible numbers

Standing work when this chapter was opened: dimension-correct 265/50R22
tire file; LYRIQ-correct aero .aae; light-load coverage for the AAM map
(measured, or disclosed physics fill); driver tune frozen; HWFET baseline
re-run; parallel EMS sweep. Write the ending when it happens.
