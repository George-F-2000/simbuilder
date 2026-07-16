"""
avl_extract.py
================================================================================
The AVL Drive signal layer: which MotionSolve request/component feeds each
AVL Drive channel, plus the unit conversion applied to each one.

Requests are matched by NAME (not numeric id), so the mapping survives model
rebuilds that renumber the requests. Components are resolved to their data
slot through the .nam file, so slot reshuffles are handled automatically.

EM1 = front motor, EM2 = rear motor.

The model outputs no motor current channel, so EM1Current / EM2Current are
ESTIMATED as DC-link current:  I = Power Demand / pack voltage. The pack
voltage is a parameter (GUI field / extract() argument, default 380 V); the
estimate assumes constant terminal voltage, which holds well over short
maneuvers where SOC barely moves. Signs follow Power Demand, so regen
current comes out negative.

AccelerationVertical was dropped from the channel set on purpose (no
vertical acceleration request in the model, and it is not needed).
================================================================================
"""

import numpy as np

from plt_reader import read_nam, read_plt, norm

RAD_S_TO_RPM = 60.0 / (2.0 * np.pi)   # 9.5493
RAD_TO_DEG   = 180.0 / np.pi          # 57.2958

# Nominal battery pack voltage [V] used for the EM current estimate when no
# other value is supplied (the GUI exposes this as an editable field).
DEFAULT_PACK_VOLTAGE = 380.0

# ----------------------------------------------------------------------------
#  SIGNAL MAP  -  AVL Drive channel : (request name, component name)
#  Names as they appear in the .nam file (whitespace differences don't matter).
# ----------------------------------------------------------------------------

R_DRIVER_OUT = "Driver outputs: Steer angle, Throttle, Brake, Gear, clutch, Distance Travelled"
R_DRIVER_IN2 = "Driver inputs 2:  Long vel, Lat vel , Yaw rate, Roll rate, Pitch rate , Engine speed"
R_DRIVER_IN3 = "Driver inputs 3 : Long acc , Lat acc"
R_MOTOR_F    = "Motor - front (FMU) Outputs"
R_MOTOR_R    = "Motor - rear (FMU) Outputs"
R_BATTERY    = "Battery Management"
R_ESP_OMEGA  = "ESP - FMU Inputs - Wheel Omega"

SIGNAL_MAP = {
    "AccelerationChassis":  (R_DRIVER_IN3, "Long. acc."),
    "AccelerationLateral":  (R_DRIVER_IN3, "Lat. acc."),
    "AcceleratorPedal":     (R_DRIVER_OUT, "Throttle"),
    "BattSOC":              (R_BATTERY,    "SOC"),
    "BrakePosition":        (R_DRIVER_OUT, "Brake"),
    "EM1Speed":             (R_MOTOR_F,    "Motor Speed"),
    "EM1Torque":            (R_MOTOR_F,    "Motor Torque"),
    "EM2Speed":             (R_MOTOR_R,    "Motor Speed"),
    "EM2Torque":            (R_MOTOR_R,    "Motor Torque"),
    "GearDMU":              (R_DRIVER_OUT, "Gear"),
    "SteeringWheelAngle":   (R_DRIVER_OUT, "Steer angle"),
    "VehicleSpeed":         (R_DRIVER_IN2, "Long. vel."),
    "WheelSpeed_FL":        (R_ESP_OMEGA,  "Front-left"),
    "WheelSpeed_FR":        (R_ESP_OMEGA,  "Front-right"),
    "WheelSpeed_RL":        (R_ESP_OMEGA,  "Rear-left"),
    "WheelSpeed_RR":        (R_ESP_OMEGA,  "Rear-right"),

    # internal sources ("_" prefix = extracted but never written to the MF4);
    # these feed the EM current estimates below
    "_EM1PowerDemand":      (R_MOTOR_F,    "Power Demand"),
    "_EM2PowerDemand":      (R_MOTOR_R,    "Power Demand"),
}

