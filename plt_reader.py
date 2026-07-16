"""
plt_reader.py
================================================================================
Parser for MotionSolve ASCII result files: the .plt (data) and its .nam
companion (channel names + units). No Altair software needed.

Format, reverse-engineered and validated against MotionSolve v9.1 output
(cross-checked value-for-value against HyperGraph's own DataFileQuery):

.plt layout
    line 0      "MotionSolve v9.1 Plot File"
    line 1      generation timestamp
    line 2      <n_requests>  <units system, e.g. MMKGS_N_RACA>  <scale>
    directory   n_requests entries, 2 lines each:
                    <request id> <type> <marker> <marker> <name length>
                    <request name>
    data        per timestep: one line with the time value, then one line
                per request holding its 6 component slots:
                    X  Y  Z  R1  R2  R3

.nam layout
    INI-style [REQUEST] blocks:  NAME=, ID=, X=..R3= (component names),
    X_UNITS=..R3_UNITS= (units). Slots the model doesn't use carry filler
    names like 'F4'/'F6'.

If a future MotionSolve version changes this layout, the checks below raise
PltFormatError with a clear message instead of misreading data.
================================================================================
"""

import os

import numpy as np

# slot order of the 6 values on each request's data line
SLOTS = ["X", "Y", "Z", "R1", "R2", "R3"]


class PltFormatError(ValueError):
    """The file doesn't match the MotionSolve ASCII layout we know."""


def norm(s):
    """Collapse runs of whitespace - request names in the .plt/.nam contain
    inconsistent double spaces, so all name matching goes through this."""
    return " ".join(s.split())


def read_nam(nam_path):
    """
    Parse the .nam file.

    Returns {request_id: {"name": str,
                          "components": {component_name: slot_index},
                          "units": {component_name: unit_string}}}
    Names are whitespace-normalized.
    """
    blocks = []
    cur = None
    with open(nam_path, "r", encoding="ascii", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("["):
                cur = {} if line.upper().startswith("[REQUEST]") else None
                if cur is not None:
                    blocks.append(cur)
                continue
            if cur is None or "=" not in line:
                continue
            key, _, val = line.partition("=")
            cur[key.strip().upper()] = val.strip().strip("'\"")

    entries = {}
    for block in blocks:
        if "ID" not in block:
            continue
        rid = int(block["ID"])
        comps, units = {}, {}
        for slot_idx, slot in enumerate(SLOTS):
            comp_name = block.get(slot)
            if not comp_name:
                continue
            comps[norm(comp_name)] = slot_idx
            units[norm(comp_name)] = block.get(slot + "_UNITS", "")
        entries[rid] = {
            "name": norm(block.get("NAME", "")),
            "components": comps,
            "units": units,
        }
    if not entries:
        raise PltFormatError("No [REQUEST] blocks found in " + nam_path)
    return entries


def read_plt(plt_path):
    """
    Parse the .plt file.

    Returns (times, data, directory, units_system) where
        times      1-D float array, one value per timestep
        data       float array shaped (n_timesteps, n_requests, 6 slots)
        directory  list of (request_id, request_name) in file order
        units_system  e.g. "MMKGS_N_RACA" (mm / kg / s)
    """
    with open(plt_path, "r", encoding="ascii", errors="replace") as f:
        lines = f.read().splitlines()

    if len(lines) < 4 or "Plot File" not in lines[0]:
        raise PltFormatError(
            "{} does not look like a MotionSolve ASCII plot file "
            "(first line: {!r}). Binary .plt/.abf files are not supported - "
            "make sure MotionSolve is writing ASCII output.".format(
                os.path.basename(plt_path), lines[0][:60] if lines else ""))

    header = lines[2].split()
    try:
        n_req = int(header[0])
        units_system = header[1]
    except (IndexError, ValueError):
        raise PltFormatError("Unexpected header line 3: " + repr(lines[2]))

    directory = []
    i = 3
    for _ in range(n_req):
        try:
            rid = int(lines[i].split()[0])
        except (IndexError, ValueError):
            raise PltFormatError(
                "Directory entry at line {} is not an id line: {!r}".format(
                    i + 1, lines[i][:60]))
        directory.append((rid, norm(lines[i + 1])))
        i += 2

    tokens = " ".join(lines[i:]).split()
    per_block = 1 + n_req * 6  # time value + 6 slots per request
    if not tokens or len(tokens) % per_block:
        raise PltFormatError(
            "Data section size mismatch: {} values is not a multiple of "
            "{} (1 time + {} requests x 6 slots). The data layout may have "
            "changed in this MotionSolve version.".format(
                len(tokens), per_block, n_req))

    try:
        arr = np.array(tokens, dtype=np.float64).reshape(-1, per_block)
    except ValueError as exc:
        raise PltFormatError("Non-numeric value in data section: " + str(exc))

    times = arr[:, 0]
    if len(times) > 1 and np.any(np.diff(times) <= 0):
        raise PltFormatError("Time values are not strictly increasing - "
                             "the data section was mis-read.")

    data = arr[:, 1:].reshape(len(arr), n_req, 6)
    return times, data, directory, units_system
