"""
Hidden-window self-test of the Optimizer tab through the REAL pywebview bridge
(not a pytest):   python tests/ui_selftest.py

Opens the app's page in a hidden pywebview window with the real Api, switches
to the Optimizer tab, lets it load optim_state / agent_state over the bridge,
reads the DOM back and prints a short report. No screenshots, no vehicle
values: only element counts, flags and the hint texts.
"""
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import webview   # noqa: E402

import main      # noqa: E402

JS = r"""
(async () => {
  const out = {};
  try {
    document.querySelector('.tab[data-tab="optimizer"]').click();
    await new Promise(r => setTimeout(r, 1500));
    out.active = document.querySelector('.tab.active').dataset.tab;
    out.cards = document.querySelectorAll('#tab-optimizer .card').length;
    out.hint = document.getElementById('optimHint').textContent;
    out.setup = document.getElementById('optimSetup').textContent.slice(0, 160);
    out.params = document.querySelectorAll('#optimParams .optim-param').length;
    out.weights = document.querySelectorAll('#optimWeights input').length;
    out.history_rows = document.querySelectorAll('#optimHistory tr').length;
    out.start_disabled = document.getElementById('btnOptimStart').disabled;
    out.start_hint = document.getElementById('optimStartHint').textContent;
    out.agent_hint = document.getElementById('agentHint').textContent;
    const st = await pywebview.api.optim_state();
    out.bridge_ok = st.ok; out.roles = (st.roles || []).length; out.base_tyre_ok = st.base_files && st.base_files.tire_ok;
    const ag = await pywebview.api.agent_state();
    out.agent_ok = ag.ok; out.agent_runtime = ag.runtime;
    const inspect = await pywebview.api.optim_inspect_log('C:/does/not/exist.mf4');
    out.inspect_missing_handled = inspect.ok === false && typeof inspect.error === 'string';
  } catch (e) { out.error = String(e); }
  window.__selftest = out;      // evaluate_js does not await a promise: poll this
})(); true
"""


def drive(window):
    deadline = time.time() + 60
    result = None
    # wait for the page and the bridge
    while time.time() < deadline:
        try:
            ready = window.evaluate_js("!!(window.pywebview && window.pywebview.api && typeof optimLoad === 'function')")
            if ready:
                break
        except Exception:
            pass
        time.sleep(0.5)
    try:
        window.evaluate_js(JS)
        while time.time() < deadline:
            raw = window.evaluate_js("window.__selftest ? JSON.stringify(window.__selftest) : null")
            if raw:
                result = json.loads(raw)
                break
            time.sleep(0.5)
        if result is None:
            result = {"error": "timed out waiting for the page"}
    except Exception as exc:
        result = {"error": str(exc)}
    print(json.dumps(result, indent=1))
    ok = isinstance(result, dict) and result.get("bridge_ok") and result.get("agent_ok") \
        and result.get("active") == "optimizer" and result.get("cards", 0) >= 8 \
        and result.get("params") == 2 and result.get("inspect_missing_handled")
    print("UI SELFTEST", "PASS" if ok else "FAIL")
    window.destroy()


if __name__ == "__main__":
    api = main.Api()
    w = webview.create_window("SimBuilder selftest", main.web_index(), js_api=api,
                              width=1200, height=800, hidden=True)
    webview.start(drive, w, private_mode=True)