# ----------------------------------------------------------------------------
#  DERIVED SIGNALS  -  computed from an extracted channel's RAW values
# ----------------------------------------------------------------------------
# Brake:            brake switch, 1.0 while the brake pedal is applied
# SelectorLeverDMU: the model has no PRND lever channel; any gear engaged
#                   counts as Drive (1.0). Adjust if your AVL Drive project
#                   expects a different lever encoding.
# ----------------------------------------------------------------------------

DERIVED = {
    "Brake":            ("BrakePosition", lambda raw: (raw > 0.0).astype(np.float64)),
    "SelectorLeverDMU": ("GearDMU",       lambda raw: (raw != 0.0).astype(np.float64)),
}

# ----------------------------------------------------------------------------
#  CHANNEL CONFIG  -  physical = raw * scale + offset
# ----------------------------------------------------------------------------
# src_unit is what the .nam declares for the source component; the extractor
# warns if the file disagrees (a units change in the model would otherwise
# corrupt every converted value silently).
#
# Speeds are converted rad/s -> rpm because that is what AVL Drive expects
# for EM and wheel speed channels; set scale=1.0 and unit "rad/s" to revert.
# ----------------------------------------------------------------------------

CHANNEL_CONFIG = {
    # channel               unit      scale          offset  src_unit   comment
    "AccelerationChassis":  ("m/s^2", 0.001,         0.0,    "",        "Longitudinal acceleration (mm/s^2 -> m/s^2)"),
    "AccelerationLateral":  ("m/s^2", 0.001,         0.0,    "",        "Lateral acceleration (mm/s^2 -> m/s^2)"),
    "AcceleratorPedal":     ("%",     100.0,         0.0,    "[0-1]",   "Accelerator pedal position"),
    "BattSOC":              ("%",     100.0,         0.0,    "0-1",     "Battery state of charge"),
    "Brake":                ("-",     1.0,           0.0,    "",        "Brake switch (derived from BrakePosition)"),
    "BrakePosition":        ("%",     100.0,         0.0,    "[0-1]",   "Brake pedal position"),
    "EM1Current":           ("A",     1.0,           0.0,    "",        "Front motor DC current (estimated: Power Demand / pack voltage)"),
    "EM1Speed":             ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Front motor speed (rad/s -> rpm)"),
    "EM1Torque":            ("Nm",    0.001,         0.0,    "N-mm",    "Front motor torque (N*mm -> N*m)"),
    "EM2Current":           ("A",     1.0,           0.0,    "",        "Rear motor DC current (estimated: Power Demand / pack voltage)"),
    "EM2Speed":             ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Rear motor speed (rad/s -> rpm)"),
    "EM2Torque":            ("Nm",    0.001,         0.0,    "N-mm",    "Rear motor torque (N*mm -> N*m)"),
    "_EM1PowerDemand":      ("W",     1.0,           0.0,    "W",       "internal - feeds EM1Current estimate"),
    "_EM2PowerDemand":      ("W",     1.0,           0.0,    "W",       "internal - feeds EM2Current estimate"),
    "GearDMU":              ("-",     1.0,           0.0,    "",        "Selected gear"),
    "SelectorLeverDMU":     ("-",     1.0,           0.0,    "",        "Selector lever (derived: 1 = Drive)"),
    "SteeringWheelAngle":   ("deg",   RAD_TO_DEG,    0.0,    "rad",     "Steering wheel angle (rad -> deg)"),
    "VehicleSpeed":         ("km/h",  0.0036,        0.0,    "",        "Vehicle longitudinal speed (mm/s -> km/h)"),
    "WheelSpeed_FL":        ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Wheel speed front-left (rad/s -> rpm)"),
    "WheelSpeed_FR":        ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Wheel speed front-right (rad/s -> rpm)"),
    "WheelSpeed_RL":        ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Wheel speed rear-left (rad/s -> rpm)"),
    "WheelSpeed_RR":        ("1/min", RAD_S_TO_RPM,  0.0,    "rad/s",   "Wheel speed rear-right (rad/s -> rpm)"),
}

