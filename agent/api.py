"""
agent/api.py
================================================================================
agent_* methods exposed on main.Api (forwarded). The model file is a local
setting; without it the chat explains what to do rather than failing.
================================================================================
"""
import os

import pipeline
from . import llm as llm_mod
from .agent import Agent


def _err(exc):
    return {"ok": False, "error": "{}: {}".format(type(exc).__name__, str(exc)[:300])}


class AgentApi:
    def __init__(self, api, optim_api):
        self.api = api
        self.optim_api = optim_api
        self.agent = None

    def _llm(self):
        s = self.api.settings
        return llm_mod.LocalLLM(s.get("llm_model_path") or "", n_ctx=s.get("llm_ctx") or 8192,
                                n_gpu_layers=s.get("llm_gpu_layers") or 0,
                                n_threads=s.get("llm_threads"))

    def _agent(self):
        if self.agent is None:
            self.agent = Agent(self.optim_api, self._llm(), log=self.api._log)
        return self.agent

    def agent_state(self):
        try:
            s = self.api.settings
            mp = s.get("llm_model_path") or ""
            try:
                import llama_cpp
                runtime = "llama-cpp-python {}".format(llama_cpp.__version__)
            except Exception as exc:
                runtime = None
            ag = self.agent
            return {"ok": True, "model_path": mp, "model_ok": bool(mp and os.path.isfile(mp)),
                    "model_name": os.path.basename(mp) if mp else "", "runtime": runtime,
                    "gpu_layers": s.get("llm_gpu_layers") or 0, "ctx": s.get("llm_ctx") or 8192,
                    "busy": bool(ag and ag.busy()), "loaded": bool(ag and ag.llm.loaded),
                    "transcript": ag.tail() if ag else [], "error": ag.error if ag else None}
        except Exception as exc:
            return _err(exc)

    def agent_pick_model(self):
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=("GGUF model (*.gguf)", "All files (*.*)"))
        if result:
            self.api.settings["llm_model_path"] = result[0]
            pipeline.save_settings(self.api.settings)
            self.agent = None          # reload with the new model on the next message
        return self.agent_state()

    def agent_set(self, key, value):
        """llm_gpu_layers / llm_ctx / llm_threads from the page."""
        try:
            if key not in ("llm_gpu_layers", "llm_ctx", "llm_threads"):
                return {"ok": False, "error": "not a model setting"}
            self.api.settings[key] = int(value)
            pipeline.save_settings(self.api.settings)
            self.agent = None
            return self.agent_state()
        except Exception as exc:
            return _err(exc)

    def agent_send(self, text):
        try:
            text = (text or "").strip()
            if not text:
                return {"ok": False, "error": "empty message"}
            ag = self._agent()
            if not ag.llm.available():
                return {"ok": False, "error": "no model file: pick a GGUF model first "
                                              "(settings llm_model_path)"}
            ag.send(text)
            return {"ok": True}
        except Exception as exc:
            return _err(exc)

    def agent_tail(self):
        try:
            ag = self.agent
            return {"ok": True, "busy": bool(ag and ag.busy()),
                    "transcript": ag.tail() if ag else [], "error": ag.error if ag else None}
        except Exception as exc:
            return _err(exc)

    def agent_stop(self):
        try:
            if self.agent:
                self.agent.stop()
            return {"ok": True}
        except Exception as exc:
            return _err(exc)

    def agent_reset(self):
        try:
            if self.agent:
                self.agent.reset()
            return {"ok": True}
        except Exception as exc:
            return _err(exc)
