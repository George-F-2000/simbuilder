"""
optimizer
================================================================================
Fit the model's ROAD LOAD to a real-vehicle log.

The model is driven by the log's own accelerator and brake (open loop, the
driver out of the loop), and two calibration-layer parameters are tuned so the
model's curves land on the car's:

    lmy_scale   x the tyre file's LMY (rolling-resistance moment scale)
    aero_scale  x the drag-coefficient table in the aero file

Nothing else is tunable - masses, inertias, compliances, motor maps and the
controller FMU's tables are locked (plant.PARAMS is the whole registry, and
Study refuses any other key). Each evaluation is one MotionSolve run per
replay window, scored straight from the .plt against the log; candidates run
in parallel up to a solver cap.

Modules
  logmatch   the real log: channels -> roles, windows, alignment, metrics
  replay     the open-loop driver file (constant maneuvers for pedal + brake)
  plant      the two tunables and how they reach the tyre / aero files
  study      the search (grid + quadratic response surface), the scheduler,
             state, export of the tuned model
  api        the methods exposed to the page (and to the local agent)

Data policy: this package ships no real-car channel names, vehicle constants
or measured values. The channel mapping is chosen in the UI and saved to
channel_aliases.local.json (gitignored).
================================================================================
"""