# Output channel order (also used for the optional CSV)
COLUMN_ORDER = [
    "AccelerationChassis", "AccelerationLateral",
    "AcceleratorPedal",
    "BattSOC",
    "Brake", "BrakePosition",
    "EM1Current", "EM1Speed", "EM1Torque",
    "EM2Current", "EM2Speed", "EM2Torque",
    "GearDMU", "SelectorLeverDMU",
    "SteeringWheelAngle",
    "VehicleSpeed",
    "WheelSpeed_FL", "WheelSpeed_FR", "WheelSpeed_RL", "WheelSpeed_RR",
]


def extract(plt_path, nam_path, log=print, pack_voltage=DEFAULT_PACK_VOLTAGE):
    """
    Pull the raw AVL Drive channels out of a .plt/.nam pair.

    pack_voltage [V] feeds the EM current estimate (I = Power Demand / V).

    Returns (times, raw, missing) where
        times    1-D float array
        raw      {channel_name: 1-D float array} - RAW solver values,
                 CHANNEL_CONFIG scaling is NOT applied here
        missing  [(channel_name, reason)] for channels that could not be found
    """
    times, data, directory, units_system = read_plt(plt_path)
    nam = read_nam(nam_path)

    if not units_system.upper().startswith("MMKGS"):
        log("  WARNING: solver units are '{}' (expected MMKGS/mm-kg-s). "
            "Scale factors in CHANNEL_CONFIG may be wrong for this run!"
            .format(units_system))

    name_to_ids = {}
    for rid, entry in nam.items():
        name_to_ids.setdefault(entry["name"], []).append(rid)
    id_to_col = {rid: col for col, (rid, _name) in enumerate(directory)}

    raw, missing = {}, []
    for channel, (req_name, comp_name) in SIGNAL_MAP.items():
        ids = name_to_ids.get(norm(req_name), [])
        if len(ids) != 1:
            reason = ("request '{}' not found in .nam".format(req_name)
                      if not ids else
                      "request name '{}' is ambiguous ({} matches)".format(
                          req_name, len(ids)))
            missing.append((channel, reason))
            continue
        rid = ids[0]

        slot = nam[rid]["components"].get(norm(comp_name))
        if slot is None:
            missing.append((channel,
                            "component '{}' not in request {} ({})".format(
                                comp_name, rid, req_name)))
            continue

        col = id_to_col.get(rid)
        if col is None:
            missing.append((channel,
                            "request id {} in .nam but not in .plt".format(rid)))
            continue

        # units cross-check: warn if the .nam disagrees with what the
        # conversion in CHANNEL_CONFIG assumes
        expected_src = CHANNEL_CONFIG.get(channel, ("", 1, 0, "", ""))[3]
        actual_src = nam[rid]["units"].get(norm(comp_name), "")
        if expected_src and actual_src and \
                norm(actual_src).lower() != norm(expected_src).lower():
            log("  WARNING: '{}' unit is '{}' in the .nam but the converter "
                "assumes '{}' - check CHANNEL_CONFIG.".format(
                    channel, actual_src, expected_src))

        raw[channel] = data[:, col, slot]

    for channel, (src, func) in DERIVED.items():
        if src in raw:
            raw[channel] = func(raw[src])
        else:
            missing.append((channel, "derived from '{}' which is missing".format(src)))

    # ---- estimated channels ------------------------------------------------
    # DC-link current per motor: I = electrical Power Demand / pack voltage.
    # Assumes constant terminal voltage; regen shows up as negative current.
    if pack_voltage <= 0:
        raise ValueError("Pack voltage must be positive, got {}".format(pack_voltage))
    estimated = [("EM1Current", "_EM1PowerDemand"),
                 ("EM2Current", "_EM2PowerDemand")]
    for channel, pwr in estimated:
        if pwr in raw:
            raw[channel] = raw[pwr] / float(pack_voltage)
        else:
            missing.append((channel,
                            "estimate needs '{}' which is missing".format(pwr)))
    if any(pwr in raw for _c, pwr in estimated):
        log("  EM currents estimated as Power Demand / {:g} V (DC-link, "
            "constant-voltage assumption)".format(pack_voltage))

    return times, raw, missing
