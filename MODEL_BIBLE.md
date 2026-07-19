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
each as of 2026-07-18 (all four now ADDRESSED — vehicle SN-2499411196):

1. **Mass** — GOSPEL for our experiments: the prototype is **2746.938776
   kg** (heavier than a production LYRIQ; 6,056 lb). Set as massKg with
   "Apply mass" ON; the deck's chassis-ballast body absorbs the delta and
   the solver statics confirm Total Mass = 2.747E+03 kg. ✅
2. **Tire** — replaced the generic 205/60R15 with
   **`LYRIQ_265_50R20_proto.tir`** (in `MBD - Copy For Testing`): donor
   TNO tyre, dimensions scaled to 265/50R20 at the lab, then load
   parameters rescaled ×1.087 for the 2746.94 kg prototype (FNOMIN 6737
   N/corner, vertical/long/lat/yaw stiffness scaled), FZMAX→16 kN,
   VXLOW→1, inflation 262 kPa, RIM_WIDTH artifact fixed. Set as the
   Vehicle Builder tire override (⚡). ✅ CAVEAT: the Pacejka SHAPE
   coefficients are still the donor tyre's — disclosed approximation
   until a measured 265/50R20 EV tyre file exists (ask Altair academic).
3. **Aero** — replaced with **`LYRIQ_aero.aae`** (in `MBD - Copy For
   Testing`): frontal area 2.6 m², Cd 0.28 (incidence curve scaled
   proportionally). Set as the Vehicle Builder aero override (⚡, new
   feature). ✅ CAVEAT: lift/side/yaw curves remain the generic donor's
   (irrelevant to straight-line consumption; disclose if lateral work).
4. **Motor maps — THE COVERAGE RULE, now enforced by the tool.** The FMU
   treats empty (zero) map cells as ~lossless; highway cycles live at
   LIGHT LOAD (first-HWFET AAM median: 13 Nm @ 10,440 rpm — a zero cell).
   fmu_inject now FILLS uncovered cells with the synthetic bowl scaled to
   the scan's own peak, keeps measured cells verbatim, and LOGS COVERAGE
   every run ("map coverage: 93% measured — 14 of 196 cells filled").
   ✅ Still: prefer real light-load dyno data when you get it; the fill is
   a disclosed model, not measurement. Re-check coverage after ANY upload.

**NOTE — the "match stock" coincidence is now expected to unwind:** with
correct (heavier) mass and correct tire/aero, absolute Wh/km should MOVE
from the old 255.6. Re-run the HWFET baseline on SN-2499411196 and compare
against real figures on the §5 equal basis; that number is the real one.

## 4b. The road-load anchor (independent realism check)

Before trusting ANY absolute Wh/km from the solver, compute what pure
road-load physics says the same vehicle should consume, and require the
run to land near it. Physics-only HWFET battery-out prediction
(`roadload_anchor.py`), for reference (2026-07-18):

| config | Wh/km |
|---|---|
| stock-est (2650 kg, CdA 0.60, Crr 0.008) | 138 |
| prototype (2747, CdA 0.728, Crr 0.008) | 162 |
| prototype + realistic tyre (Crr 0.010) | ~185 |
| prototype worst-case (Crr 0.012, weak regen) | 203 |

- **The prototype target is ~180–190 Wh/km battery-out unadjusted.** A
  solver run far above that is losing energy somewhere unphysical
  (artifact); far below means an input is too soft.
- **NO phantom parasitic load exists** — verified: at true coast
  (|shaft power|<0.5 kW) battery median = 0.003 kW. The old 0.62
  integrated chain efficiency was the CHATTERING driver operating in
  inefficient transients, not an accessory draw. Fixed by the driver tune.
- **The old 255.6 was too HIGH** (above worst-case physics) — chatter
  inflation, not a realistic thirsty result. The realistic prototype
  number is LOWER than the old buggy one even though inputs got worse.
- **Prototype IS worse than stock** (~185 vs ~138, a defensible ~35%
  penalty from mass + CdA + tyre) — the real "worse than stock" claim,
  just don't measure it against the old buggy 255.

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

