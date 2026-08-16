/* ---------------------------------------------------------------------------
   calib.js — the Calibration tab.

   George's requirement, verbatim: "how will I know the changes I'm making
   are working? ... I just want to know that I'm not just randomly pressing
   buttons." So: every knob carries a plain-language tooltip (what it does,
   which way to turn it, what evidence set its default), and every run is
   scored with DELTAS — green when your change improved the overlay vs the
   previous attempt, red when it made it worse.
--------------------------------------------------------------------------- */

let calibState = null;

function cEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function knobRow(key, meta, val) {
  const tip = cEsc(meta.tip);
  if (meta.options) {
    const opts = meta.options.map(o =>
      `<option value="${o}"${o === val ? " selected" : ""}>${o}</option>`).join("");
    return `<label class="calib-knob" title="${tip}">${cEsc(meta.label)}
      <select id="knob_${key}">${opts}</select>
      <span class="hint knob-hint">${tip}</span></label>`;
  }
  return `<label class="calib-knob" title="${tip}">${cEsc(meta.label)}
    <input type="number" id="knob_${key}" value="${val}"
      min="${meta.range[0]}" max="${meta.range[1]}" step="${meta.step}">
    <span class="hint knob-hint">${tip}</span></label>`;
}

function renderKnobs() {
  const box = $("#calibKnobs");
  if (!calibState) { box.innerHTML = "<p class='hint'>Loading…</p>"; return; }
  box.innerHTML = Object.entries(calibState.meta)
    .map(([k, m]) => knobRow(k, m, calibState.knobs[k])).join("");
}

function deltaCell(cur, prev, lowerIsBetter) {
  if (prev === null || prev === undefined) return `<td>${cur}</td>`;
  const d = cur - prev;
  const better = lowerIsBetter ? d < 0 : d > 0;
  const cls = Math.abs(d) < 1e-9 ? "" : (better ? "calib-better" : "calib-worse");
  const arrow = Math.abs(d) < 1e-9 ? "" : (better ? " ▼" : " ▲");
  return `<td class="${cls}">${cur}${arrow}</td>`;
}

function renderHistory() {
  const t = $("#calibHistory");
  const h = (calibState && calibState.history) || [];
  if (!h.length) {
    t.innerHTML = "<tr><td class='hint'>No attempts yet — set the knobs and " +
                  "hit Run &amp; Score. The first run becomes your baseline.</td></tr>";
    return;
  }
  let html = "<thead><tr><th>#</th><th>when</th><th>pedal gain</th><th>EMS</th>" +
             "<th>LMY</th><th>smooth</th><th>speed RMSE</th><th>speed corr</th>" +
             "<th>torque RMSE</th><th>torque corr</th></tr></thead><tbody>";
  h.forEach((r, i) => {
    const p = i > 0 ? h[i - 1] : null;
    html += `<tr><td>${i + 1}</td><td>${cEsc(r.when)}</td>` +
      `<td>${r.knobs.pedal_gain}</td><td>${cEsc(r.knobs.ems)}</td>` +
      `<td>${r.knobs.lmy}</td><td>${r.knobs.smoothing_hz}</td>` +
      deltaCell(r.speed_rmse, p && p.speed_rmse, true) +
      deltaCell(r.speed_corr, p && p.speed_corr, false) +
      deltaCell(r.torque_rmse, p && p.torque_rmse, true) +
      deltaCell(r.torque_corr, p && p.torque_corr, false) + "</tr>";
  });
  t.innerHTML = html + "</tbody>";
  // best-so-far banner
  const best = h.reduce((a, b) => (b.speed_rmse < a.speed_rmse ? b : a));
  $("#calibBest").textContent =
    "Best so far: speed RMSE " + best.speed_rmse + " km/h (corr " +
    best.speed_corr + "), torque RMSE " + best.torque_rmse + " Nm — from " +
    best.when + ". Lower RMSE and higher corr = the overlay tracks the real " +
    "car better.";
}

async function calibLoad() {
  if (!window.pywebview) {
    $("#calibHint").textContent =
      "The Calibration tab runs inside the SimBuilder app.";
    return;
  }
  calibState = await pywebview.api.calib_state();
  renderKnobs(); renderHistory();
  $("#calibHint").textContent = calibState.reference.ok
    ? "Reference: the 61 s MCT city window (real pedal + torque). Set knobs, " +
      "then Run & Score (~15 min, machine-guarded)."
    : "Reference log missing — expected OVERLAY - Real vs Virtual\\REAL_mct_chunk_full.mf4";
}

async function calibRun() {
  if (!window.pywebview) return;
  const knobs = {};
  for (const k of Object.keys(calibState.meta)) {
    const el = $("#knob_" + k);
    knobs[k] = el.tagName === "SELECT" ? el.value : parseFloat(el.value);
  }
  $("#btnCalibRun").disabled = true;
  $("#calibHint").textContent =
    "Running the replay with your knob settings… (~15 min; scores appear in " +
    "the history when done)";
  try {
    const res = await pywebview.api.calib_run(knobs);
    if (res && res.ok) {
      calibState = await pywebview.api.calib_state();
      renderHistory();
      $("#calibHint").textContent =
        "Scored. Green ▼/▲ in the history = this change IMPROVED the overlay " +
        "vs your previous attempt; red = it made it worse.";
    } else {
      $("#calibHint").textContent = "Run failed: " + ((res && res.error) || "?");
    }
  } catch (e) {
    $("#calibHint").textContent = "Run failed: " + e;
  } finally {
    $("#btnCalibRun").disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const b = $("#btnCalibRun");
  if (b) b.onclick = calibRun;
});
window.calibOnEnter = calibLoad;
