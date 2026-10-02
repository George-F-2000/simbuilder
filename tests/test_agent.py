"""The agent loop with a scripted model: only registered tools are callable,
results flow back into the context, the loop ends on a final message or at
the step cap, and the grammar builds from the registry."""
import json
import time

import pytest

from agent import llm as llm_mod
from agent import tools
from agent.agent import Agent, MAX_STEPS


class FakeOptim:
    def __init__(self):
        self.calls = []

    def optim_state(self):
        self.calls.append(("optim_state", {}))
        return {"ok": True, "params": {"lmy_scale": {}, "aero_scale": {}}, "running": False}

    def optim_inspect_log(self, path):
        self.calls.append(("optim_inspect_log", {"path": path}))
        return {"ok": True, "channels": [{"name": "Zz_Spd", "unit": "m/s"}], "map": {}, "problems": []}

    def optim_start(self, config):
        self.calls.append(("optim_start", config))
        return {"ok": True, "dir": "C:/tmp/study"}


def _wait(agent, timeout=10):
    t0 = time.time()
    while agent.busy() and time.time() - t0 < timeout:
        time.sleep(0.02)
    assert not agent.busy()


def test_registry_matches_optimizer_api_surface():
    from optimizer.api import TOOL_METHODS
    names = set(tools.TOOL_NAMES)
    assert set(TOOL_METHODS) <= names
    assert "read_report" in names
    for t in tools.TOOLS:
        assert t["parameters"]["type"] == "object"
        assert "description" in t and t["description"]


def test_parse_step_accepts_only_registry_tools():
    assert llm_mod.parse_step('{"tool": "optim_state", "args": {}}') == {"tool": "optim_state", "args": {}}
    assert llm_mod.parse_step('```json\n{"final": "done"}\n```') == {"final": "done"}
    with pytest.raises(ValueError):
        llm_mod.parse_step('{"tool": "run_shell", "args": {"cmd": "dir"}}')
    with pytest.raises(ValueError):
        llm_mod.parse_step('no json here')
    with pytest.raises(ValueError):
        llm_mod.parse_step('{"tool": "optim_state", "args": "x"}')


def test_dispatch_refuses_unknown_and_bad_args():
    api = FakeOptim()
    out = json.loads(tools.dispatch(api, "run_shell", {}))
    assert out["ok"] is False and "unknown tool" in out["error"]
    out = json.loads(tools.dispatch(api, "optim_inspect_log", {"nope": 1}))
    assert out["ok"] is False and "bad arguments" in out["error"]
    out = json.loads(tools.dispatch(api, "optim_inspect_log", {"path": "C:/x.mf4"}))
    assert out["ok"] is True and api.calls[-1] == ("optim_inspect_log", {"path": "C:/x.mf4"})


def test_loop_calls_tools_then_finishes():
    api = FakeOptim()
    scripted = llm_mod.ScriptedLLM([
        {"tool": "optim_state", "args": {}},
        {"tool": "optim_inspect_log", "args": {"path": "C:/logs/demo.mf4"}},
        {"final": "The log has one speed channel in m/s; map the pedal next."},
    ])
    ag = Agent(api, scripted)
    ag.send("look at C:/logs/demo.mf4")
    _wait(ag)
    roles = [e["role"] for e in ag.tail()]
    assert roles == ["user", "tool", "result", "tool", "result", "assistant"]
    assert [c[0] for c in api.calls] == ["optim_state", "optim_inspect_log"]
    # tool results were fed back into the model's context
    fed = [m["content"] for m in scripted.calls[-1] if m["role"] == "user"]
    assert any("Tool result for optim_inspect_log" in f and "Zz_Spd" in f for f in fed)
    assert ag.tail()[-1]["text"].startswith("The log has")
    assert ag.error is None


def test_loop_stops_at_step_cap():
    api = FakeOptim()
    scripted = llm_mod.ScriptedLLM([{"tool": "optim_state", "args": {}}] * (MAX_STEPS + 5))
    ag = Agent(api, scripted)
    ag.send("loop forever")
    _wait(ag, timeout=20)
    assert len([c for c in api.calls if c[0] == "optim_state"]) == MAX_STEPS
    assert "without a final answer" in ag.tail()[-1]["text"]


def test_grammar_builds_from_registry():
    pytest.importorskip("llama_cpp")
    from llama_cpp import LlamaGrammar
    g = LlamaGrammar.from_json_schema(json.dumps(llm_mod.response_schema()))
    assert g is not None
