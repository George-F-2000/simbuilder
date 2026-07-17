# EMS Simulation Campaign — the path forward

Goal: efficiency **and** drivability comparison of EMS strategies on the
full multibody LYRIQ model — the Pareto scatter in the Results tab is the
key figure. Rule #1: **lock the vehicle first and never touch it
mid-campaign** (the serial number is your witness).

## Phase 0 — calibration runs (start tonight)
- [ ] Lock the campaign vehicle in Vehicle Builder. Name it properly,
      write down the serial (SN-…).
- [ ] Fire **one full HWFET, deck-default EMS** overnight.
      → validates a full-length cycle, gives the true wall-time cost,
      and becomes leaderboard row #1 (the OEM baseline).
- [ ] Fire **one 10 % tip-in preset** (the slowest preset) right after.
      → sizes what RUN AVL CYCLE will really cost.
- [ ] Morning: open the Results tab. Check HWFET **Track RMSE < ~2 km/h**
      (validity gate) and note both wall times.

## Phase 1 — HWFET efficiency sweep (the core result)
- [ ] Ask Claude for the **RUN EMS SWEEP** button (campaign item 3 —
      same scenario, all strategies back-to-back, one click).
- [ ] HWFET × 6 strategies: deck_default, loss_optimal, rule, fuzzy,
      even, single_motor. (~1 night with the sweep button.)
- [ ] Results tab → check every run's tracking RMSE, then read the
      Wh/km column. Export CSV, stash it in the thesis folder.

## Phase 2 — UDDS (city) sweep
- [ ] One UDDS, deck-default, overnight → true cost of the city cycle.
- [ ] If too slow: ask Claude for a **UDDS Phase-1 (505 s)** variant —
      defensible subset, ~⅓ the cost.
- [ ] UDDS × the strategies that mattered on HWFET (often the extremes:
      default, loss_optimal, even). One per night is fine.

## Phase 3 — drivability axis
- [ ] RUN AVL CYCLE × 3 strategies: deck_default, loss_optimal, and the
      HWFET winner. Jerk RMS + chatter/min land in the Results tab.
- [ ] Lab day: run the same MF4s through AVL Drive, note the official
      drivability scores next to the surrogate metrics (one calibration
      table: surrogate vs AVL score = a nice validation subsection).

## Phase 4 — reviewer-proofing (sensitivity)
- [ ] Repeat the HWFET sweep at **±10 % mass** (Vehicle Builder, two new
      serials). Shows conclusions aren't knife-edge.
- [ ] Replace the synthetic motor efficiency maps with real LYRIQ data
      (upload or MotorBuilder) and re-run the HWFET sweep — kills the
      "synthetic map" caveat and re-optimizes loss_optimal properly.

## Phase 5 — writing
- [ ] Export the final Results CSV → publication plots.
- [ ] The scatter (Wh/km vs jerk/chatter, colored by strategy, one panel
      per cycle) is Figure 1. The serial numbers go in the appendix as
      the reproducibility statement.

## Standing rules
- Never change the vehicle mid-phase — new serial = new campaign row.
- A run whose tracking RMSE is bad is INVALID for efficiency — rerun it.
- Keep every run folder; they're self-contained evidence.
- Deterministic solver: never repeat an identical run expecting new info.