## Ch. 12 — Building the defensible vehicle (2026-07-18)

The four input pillars got fixed in one sitting. The driver tune was frozen
(1 Hz + PID 0.3/0.05). A prototype tyre was built —
`LYRIQ_265_50R20_proto.tir`, load parameters rescaled for the heavier
prototype mass George declared gospel (2746.938776 kg, applied and
confirmed by solver statics at 2.747 t). A LYRIQ aero file replaced
Altair's generic library values, reaching the deck through a NEW aero
override (same re-point mechanism as the tire). And the injector learned to
fill empty map cells honestly — the first-HWFET lesson made into a
permanent guardrail that logs measured-vs-modeled coverage on every run
(the AAM scan came out 93% measured). A full-stack validation run confirmed
all four active at once: tire re-pointed, aero re-pointed, mass patched,
maps filled, physics sane. New campaign vehicle: **SN-2499411196**.
*Moral: a defensible number is assembled deliberately, one audited input at
a time, each disclosed for exactly what it is — measurement where we have
it, honest model where we don't.*

## Ch. 13 — The tyre I broke, and the 335 kW ghost (2026-07-18/19)

The rebuilt vehicle read a physically impossible 352 kW at a steady 100 km/h
cruise — 18x what road-load physics allows, and cleanly converged, which is
worse than noise because the model had settled into a wrong equilibrium. The
wheel-speed telltale: front axle (18:1) implied a wheel speed 15% higher than
the rear, spinning against the road and dissipating ~335 kW in tyre scrub.

The bisection took a full day and one false conclusion. I claimed the bind
was high-speed-only and drivability was therefore safe; the direct 80 km/h
test refuted me (7.2x over physics there too) — *never generalise a "clean"
verdict from a run you only eyeballed; measure the operating point you
actually care about.* The stock deck at 50 km/h was clean (H=9e-3), my
config at 50 was fine (10.6 vs 8.7 kW), so it was mine and load-dependent.

Root cause: **I broke the tyre.** I had "dimension-scaled" a tyre that was
already a correct 265/50R20, and in doing so changed FNOMIN and INFLPRES —
the constants the Pacejka force coefficients are *fitted against*. Rescaling
them without re-fitting silently reduces grip, and the shortfall grows with
load, which is exactly why it hid at 50 km/h and detonated at 100. Fix:
start from the deck's ORIGINAL tyre, change ONLY rolling resistance (QSY1/3/4
-> Crr 0.011 for the Pilot Sport 4 SUV) and the FZMAX validity limit (12400
-> 16000, needed because the 2747 kg prototype overloads the donor's range
during settling and the cap made statics non-convergent). Result at 80 km/h:
slip +20% -> -1.4%, power 89 -> 24 kW. *Moral: a .tir's coefficients are
fitted against its normalisation constants — touch FNOMIN/INFLPRES and you
silently rebuild the force model. Change rolling resistance and validity
limits only; never the normalisation.*

## Ch. 14 — The split that divided the wrong torque (2026-07-19)

