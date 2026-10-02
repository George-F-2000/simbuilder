"""
agent/tools.py
================================================================================
The complete tool list of the local agent. Each entry maps a name to an
OptimizerApi method with a JSON-schema description of its arguments; the
grammar in llm.py is generated from this list, so the model cannot name a
tool that is not here. Results are returned as compact JSON, truncated to
keep the context small.
================================================================================
"""
import json

MAX_RESULT_CHARS = 6000

TOOLS = [
    {"name": "optim_state",
     "description": "Current optimizer state: tunable parameters, log roles, defaults, base tyre/aero "
                    "files, deck info, past studies, whether a study is running.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "optim_inspect_log",
     "description": "Open a real-vehicle MF4 log: list its channels, the resolved role mapping "
                    "(saved/last/suggested) and its problems, and the speed channel's time span.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "optim_save_map",
     "description": "Save the role->channel mapping for a log. cmap: {role: {name, unit, sign?}} "
                    "with roles speed, pedal (required), brake, torque_front, torque_rear, "
                    "pack_power, pack_voltage, pack_current, soc.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "cmap": {"type": "object"}},
                    "required": ["path", "cmap"]}},
    {"name": "optim_find_windows",
     "description": "Find candidate replay windows (moving stretches) in a mapped log. opts: "
                    "min_len_s, max_len_s, v_floor_kph, brake_free.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "cmap": {"type": "object"},
                                                     "opts": {"type": "object"}},
                    "required": ["path", "cmap"]}},
    {"name": "optim_start",
     "description": "Start a study. config: {name, log_path, channel_map, windows:[{t0,t1}], "
                    "params:{lmy_scale:{min,max}, aero_scale:{min,max}}, weights, max_workers, "
                    "step_s, pedal_mode ('physical'|'mapped'), design:{grid, rounds}}.",
     "parameters": {"type": "object", "properties": {"config": {"type": "object"}}, "required": ["config"]}},
    {"name": "optim_status",
     "description": "Progress of the running (or last) study: round, jobs, candidates with scores, best.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "optim_stop",
     "description": "Stop the running study and kill its solvers.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "optim_export",
     "description": "Export the best candidate of a finished study: tuned deck, tyre, aero, report, figure.",
     "parameters": {"type": "object", "properties": {"study_dir": {"type": "string"},
                                                     "redact": {"type": "boolean"}}, "required": []}},
    {"name": "optim_history",
     "description": "List past studies with status and best parameters.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "optim_study",
     "description": "Full state and config of one past study by folder.",
     "parameters": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]}},
    {"name": "read_report",
     "description": "The exported report.md of a study (text), if the study was exported.",
     "parameters": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]}},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


def describe_tools():
    """Plain-text tool list for the system prompt."""
    out = []
    for t in TOOLS:
        req = ", ".join(t["parameters"].get("required") or []) or "none"
        props = ", ".join(t["parameters"].get("properties") or {}) or "none"
        out.append("- {}: {} (args: {}; required: {})".format(t["name"], t["description"], props, req))
    return "\n".join(out)


def _trim(obj):
    s = json.dumps(obj, default=str)
    if len(s) <= MAX_RESULT_CHARS:
        return s
    return s[:MAX_RESULT_CHARS] + '... [truncated, {} chars total]'.format(len(s))


def dispatch(optim_api, name, args):
    """Call one registered tool on the OptimizerApi; returns compact JSON text.
    Unknown names are refused here as well as by the grammar."""
    if name not in TOOL_NAMES:
        return json.dumps({"ok": False, "error": "unknown tool '{}'".format(name)})
    args = dict(args or {})
    try:
        if name == "read_report":
            import os
            p = os.path.join(args.get("study_dir") or "", "best", "report.md")
            if not os.path.isfile(p):
                return json.dumps({"ok": False, "error": "no report at " + p})
            text = open(p, encoding="utf-8").read()
            return _trim({"ok": True, "report": text})
        fn = getattr(optim_api, name)
        return _trim(fn(**args))
    except TypeError as exc:
        return json.dumps({"ok": False, "error": "bad arguments for {}: {}".format(name, exc)})
    except Exception as exc:
        return json.dumps({"ok": False, "error": "{}: {}".format(type(exc).__name__, str(exc)[:200])})
