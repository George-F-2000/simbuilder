"""
converter.py
================================================================================
PLT -> MF4 conversion engine (no GUI code in this file).

app.py (the tkinter window) imports convert() from here, and it stays
testable from a command line:

    python converter.py <run.plt> [output.mf4] [--csv]

Pipeline:
    1. find the .nam companion next to the .plt (names + units live there)
    2. extract the AVL Drive channels (avl_extract.py)
    3. apply unit conversions (physical = raw * scale + offset)
    4. write one channel group into an MDF 4.10 file - the layout AVL
       Drive expects - plus an optional CSV with the same physical values
================================================================================
"""

import csv
import os

import numpy as np
from asammdf import MDF, Signal

from avl_extract import extract, CHANNEL_CONFIG, COLUMN_ORDER, DEFAULT_PACK_VOLTAGE

MDF_VERSION = "4.10"   # safest ASAM MDF version for AVL tools


def find_nam(plt_path):
    """The .nam with the same base name, or the folder's only .nam."""
    base_nam = os.path.splitext(plt_path)[0] + ".nam"
    if os.path.isfile(base_nam):
        return base_nam
    folder = os.path.dirname(plt_path) or "."
    nams = [os.path.join(folder, f) for f in os.listdir(folder)
            if f.lower().endswith(".nam")]
    if len(nams) == 1:
        return nams[0]
    raise FileNotFoundError(
        "No .nam companion for {}. MotionSolve writes it next to the .plt; "
        "it is needed for channel names and units.".format(
            os.path.basename(plt_path)))


def convert(plt_path, mf4_path=None, write_csv=False, log=print,
            pack_voltage=DEFAULT_PACK_VOLTAGE, serial_number=None,
            pack_kwh=None, soc_start=None):
    """Convert one .plt (+ .nam) to MF4. Returns the output path.

    pack_voltage [V] feeds the EM current estimate (I = Power Demand / V).
    serial_number (int, optional): SimBuilder vehicle-spec fingerprint;
    written as a constant 'VehicleSerial' channel so the MF4 itself
    identifies the exact vehicle config that produced it.
    pack_kwh / soc_start: recompute BattSOC for the REAL pack. The motor
    FMU's battery capacity is compiled into its binary (a ~9.5 kWh stand-in),
    so the FMU's own SOC output drops ~10x too fast and starts at its baked
    75%. Since the FMU battery is a fixed-loss model, SOC is just the energy
    integral over capacity - so given the real pack kWh and starting SOC we
    reconstruct the correct SOC trace from the (correct) BattPower channel.
    """
    nam_path = find_nam(plt_path)
    log("  using names/units from: " + os.path.basename(nam_path))

    times, raw, missing = extract(plt_path, nam_path, log=log,
                                  pack_voltage=pack_voltage)
    if not raw:
        raise ValueError("None of the AVL Drive channels were found - "
                         "is this the right model's .plt?")

    # rebuild SOC for the real pack (see docstring). BattPower is raw W here.
    if pack_kwh and soc_start is not None and "BattPower" in raw:
        p_w = raw["BattPower"]                      # W, + discharge / - regen
        e_wh = np.concatenate([[0.0], np.cumsum(
            0.5 * (p_w[1:] + p_w[:-1]) * np.diff(times))]) / 3600.0
        soc = float(soc_start) - e_wh / (float(pack_kwh) * 1000.0)
        raw["BattSOC"] = np.clip(soc, 0.0, 1.0)     # 0-1; CHANNEL_CONFIG x100
        log("  BattSOC recomputed for a {:g} kWh pack from {:.0%} start "
            "(the FMU's own SOC uses a compiled ~9.5 kWh stand-in)".format(
                pack_kwh, float(soc_start)))

    ordered = [c for c in COLUMN_ORDER if c in raw]
    signals = []
    physical = {}
    for channel in ordered:
        unit, scale, offset, _src, comment = CHANNEL_CONFIG.get(
            channel, ("", 1.0, 0.0, "", ""))
        samples = raw[channel] * scale + offset
        physical[channel] = samples
        signals.append(Signal(samples=samples, timestamps=times,
                              name=channel, unit=unit, comment=comment))

    if serial_number is not None:
        signals.append(Signal(
            samples=np.full(len(times), float(serial_number)),
            timestamps=times, name="VehicleSerial", unit="-",
            comment="SimBuilder vehicle spec fingerprint "
                    "(SN-{:010d})".format(serial_number)))
        log("  VehicleSerial channel: SN-{:010d}".format(serial_number))

    if mf4_path is None:
        mf4_path = os.path.splitext(plt_path)[0] + "_avldrive.mf4"

    mdf = MDF(version=MDF_VERSION)
    mdf.append(signals, comment="Converted from " + os.path.basename(plt_path),
               common_timebase=True)
    mdf.save(mf4_path, overwrite=True)
    mdf.close()

    if write_csv:
        csv_path = os.path.splitext(mf4_path)[0] + ".csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time"] + ordered)
            for i in range(len(times)):
                writer.writerow([times[i]] + [physical[c][i] for c in ordered])
        log("  CSV written: " + csv_path)

    dt = float(np.median(np.diff(times)))
    log("MF4 written: " + mf4_path)
    log("  {} channels, {} samples, {:.4g} s duration, ~{:.6g} s sample step"
        .format(len(signals), len(times), times[-1] - times[0], dt))
    for channel, reason in missing:
        log("  missing '{}': {}".format(channel, reason))
    return mf4_path


if __name__ == "__main__":
    import sys
    argv = sys.argv[1:]
    voltage = DEFAULT_PACK_VOLTAGE
    if "--voltage" in argv:
        i = argv.index("--voltage")
        voltage = float(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if a != "--csv"]
    if not args:
        print("Usage: python converter.py <run.plt> [output.mf4] "
              "[--csv] [--voltage 380]")
        sys.exit(1)
    convert(args[0],
            mf4_path=args[1] if len(args) > 1 else None,
            write_csv="--csv" in argv,
            pack_voltage=voltage)
