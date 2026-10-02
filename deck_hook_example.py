"""
deck_hook_example.py
================================================================================
The contract for a DECK HOOK: a local Python file that patches the solver deck
text after every built-in override (vehicle, tyre, aero, EMS) and before the
XML is written. Point settings.json at it:

    "deck_hooks": ["C:/path/to/my_plant.local.py"]

or pass per run:  vehicle["deck_hooks"] = [...]  and  vehicle["hook_params"] = {...}

Hooks are how machine-specific or confidential model edits (a measured pedal
law written into the deck as a spline, a brake-blended regen expression, a
seat swap for a different controller FMU) stay out of the public repository:
anything named *.local.py is gitignored. This example is a no-op that only
reports counts, so it is safe to leave in the repository.

Rules
  * Signature:  apply(deck_text, *, run_dir, settings, vehicle, log)
                -> (deck_text, counts)
  * `counts` is a dict {what: how_many}; assert your own substitution counts
    (re.subn) and raise when they are wrong - a silent no-op is the worst
    failure mode for a calibration study.
  * Hooks run in worker threads (several runs may be prepared at once):
    read your inputs, write only into run_dir, touch no module globals.
  * A raising hook is logged and skipped by the pipeline; the run continues
    on the unhooked deck. Make the message say what did not happen.
================================================================================
"""


def apply(deck_text, *, run_dir, settings, vehicle, log):
    params = (vehicle or {}).get("hook_params") or {}
    log("  example deck hook: {} chars of deck, {} hook parameter(s), "
        "nothing changed".format(len(deck_text), len(params)))
    return deck_text, {"changed": 0}
