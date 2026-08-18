/* ---------------------------------------------------------------------------
   gym.js — the RL Gym tab. Hand-holdy by design (George's order): a 3-step
   wizard (what comfort means -> which workout -> train), a live coach feed
   while training runs, and a graduates table that compares every brain to
   the stock map baseline scored in the same session.
--------------------------------------------------------------------------- */

let gymState = null;
let gymPoll = null;

function gEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function gymRenderKnobs() {
  const box = $("#gymKnobs");
  box.innerHTML = Object.entries(gymState.knobs).map(([k, m]) =>
    `<label class="calib-knob" title="${gEsc(m.tip)}">${gEsc(m.label)}
       <input type="number" id="gym_${k}" value="${m.default}" step="${m.step}" min="0">
       <span class="hint knob-hint">${gEsc(m.tip)}</span></label>`).join("");
}

function gymRenderWorkouts() {
  const box = $("#gymWorkouts");
  box.innerHTML = Object.entries(gymState.workouts).map(([k, d], i) =>
    `<label class="calib-knob"><input type="radio" name="gymWorkout"
       value="${k}" ${i === 1 ? "checked" : ""}> <b>${k}</b>
       <span class="hint knob-hint">${gEsc(d)}</span></label>`).join("");
}

function gymRenderHistory() {
  const t = $("#gymHistory");
  const h = (gymState && gymState.history) || [];
  if (!h.length) {
    t.innerHTML = "<tr><td class='hint'>No graduates yet. Run your first " +
                  "training session - the first one becomes your baseline " +
                  "story.</td></tr>";
    return;
  }
  let html = "<thead><tr><th>when</th><th>workout</th><th>comfort wt</th>" +
             "<th>Wh/km (vs stock)</th><th>discomfort (vs stock)</th>" +
             "<th>wakes/min</th></tr></thead><tbody>";
  h.slice().reverse().forEach(r => {
    const dW = r.wh_per_km - r.baseline_wh;
    const dD = r.discomfort - r.baseline_disc;
    const cW = dW < 0 ? "calib-better" : "calib-worse";
    const cD = dD < 0 ? "calib-better" : "calib-worse";
    html += `<tr><td>${gEsc(r.when)}</td><td>${gEsc(r.workout)}</td>` +
      `<td>${r.wc}</td>` +
      `<td class="${cW}">${r.wh_per_km.toFixed(1)} (${dW >= 0 ? "+" : ""}${dW.toFixed(1)})</td>` +
      `<td class="${cD}">${r.discomfort.toFixed(1)} (${dD >= 0 ? "+" : ""}${dD.toFixed(1)})</td>` +
      `<td>${r.engage_per_min.toFixed(1)}</td></tr>`;
  });
  t.innerHTML = html + "</tbody>";
}

function gymSetBusy(running, kind) {
  $("#btnGymTrain").disabled = running;
  $("#btnGymScore").disabled = running;
  $("#btnGymStop").style.display = running ? "" : "none";
  $("#gymCoach").style.display = running ? "" : "none";
  if (!running && gymPoll) { clearInterval(gymPoll); gymPoll = null; }
}

async function gymTick() {
  const t = await pywebview.api.gym_tail();
  $("#gymLog").textContent = (t.lines || []).join("\n") || "warming up...";
  if (!t.running) {
    gymSetBusy(false);
    $("#gymHint").textContent = "Session finished. Fresh graduates below - " +
      "green means better than the stock map on the same workout.";
    gymState = await pywebview.api.gym_state();
    gymRenderHistory();
  }
}

async function gymTrain() {
  const cfg = {
    c_jerk: parseFloat($("#gym_c_jerk").value),
    c_engage: parseFloat($("#gym_c_engage").value),
    c_rate: parseFloat($("#gym_c_rate").value),
    workout: document.querySelector("input[name=gymWorkout]:checked").value,
    steps: parseInt($("#gymEffort").value, 10),
    weights: [0.0, 1.0],
    seeds: 2,
  };
  const res = await pywebview.api.gym_train(cfg);
  if (!res.ok) { $("#gymHint").textContent = "Could not start: " + res.error; return; }
  $("#gymHint").textContent = "Training started. You can leave this tab - " +
    "the session keeps running and the coach feed below shows progress.";
  gymSetBusy(true, "train");
  gymPoll = setInterval(gymTick, 3000);
}

async function gymScore() {
  const res = await pywebview.api.gym_rescore();
  if (!res.ok) { $("#gymHint").textContent = "Could not start: " + res.error; return; }
  $("#gymHint").textContent = "Scoring everything at equal footing (~2 min)...";
  gymSetBusy(true, "score");
  gymPoll = setInterval(gymTick, 3000);
}

async function gymLoad() {
  if (!window.pywebview) {
    $("#gymHint").textContent = "The RL Gym runs inside the SimBuilder app.";
    return;
  }
  gymState = await pywebview.api.gym_state();
  if (!gymState.gym_ok) {
    $("#gymHint").textContent = "rl_gym folder not found next to the app - " +
      "run from the repo checkout.";
    return;
  }
  gymRenderKnobs(); gymRenderWorkouts(); gymRenderHistory();
  gymSetBusy(gymState.running, gymState.kind);
  if (gymState.running) {
    $("#gymHint").textContent = "A session is already running - live feed below.";
    gymPoll = setInterval(gymTick, 3000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const bt = $("#btnGymTrain"); if (bt) bt.onclick = gymTrain;
  const bs = $("#btnGymScore"); if (bs) bs.onclick = gymScore;
  const bx = $("#btnGymStop");
  if (bx) bx.onclick = async () => { await pywebview.api.gym_stop(); gymSetBusy(false); };
});
window.gymOnEnter = gymLoad;
