# Scenario Builder

Interactive builder for MotionSolve longitudinal driving scenarios. Define a maneuver as a sequence of phases ("do WHAT, UNTIL"), preview the pedal trace and estimated speed, and export a runnable Altair Driver `.adf` file.

**Run it:** double-click `ScenarioBuilder.exe` — opens the app in its own chromeless desktop window (Edge app mode). Or open `index.html` in any browser; both are the same app, no install or server needed.

`ScenarioBuilder.exe` is a tiny launcher (5 KB, compiled from `build\ScenarioBuilder.cs` with the .NET Framework's built-in `csc.exe`). It must stay in the same folder as `index.html`/`style.css`/`app.js`. Falls back to the default browser on machines without Edge. To rebuild after editing the launcher:
`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe /out:ScenarioBuilder.exe /win32icon:build\icon.ico /r:System.Windows.Forms.dll build\ScenarioBuilder.cs`

## Current features (v1 — vertical slice)
- Phase cards: accelerator + brake per phase, `hold at` / `step to` (with rise time) in %
- Phase exits: fixed duration, speed rises above X kph, speed drops below X kph (with max-time safety cap)
- Live preview: driver inputs + point-mass speed estimate (mass/force/drag configurable, preview only)
- Warnings when an exit condition won't be reached before its cap (per the estimate)
- Live `.adf` generation, copy/download; scenario save/load as JSON; auto-saves to browser storage
- Ships with the AVL tip-out/tip-in example (10% to 50 kph → release to 20 kph → 10% for 5 s → 10 s buffer)

## ADF format basis
Generated blocks mirror the stock Altair writers (see `..\Stock Scenarios\_Altair_Source\ADFtemplates_DECOMPILED.py`):
units mm/N/rad/kg/s, `[*_STANDARD]` driver limits, `[MANEUVERS_LIST]` (sim_time = cap),
per-maneuver `(CONTROLLERS)` + `(END_CONDITIONS)` (`LONG_VEL GT/LT`, tolerance = 5% of value),
open-loop `CONSTANT` / `EXPRESSION` controllers with `STEP({%TIME},0,{THROTTLE_0},rise,target)`
continuity placeholders, shared zero-steer, stock gear/clutch map.

**Validation status:** format verified against decompiled writers and a real `Model_Run_doublelane_0.adf`; not yet run through MotionSolve — do that with the exported example before trusting it broadly.

## Roadmap ideas
Template library (AVL-DRIVE modes), parameter sweeps → batch .adf, gear/steer channels,
closed-loop speed phases (demand curves), distance/steady-state exits (verify driver support first).
