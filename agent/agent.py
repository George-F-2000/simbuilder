"""
agent/agent.py
================================================================================
The loop. One user message -> up to MAX_STEPS model steps; every tool call and
its result are appended to a visible transcript so the operator sees exactly
what the assistant did. Runs on a thread; the page polls the transcript.
================================================================================
"""
import json
import threading
import time

from . import tools
from .llm import StepParseError

MAX_STEPS = 12
MAX_TOOL_RESULT_IN_CONTEXT = 4000

SYSTEM_PROMPT = """You are the Optimizer assistant inside SimBuilder, a desktop tool that fits a
vehicle simulation model (MotionSolve) to a real-vehicle log. You run locally and offline.

What the optimizer does: it replays the log's own accelerator and brake through the model
(open loop) and tunes two road-load scales - lmy_scale (tyre rolling resistance) and
aero_scale (aero drag) - so the model's speed, torque and power curves land on the car's.
Everything else in the model is locked by design. A study = windows of the log x candidate
parameter sets, each a solver run; results are normalised RMSE per signal and a weighted total
(lower is better), with a quadratic response surface over the candidates.

You act ONLY through the tools below. You cannot run commands, open files other than through
these tools, or reach the network. Work step by step: inspect the log, check the channel
mapping and fix obvious unit problems, find windows, propose a study (two or three windows of
30-90 s with tip-ins and coasting are better than one long one), start it only when the user
asked you to, report progress and explain results in plain engineering language (which
parameter moved, by how much, which signals improved, what remains unexplained). Keep in mind:
a candidate scored 10 failed to solve; a lag of a second or two is alignment, not physics;
rear-torque terms are meaningless on a front-only log.

Answer with exactly one JSON object per step:
  {"tool": "<name>", "args": {...}}   to call a tool
  {"final": "<message to the user>"}  when you are done or need the user's decision
Tools:
""" + tools.describe_tools()


class Agent:
    def __init__(self, optim_api, llm, log=None):
        self.optim_api = optim_api
        self.llm = llm
        self.log = log or (lambda s: None)
        self.transcript = []        # [{"role", "text", "when"}]
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.error = None

    def busy(self):
        return bool(self._thread and self._thread.is_alive())

    def reset(self):
        if self.busy():
            raise RuntimeError("the assistant is working")
        self.transcript = []
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.error = None

    def _add(self, role, text):
        with self._lock:
            self.transcript.append({"role": role, "text": text, "when": time.strftime("%H:%M:%S")})

    def tail(self, n=200):
        with self._lock:
            return list(self.transcript[-n:])

    def send(self, user_text):
        if self.busy():
            raise RuntimeError("the assistant is still working on the previous message")
        self._stop.clear()
        self.error = None
        self._add("user", user_text)
        self.messages.append({"role": "user", "content": user_text})
        self._thread = threading.Thread(target=self._run, name="optimizer-agent", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            if not self.llm.loaded:
                self._add("system", "loading the model…")
                self.llm.load()
                self._add("system", "model ready: {}".format(self.llm.info))
            for step_no in range(1, MAX_STEPS + 1):
                if self._stop.is_set():
                    self._add("system", "stopped by the user")
                    return
                try:
                    step, raw, usage = self.llm.step(self.messages)
                except StepParseError as exc:
                    # unparsable despite the grammar: show it, tell the model, try again
                    self._add("system", "could not read the model's step: {}".format(exc))
                    self.messages.append({"role": "assistant", "content": exc.raw or ""})
                    self.messages.append({"role": "user", "content": "Your last answer was not a valid step object. "
                                          "Reply with one JSON object: {\"tool\": ..., \"args\": {...}} or {\"final\": ...}."})
                    continue
                self.messages.append({"role": "assistant", "content": raw})
                if "final" in step:
                    self._add("assistant", step["final"])
                    return
                name, args = step["tool"], step["args"]
                self._add("tool", "{}({})".format(name, json.dumps(args)[:400]))
                result = tools.dispatch(self.optim_api, name, args)
                self._add("result", result[:1500] + ("…" if len(result) > 1500 else ""))
                self.messages.append({"role": "user", "content": "Tool result for {}:\n{}".format(
                    name, result[:MAX_TOOL_RESULT_IN_CONTEXT])})
            self._add("system", "stopped after {} steps without a final answer".format(MAX_STEPS))
        except Exception as exc:
            self.error = "{}: {}".format(type(exc).__name__, str(exc)[:300])
            self._add("system", "assistant error: " + self.error)
