"""
agent/llm.py
================================================================================
The local model: a GGUF file run in-process by llama.cpp (llama-cpp-python).
Output is constrained by a grammar generated from a JSON schema with exactly
two shapes - a tool call whose name is one of the registry's, or a final
message - so the loop never has to parse free text.

Settings: llm_model_path (the GGUF), llm_ctx (context tokens, default 8192),
llm_gpu_layers (-1 = all on the GPU when a CUDA build is installed, 0 = CPU),
llm_threads. The CPU wheel is the default install; a 7B Q4 model answers in
seconds per step on this class of machine, a 14B in tens of seconds.
================================================================================
"""
import json
import os

from . import tools


def response_schema():
    """JSON schema of one agent step: {"tool": name, "args": {...}} or {"final": text}."""
    return {
        "oneOf": [
            {"type": "object",
             "properties": {"tool": {"type": "string", "enum": tools.TOOL_NAMES},
                            "args": {"type": "object"}},
             "required": ["tool", "args"], "additionalProperties": False},
            {"type": "object",
             "properties": {"final": {"type": "string"}},
             "required": ["final"], "additionalProperties": False},
        ]
    }


class StepParseError(ValueError):
    """The model's text was not a valid step; carries the raw text so the
    loop can show it and ask the model again."""

    def __init__(self, msg, raw=""):
        super().__init__(msg)
        self.raw = raw


def parse_step(text):
    """The step object from the model's text; tolerant of a leading/trailing
    fence or prose. Raises StepParseError when no valid step can be read."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise StepParseError("no JSON object in the model output", text)
    try:
        obj = json.loads(s[i:j + 1])
    except ValueError as exc:
        raise StepParseError("invalid JSON: {}".format(exc), text)
    if not isinstance(obj, dict):
        raise StepParseError("step must be an object", text)
    if "tool" in obj:
        if obj["tool"] not in tools.TOOL_NAMES:
            raise StepParseError("tool '{}' is not in the registry".format(obj["tool"]), text)
        obj.setdefault("args", {})
        if not isinstance(obj["args"], dict):
            raise StepParseError("args must be an object", text)
        return obj
    if "final" in obj:
        return {"final": str(obj["final"])}
    raise StepParseError("step must have 'tool' or 'final'", text)


class LocalLLM:
    """llama.cpp wrapper. The model loads on the first call."""

    def __init__(self, model_path, n_ctx=8192, n_gpu_layers=0, n_threads=None):
        self.model_path = model_path
        self.n_ctx = int(n_ctx or 8192)
        self.n_gpu_layers = int(n_gpu_layers or 0)
        self.n_threads = n_threads
        self._llm = None
        self._grammar = None
        self.loaded = False
        self.info = {}

    def available(self):
        return bool(self.model_path) and os.path.isfile(self.model_path)

    def load(self):
        if self._llm is not None:
            return
        if not self.available():
            raise FileNotFoundError("model file not found: {}".format(self.model_path))
        from llama_cpp import Llama, LlamaGrammar
        n_threads = self.n_threads or max(2, (os.cpu_count() or 8) // 2)
        self._llm = Llama(model_path=self.model_path, n_ctx=self.n_ctx,
                          n_gpu_layers=self.n_gpu_layers, n_threads=n_threads, verbose=False)
        self._grammar = LlamaGrammar.from_json_schema(json.dumps(response_schema()))
        self.loaded = True
        self.info = {"model": os.path.basename(self.model_path), "n_ctx": self.n_ctx,
                     "n_gpu_layers": self.n_gpu_layers, "n_threads": n_threads}

    def step(self, messages, max_tokens=700, temperature=0.2):
        """One constrained completion. Returns (step_dict, raw_text, usage)."""
        self.load()
        out = self._llm.create_chat_completion(
            messages=messages, grammar=self._grammar, max_tokens=max_tokens,
            temperature=temperature)
        text = out["choices"][0]["message"]["content"] or ""
        usage = out.get("usage") or {}
        return parse_step(text), text, usage


class ScriptedLLM:
    """A stand-in for tests and for the UI without a model file: returns the
    scripted steps in order, then a final message."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.loaded = True
        self.info = {"model": "scripted"}
        self.calls = []

    def available(self):
        return True

    def load(self):
        pass

    def step(self, messages, max_tokens=700, temperature=0.2):
        self.calls.append(messages)
        if self.steps:
            s = self.steps.pop(0)
        else:
            s = {"final": "(scripted: no more steps)"}
        text = json.dumps(s)
        return parse_step(text), text, {}