With grip fixed, a launch to 100 km/h still collapsed — the car stuck at
10.2 km/h with the front wheels spinning at +1972%. A SECOND, independent
bug: the deck's torque-split map (r_ch) divides **motor** torque, but the
axles multiply it by 18:1 vs 9.59:1, so an "even" motor split puts 68% of
the WHEEL torque on the front — exactly as rearward weight transfer unloads
it. The deck's own default map had this flaw. Fix: a ratio-aware `traction`
strategy that splits WHEEL torque by axle load (incl. load transfer),
converts back through the ratios (an even wheel split is r_ch=0.652, NOT
0.5), and clamps to each motor's real envelope. loss_optimal was fixed too
(it had assumed equal ratios AND evaluated both motors at the same speed —
a given road speed puts the front motor at 1.88x the rear's). Also fixed:
the EMS was sizing against the field ratings while the FMU runs the
file-truth envelope, so it optimised for a motor that wasn't there. Launch
to 100 km/h after: holds 100.1 km/h, slip -1.4%, 35.7 kW. *Moral: on a
mixed-ratio multi-motor vehicle, ALWAYS reason in wheel torque; motor-torque
splits silently over-drive the higher-ratio axle.*

**Hardware truth this exposed:** front axle can make 235x18 = 4234 Nm at the
wheel, rear only 198x9.59 = 1895 Nm — the vehicle is inherently front-biased
in capability, so no strategy can put an even wheel split down at high demand.

## Ch. 15 — What the split can't fix, and where the thirst lives (2026-07-19)

Overnight + morning on the repaired vehicle. Traction split VALIDATED clean
50/56/89/96 km/h (slip <2%, power scaling sensibly) — that band is the model's
trustworthy envelope. HWFET rows: traction split 361.6 Wh/km at RMSE 1.97
(passes the 2.0 gate) = campaign baseline row #1; deck-default 944 Wh/km at
RMSE 11.82 = INVALID (the front over-drive wrecks tracking on any cycle with
acceleration) — so the ratio-aware split is REQUIRED, not optional.

**111 km/h is NOT a torque-split problem — hypothesis refuted by experiment.**
I thought high-speed sharing caused a two-motor fight fixable by single-motor.
Ran traction, single_motor AND loss_optimal at 111: all three gave
BYTE-IDENTICAL results (471 kW, front 78 / rear 181 Nm). single_motor commands
r_ch=0 (rear off) yet the rear still makes 181 Nm — proving the FMU IGNORES
the injected split above ~100 km/h. So 111 is high-speed FMU/vcu behaviour
(prime suspect: rear SRM at 7642 rpm = 85% of its 9000 rpm envelope), not
anything the EMS can touch. *Moral (again): test the hypothesis before
building the fix — single-motor would have been coded for nothing.*

**The thirst is road load, not driveline — SOURCE NOT YET IDENTIFIED.**
Decomposed the clean plateaus: driveline (mech/batt) is a healthy ~0.82; the
excess is MECHANICAL road load, ~1.6-1.9x idealised physics as a roughly
constant ~380 N unaccounted force (model 1070 N at 96 km/h vs aero 371 +
Crr-0.011 RR 296 = 667 N). Ruled OUT so far: (a) driveline/electrical (eff is
fine); (b) the tyre Crr coefficient — cutting QSY1/3/4 by 36% moved battery
power only 4%; (c) load-dependent RR (QSY7) — I initially guessed this but the
arithmetic kills it: per-corner load 6737 N is only 1.087x nominal 6200 N, so
(Fz/Fn)^0.9 adds ~8%, not 70%. REMAINING candidates, unconfirmed: static
deck inspection found NO single explicit drag/friction element, but a large
DISTRIBUTED damping network — 69 Force_Bushing, 8 Force_SpringDamper, plus the
tyre's own vertical/relaxation damping. That distributed suspension + tyre
hysteresis dissipation is the likely home of the ~380 N, and it is PHYSICALLY
REAL — losses a simple aero+Crr hand-calc omits entirely, so the model reading
higher than textbook physics is partly expected and arguably correct. Still
not PROVEN to be the ~380 N (would need a per-element energy audit) and still
not validated against the car. Needs real power-analyzer data. The
"model matches the real car" idea stays UNPROVEN — the v^3+v+c fit that would
support it is numerically unstable (4 collinear points). Do not assert it.

**Licence wall:** 5 concurrent solves refused, 4 is the ceiling — throughput
is gated by licence SEATS not CPU cores. Changes the hardware calculus: more
machines buy nothing against a floating pool of 4; confirm floating-vs-node-
locked with Altair before spending the $3k. `queue_runner.py` (waits for a
seat before launching) is the seed of the farm scheduler.

OPEN for George: (1) the FMU's high-speed logic (why r_ch is ignored >100
km/h); (2) the F2 question (total road load vs added aero); (3) real power-
analyzer data to validate road load; (4) the torque-split log (does the real
car park a motor? is there an axle DISCONNECT the rigid-coupler model can't
represent?). Write the ending when >100 km/h runs and the road load is
confirmed against real data.
