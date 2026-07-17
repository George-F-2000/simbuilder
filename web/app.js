"use strict";

/* ================================================================
   Scenario Builder — longitudinal maneuver -> Altair Driver .adf
   Format reference: decompiled ADFBase writers (ADFtemplates.pyc,
   Altair 2025) + Model_Run_doublelane_0.adf sample.
   ================================================================ */

const KPH2MMS = 1000 / 3.6; // kph -> mm/s (ADF base units are mm/N/rad/kg/s)

/* ---------------- default scenario: AVL tip-out / tip-in ---------------- */

function exampleScenario() {
  return {
    name: "TipOut_TipIn_50_20",
    startSpeedKph: 0,
    engineInit: 300,
    hmax: 0.01,
    printInterval: 0.01,
    smoothingHz: 10,
    preview: { mass: 2200, fmax: 9000, fbrk: 14000, cda: 0.70, crr: 0.010 },
    phases: [
      { thrMode: "hold", thrPct: 10, thrRise: 0.3,
        brkMode: "hold", brkPct: 0,  brkRise: 0.3,
        exitType: "speed_above", exitValue: 50, maxTime: 60 },
      { thrMode: "step", thrPct: 0,  thrRise: 0.3,
        brkMode: "hold", brkPct: 0,  brkRise: 0.3,
        exitType: "speed_below", exitValue: 20, maxTime: 60 },
      { thrMode: "step", thrPct: 10, thrRise: 0.3,
        brkMode: "hold", brkPct: 0,  brkRise: 0.3,
        exitType: "duration", exitValue: 5, maxTime: 60 },
      { thrMode: "step", thrPct: 0,  thrRise: 0.5,
        brkMode: "hold", brkPct: 0,  brkRise: 0.3,
        exitType: "duration", exitValue: 10, maxTime: 60 },
    ],
  };
}

let sc = loadStored() || exampleScenario();
// 10 ms is the finest step ever needed for these runs (George's rule) -
// migrate stored scenarios still carrying the old 1 ms default
if (sc.hmax < 0.01) sc.hmax = 0.01;
let adfText = ""; // current generated .adf (plain text, used by copy/download)

/* ---------------- DOM helpers ---------------- */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------------- dark mode (applied ASAP to avoid a light flash) -------- */
(function () {
  const dark = localStorage.getItem("simbuilder.theme") === "dark";
  if (dark) document.body.classList.add("dark");
  window.addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("btnTheme");
    const paint = () => b.textContent =
      document.body.classList.contains("dark") ? "☀️" : "🌙";
    b.onclick = () => {
      document.body.classList.toggle("dark");
      localStorage.setItem("simbuilder.theme",
        document.body.classList.contains("dark") ? "dark" : "light");
      paint();
    };
    paint();
  });
})();

function bindScenarioInputs() {
  $("#pmInherit").checked = sc.preview.inherit !== false;   // default on
  $("#scName").value = sc.name;
  $("#scStartSpeed").value = sc.startSpeedKph;
  $("#scHmax").value = sc.hmax;
  $("#scPrint").value = sc.printInterval;
  $("#scSmooth").value = sc.smoothingHz;
  $("#scEngInit").value = sc.engineInit;
  $("#pmMass").value = sc.preview.mass;
  $("#pmFmax").value = sc.preview.fmax;
  $("#pmFbrk").value = sc.preview.fbrk;
  $("#pmCdA").value = sc.preview.cda;
  $("#pmCrr").value = sc.preview.crr;
}

function readScenarioInputs() {
  sc.name = $("#scName").value.trim() || "Scenario";
  sc.startSpeedKph = num($("#scStartSpeed").value, 0);
  sc.hmax = Math.max(num($("#scHmax").value, 0.01), 0.01);   // never finer than 10 ms
  sc.printInterval = num($("#scPrint").value, 0.01);
  sc.smoothingHz = num($("#scSmooth").value, 10);
  sc.engineInit = num($("#scEngInit").value, 300);
  sc.preview.mass = num($("#pmMass").value, 2200);
  sc.preview.fmax = num($("#pmFmax").value, 9000);
  sc.preview.fbrk = num($("#pmFbrk").value, 14000);
  sc.preview.cda = num($("#pmCdA").value, 0.70);
  sc.preview.crr = num($("#pmCrr").value, 0.010);

  // inherit the preview car from the Vehicle Builder (default): mass, CdA
  // and tractive force are computed from the vehicle and the fields lock
  sc.preview.inherit = $("#pmInherit").checked;
  if (sc.preview.inherit && typeof vehPreviewParams === "function") {
    const p = vehPreviewParams();
    if (p) {
      sc.preview.mass = p.mass;
      sc.preview.cda = p.cda;
      $("#pmMass").value = p.mass;
      $("#pmCdA").value = p.cda.toFixed(3);
      if (p.fmax) {
        sc.preview.fmax = p.fmax;
        $("#pmFmax").value = Math.round(p.fmax);
      }
    }
  }
  ["pmMass", "pmCdA", "pmFmax"].forEach(
    id => $("#" + id).disabled = sc.preview.inherit);
}

function num(v, fallback) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

/* ---------------- phase cards ---------------- */

function renderPhases() {
  const list = $("#phaseList");
  list.innerHTML = "";
  sc.phases.forEach((p, i) => {
    const node = $("#phaseTemplate").content.firstElementChild.cloneNode(true);
    $(".phase-num", node).textContent = `Phase ${i + 1}`;

    $(".thrMode", node).value = p.thrMode;
    $(".thrPct", node).value = p.thrPct;
    $(".thrRise", node).value = p.thrRise;
    $(".brkMode", node).value = p.brkMode;
    $(".brkPct", node).value = p.brkPct;
    $(".brkRise", node).value = p.brkRise;
    $(".exitType", node).value = p.exitType;
    $(".exitValue", node).value = p.exitValue;
    $(".maxTime", node).value = p.maxTime;

    syncPhaseCardVisibility(node, p);

    node.addEventListener("input", () => {
      p.thrMode = $(".thrMode", node).value;
      p.thrPct = num($(".thrPct", node).value, 0);
      p.thrRise = num($(".thrRise", node).value, 0.3);
      p.brkMode = $(".brkMode", node).value;
      p.brkPct = num($(".brkPct", node).value, 0);
      p.brkRise = num($(".brkRise", node).value, 0.3);
      p.exitType = $(".exitType", node).value;
      p.exitValue = num($(".exitValue", node).value, 0);
      p.maxTime = num($(".maxTime", node).value, 60);
      syncPhaseCardVisibility(node, p);
      refresh(false);
    });

    $(".up", node).onclick = e => { e.stopPropagation(); if (i > 0) { swap(i, i - 1); } };
    $(".down", node).onclick = e => { e.stopPropagation(); if (i < sc.phases.length - 1) { swap(i, i + 1); } };
    $(".dup", node).onclick = e => { e.stopPropagation(); sc.phases.splice(i + 1, 0, { ...p }); refresh(true); };
    $(".del", node).onclick = e => {
      e.stopPropagation();
      if (sc.phases.length > 1) { sc.phases.splice(i, 1); refresh(true); }
    };

    $(".phase-head", node).onclick = () => locatePhase(i);

    list.appendChild(node);
  });
}

function syncPhaseCardVisibility(node, p) {
  $(".thrRiseWrap", node).classList.toggle("hidden", p.thrMode !== "step");
  $(".brkRiseWrap", node).classList.toggle("hidden", p.brkMode !== "step");
  const isDuration = p.exitType === "duration";
  $(".exitUnit", node).textContent = isDuration ? "s" : "kph";
  $(".capWrap", node).classList.toggle("hidden", isDuration);
}

function swap(a, b) {
  [sc.phases[a], sc.phases[b]] = [sc.phases[b], sc.phases[a]];
  refresh(true);
}

/* ---------------- preview simulation (point mass) ---------------- */

// MotionSolve-style cubic STEP(x, x0, h0, x1, h1)
function stepVal(x, x0, h0, x1, h1) {
  if (x <= x0) return h0;
  if (x >= x1) return h1;
  const r = (x - x0) / (x1 - x0);
  return h0 + (h1 - h0) * r * r * (3 - 2 * r);
}

function simulate() {
  const dt = 0.02, G = 9.81, RHO = 1.204;
  const m = sc.preview.mass, fmax = sc.preview.fmax, fbrk = sc.preview.fbrk;
  const cda = sc.preview.cda, crr = sc.preview.crr;

  let v = sc.startSpeedKph / 3.6; // m/s
  let thr = 0, brk = 0;
  let t = 0;
  const out = { t: [], thr: [], brk: [], v: [], bounds: [], warnings: [], phaseEnds: [] };

  for (let pi = 0; pi < sc.phases.length; pi++) {
    const p = sc.phases[pi];
    const thrStart = thr, brkStart = brk;
    const cap = p.exitType === "duration" ? p.exitValue : p.maxTime;
    let tp = 0, met = false;

    while (tp < cap - 1e-9) {
      thr = p.thrMode === "step"
        ? stepVal(tp, 0, thrStart, p.thrRise, p.thrPct / 100)
        : p.thrPct / 100;
      brk = p.brkMode === "step"
        ? stepVal(tp, 0, brkStart, p.brkRise, p.brkPct / 100)
        : p.brkPct / 100;

      const fDrag = 0.5 * RHO * cda * v * v;
      const fRoll = v > 0.05 ? crr * m * G : 0;
      const fBrake = v > 0.02 ? brk * fbrk : 0;
      const a = (thr * fmax - fBrake - fDrag - fRoll) / m;
      v = Math.max(0, v + a * dt);

      t += dt; tp += dt;
      out.t.push(t); out.thr.push(thr * 100); out.brk.push(brk * 100); out.v.push(v * 3.6);

      if (p.exitType === "speed_above" && v * 3.6 >= p.exitValue) { met = true; break; }
      if (p.exitType === "speed_below" && v * 3.6 <= p.exitValue) { met = true; break; }
      if (out.t.length > 60000) break; // hard stop: 20 min of sim
    }

    if (p.exitType !== "duration" && !met) {
      out.warnings.push(`Phase ${pi + 1}: exit condition (${p.exitType === "speed_above" ? "≥" : "≤"} ${p.exitValue} kph) not reached in preview — maneuver would end at its ${cap}s cap. Real vehicle may differ.`);
    }
    out.bounds.push(t);
    out.phaseEnds.push({ met, tEnd: t });
  }
  return out;
}

/* ---------------- plotting ---------------- */

function drawPlot(canvas, series, opts) {
  const dpr = window.devicePixelRatio || 1;
  const wCss = canvas.clientWidth || canvas.parentElement.clientWidth || 600;
  const hCss = canvas.getAttribute("height") ? parseInt(canvas.getAttribute("height")) : 200;
  canvas.width = wCss * dpr;
  canvas.height = hCss * dpr;
  canvas.style.height = hCss + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const padL = 46, padR = 12, padT = 20, padB = 24;
  const W = wCss - padL - padR, H = hCss - padT - padB;

  ctx.clearRect(0, 0, wCss, hCss);
  ctx.font = "11px Segoe UI";

  const tMax = Math.max(1, opts.tMax);
  let yMax = opts.yMax;
  for (const s of series) for (const val of s.y) if (val > yMax) yMax = val;
  yMax *= 1.08;

  const X = tv => padL + (tv / tMax) * W;
  const Y = yv => padT + H - (yv / yMax) * H;

  // phase shading + boundary lines
  let prev = 0;
  (opts.bounds || []).forEach((b, i) => {
    if (i % 2 === 1) {
      ctx.fillStyle = "rgba(11,110,153,0.06)";
      ctx.fillRect(X(prev), padT, X(b) - X(prev), H);
    }
    ctx.strokeStyle = "rgba(11,110,153,0.35)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(X(b), padT); ctx.lineTo(X(b), padT + H); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#64748b";
    const mid = X(prev) + (X(b) - X(prev)) / 2;
    ctx.fillText(`P${i + 1}`, mid - 7, padT - 7);
    prev = b;
  });

  // axes + gridlines
  ctx.strokeStyle = "#dbe2ea";
  ctx.fillStyle = "#64748b";
  const yTicks = 4;
  for (let i = 0; i <= yTicks; i++) {
    const yv = (yMax / yTicks) * i;
    ctx.beginPath(); ctx.moveTo(padL, Y(yv)); ctx.lineTo(padL + W, Y(yv)); ctx.stroke();
    ctx.fillText(yv.toFixed(0), 8, Y(yv) + 4);
  }
  const xTicks = Math.min(10, Math.ceil(tMax));
  for (let i = 0; i <= xTicks; i++) {
    const tv = (tMax / xTicks) * i;
    ctx.fillText(tv.toFixed(0), X(tv) - 6, padT + H + 16);
  }

  // threshold lines (speed plot)
  (opts.thresholds || []).forEach(th => {
    ctx.strokeStyle = "rgba(192,57,43,0.5)";
    ctx.setLineDash([6, 3]);
    ctx.beginPath(); ctx.moveTo(padL, Y(th)); ctx.lineTo(padL + W, Y(th)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(192,57,43,0.8)";
    ctx.fillText(`${th} kph`, padL + W - 46, Y(th) - 4);
  });

  // series
  series.forEach(s => {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1.8;
    if (s.dash) ctx.setLineDash(s.dash);
    ctx.beginPath();
    s.x.forEach((tv, i) => { i === 0 ? ctx.moveTo(X(tv), Y(s.y[i])) : ctx.lineTo(X(tv), Y(s.y[i])); });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 1;
  });

  // title + legend
  ctx.fillStyle = "#1c2733";
  ctx.font = "600 12px Segoe UI";
  ctx.fillText(opts.title, padL, 12);
  let lx = padL + ctx.measureText(opts.title).width + 18;
  ctx.font = "11px Segoe UI";
  series.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2;
    if (s.dash) ctx.setLineDash(s.dash);
    ctx.beginPath(); ctx.moveTo(lx, 8); ctx.lineTo(lx + 16, 8); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#64748b";
    ctx.fillText(s.label, lx + 20, 12);
    lx += 20 + ctx.measureText(s.label).width + 14;
  });
}

function drawPlots(sim) {
  const tMax = sim.t.length ? sim.t[sim.t.length - 1] : 1;
  drawPlot($("#pedalPlot"),
    [
      { x: sim.t, y: sim.thr, color: "#0b6e99", label: "accel pedal" },
      { x: sim.t, y: sim.brk, color: "#c0392b", label: "brake", dash: [5, 3] },
    ],
    { title: "Driver inputs (%)", tMax, yMax: 100, bounds: sim.bounds });

  const thresholds = sc.phases.filter(p => p.exitType !== "duration").map(p => p.exitValue);
  drawPlot($("#speedPlot"),
    [{ x: sim.t, y: sim.v, color: "#0b6e99", label: "vehicle speed" }],
    { title: "Estimated speed (kph)", tMax, yMax: 10, bounds: sim.bounds, thresholds });

  // standstill starts make this model's tires numerically stiff: the solver
  // drops to ~40 microsecond steps at pull-away no matter what h_max says
  // (measured: 0.6 sim-seconds in 3.5 wall-minutes). Warn loudly.
  const extra = [];
  if (sc.startSpeedKph < 5) {
    extra.push("Start speed is " + sc.startSpeedKph + " kph: standstill " +
      "pull-away is numerically very stiff in this model and the solver " +
      "can take HOURS regardless of the time-step setting. A rolling " +
      "start (≥ 10 kph) solves ~100× faster.");
  }
  $("#warnings").innerHTML = sim.warnings.concat(extra)
    .map(w => `<div class="warn">&#9888; ${w}</div>`).join("");
}

/* ---------------- ADF generation ---------------- */

function fmt(x, dec = 3) {
  const r = Math.round(x * 10 ** dec) / 10 ** dec;
  return Number.isInteger(r) ? String(r) : String(r);
}

function sectionHeader(label) {
  const pad = 84 - label.length;
  return "$" + "-".repeat(Math.max(4, pad)) + label + "\n";
}

function standardBlock(name, maxV, minV, smooth, init) {
  let s = sectionHeader(name + "_STANDARD");
  s += `[${name}_STANDARD]\n`;
  s += `MAX_VALUE            = ${maxV}\n`;
  s += `MIN_VALUE            = ${minV}\n`;
  s += `SMOOTHING_FREQUENCY  = ${smooth}\n`;
  s += `INITIAL_VALUE        = ${init}\n`;
  return s;
}

function openLoopBlock(name, type, attr, channel) {
  let s = sectionHeader(name);
  s += `[${name}]\n`;
  s += `TAG                    = 'OPENLOOP'\n`;
  s += `TYPE                   = '${type}'\n`;
  if (type === "CONSTANT") s += `VALUE                  = ${attr}\n`;
  if (type === "EXPRESSION") {
    s += `EXPRESSION             = '${attr}'\n`;
    s += `SIGNAL_CHANNEL         = ${channel}\n`;
  }
  return s;
}

function generateHeaderText() {
  const smooth = sc.smoothingHz;
  let s = "";

  s += sectionHeader("ALTAIR_HEADER");
  s += "[ALTAIR_HEADER]\n";
  s += "FILE_TYPE    = 'ADF'\n";
  s += "FILE_VERSION = 2.0\n";
  s += "FILE_FORMAT  = 'ASCII'\n";
  s += `$ Scenario: ${sc.name} — generated by Scenario Builder\n`;

  s += sectionHeader("UNITS");
  s += "[UNITS]\n(BASE)\n";
  s += "{ length  force         angle           mass     time }\n";
  s += "  'mm'   'newton'      'radians'        'kg'    'sec'\n";

  s += sectionHeader("VEHICLE_IC");
  s += "[VEHICLE_INITIAL_CONDITIONS]\n";
  s += "$These are wrt vehicle orientation marker\n";
  s += `VX0               = ${fmt(sc.startSpeedKph * KPH2MMS)}\n`;
  s += "VY0               = 0.0\n";
  s += "VZ0               = 0.0\n";
  s += `ENGINE_INIT_SPEED = ${fmt(sc.engineInit)}\n`;

  s += standardBlock("STEER", 9.4248, -9.4248, smooth, 0);
  s += standardBlock("THROTTLE", 1, 0, smooth, 0);
  s += standardBlock("BRAKE", 1, 0, smooth, 0);
  s += standardBlock("GEAR", 6, 1, smooth, 1);
  s += standardBlock("CLUTCH", 1, 0, smooth, 0);

  // ---- maneuvers list: sim_time acts as the cap; end conditions cut it short
  s += sectionHeader("MANEUVERS_LIST");
  s += "[MANEUVERS_LIST]\n";
  s += "{" + "name".padEnd(15) + " " + "simulation_time".padEnd(20) + " " + "h_max".padEnd(15) + " " + "print_interval".padEnd(15) + "}\n";
  sc.phases.forEach((p, i) => {
    const cap = p.exitType === "duration" ? p.exitValue : p.maxTime;
    s += ("'MANEUVER_" + (i + 1) + "'").padEnd(16) + " "
      + String(fmt(cap, 2)).padEnd(20) + " "
      + String(sc.hmax).padEnd(15) + " "
      + String(sc.printInterval).padEnd(16) + "\n";
  });

  return s;
}

function phaseBlockText(p, i) {
    let s = "";
    const n = i + 1;
    const thrName = `OL_THROTTLE_${n}`, brkName = `OL_BRAKE_${n}`;

    s += sectionHeader(`MANEUVER_${n}`);
    s += `[MANEUVER_${n}]\n`;
    s += "TASK = 'STANDARD'\n";
    s += "(CONTROLLERS)\n";
    s += "{" + "DRIVER_SIGNAL".padEnd(25) + " " + "PRIMARY_CONTROLLER".padEnd(25) + " " + "ADDITIONAL_CONTROLLER".padEnd(25) + "}\n";
    s += " " + "STEER".padEnd(25) + " " + "OL_STEER".padEnd(25) + " " + "NONE".padEnd(25) + "\n";
    s += " " + "THROTTLE".padEnd(25) + " " + thrName.padEnd(25) + " " + "NONE".padEnd(25) + "\n";
    s += " " + "BRAKE".padEnd(25) + " " + brkName.padEnd(25) + " " + "NONE".padEnd(25) + "\n";
    s += " " + "GEAR".padEnd(25) + " " + "GEAR_CLUTCH_CONTROL".padEnd(25) + " " + "NONE".padEnd(25) + "\n";
    s += " " + "CLUTCH".padEnd(25) + " " + "GEAR_CLUTCH_CONTROL".padEnd(25) + " " + "NONE".padEnd(25) + "\n";

    if (p.exitType !== "duration") {
      // mirrors ADFBase.writeEndConditions: tol = 5% of value, watch_time 0.001
      const val = p.exitValue * KPH2MMS;
      const op = p.exitType === "speed_above" ? "GT" : "LT";
      s += "(END_CONDITIONS) \n";
      s += "{" + "SIGNAL".padEnd(10) + " " + "GROUP".padEnd(10) + " " + "ABS".padEnd(10) + " " + "OPERATOR".padEnd(10) + " " + "VALUE".padEnd(10) + " " + "TOLERANCE".padEnd(10) + " " + "WATCH_TIME".padEnd(10) + "}\n";
      s += " " + "LONG_VEL".padEnd(10) + " " + "0".padEnd(10) + " " + "Y".padEnd(10) + " " + op.padEnd(10) + " "
        + fmt(val).padEnd(10) + " " + fmt(0.05 * val).padEnd(10) + " " + "0.001".padEnd(10) + "\n";
    }

    // throttle controller
    if (p.thrMode === "step") {
      const expr = `STEP({%TIME},0,{THROTTLE_0},${fmt(Math.max(0.01, p.thrRise), 4)},${fmt(p.thrPct / 100, 4)})`;
      s += openLoopBlock(thrName, "EXPRESSION", expr, 0);
    } else {
      s += openLoopBlock(thrName, "CONSTANT", fmt(p.thrPct / 100, 4));
    }
    // brake controller
    if (p.brkMode === "step") {
      const expr = `STEP({%TIME},0,{BRAKE_0},${fmt(Math.max(0.01, p.brkRise), 4)},${fmt(p.brkPct / 100, 4)})`;
      s += openLoopBlock(brkName, "EXPRESSION", expr, 1);
    } else {
      s += openLoopBlock(brkName, "CONSTANT", fmt(p.brkPct / 100, 4));
    }
    return s;
}

function tailText() {
  let s = "";
  // shared zero-steer controller
  s += openLoopBlock("OL_STEER", "CONSTANT", 0);

  // gear/clutch boilerplate (from stock writeGearClutchControllerBlock)
  s += sectionHeader("%GEAR_CLUTCH_CONTROL");
  s += "$Used in case of models with IC Engine \n";
  s += "[GEAR_CLUTCH_CONTROL] \n";
  s += "TAG = 'ENGINE_SPEED'  \n";
  s += "(GEAR_SHIFT_MAP)      \n";
  s += "{G   US      DS      CT      CRT     TFD     TFT     CFT     TRD     TRT}    \n";
  for (let g = 1; g <= 5; g++) {
    s += ` ${g}   650     125     0.45    0.05    0.1     0.1     0.05    0.05    0.05   \n`;
  }
  return s;
}

function generateSegments() {
  const segs = [{ phase: null, text: generateHeaderText() }];
  sc.phases.forEach((p, i) => segs.push({ phase: i, text: phaseBlockText(p, i) }));
  segs.push({ phase: null, text: tailText() });
  return segs;
}

/* ---------------- ADF pane rendering + phase locate ---------------- */

function escHtml(t) {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderADF() {
  const segs = generateSegments();
  adfText = segs.map(sg => sg.text).join("");
  $("#adfOut").innerHTML = segs.map(sg => {
    const txt = escHtml(sg.text.replace(/\n$/, ""));
    return sg.phase === null ? txt : `<span class="adf-seg" data-phase="${sg.phase}">${txt}</span>`;
  }).join("");
}

function locatePhase(i) {
  $$("#adfOut .adf-seg").forEach(el => el.classList.remove("hl"));
  const seg = $(`#adfOut .adf-seg[data-phase="${i}"]`);
  if (!seg) return;
  void seg.offsetWidth; // restart the flash animation
  seg.classList.add("hl");
  // instant jump (smooth scrolling stalls in background tabs); the flash shows where we landed
  $("#adfOut").scrollTop = Math.max(0, seg.offsetTop - 10);
}

/* ---------------- persistence + actions ---------------- */

function loadStored() {
  try {
    const raw = localStorage.getItem("scenarioBuilder.current");
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj || !Array.isArray(obj.phases) || !obj.phases.length) return null;
    return obj;
  } catch { return null; }
}

function store() {
  try { localStorage.setItem("scenarioBuilder.current", JSON.stringify(sc)); } catch {}
}

function download(filename, text, mime = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function safeName() {
  return (sc.name || "scenario").replace(/[^\w\-]+/g, "_");
}

/* ---------------- refresh loop ---------------- */

function refresh(rebuildCards) {
  readScenarioInputs();
  if (rebuildCards) renderPhases();
  updateHmaxUI();
  const sim = simulate();
  drawPlots(sim);
  renderADF();
  store();
}

/* ---------------- solver time-step slider ----------------
   Logarithmic: slider 0..100 maps to h_max 0.01..0.1 s. 10 ms is the
   finest step these runs ever need (left end); slide right for coarser
   and faster. The readout estimates wall-clock solve time from this
   model's measured speed (~14 s of solving per simulated second at
   h_max = 0.001 s, scaling inversely with step size). */

const SOLVE_SPEED_AT_1MS = 14;   // wall seconds per sim second, measured

function updateHmaxUI() {
  const slider = $("#scHmaxSlider");
  if (!slider) return;
  const h = sc.hmax || 0.01;
  slider.value = Math.max(0, Math.min(100,
    Math.round(100 * (Math.log10(h) + 2))));
  const capsTotal = sc.phases.reduce((s, p) =>
    s + (p.exitType === "duration" ? num(p.exitValue, 0) : num(p.maxTime, 0)), 0);
  const wall = capsTotal * SOLVE_SPEED_AT_1MS * (0.001 / h);
  const est = !capsTotal ? "" :
    " · est. solve ≈ " + (wall >= 90 ? (wall / 60).toFixed(1) + " min"
                                     : Math.round(wall) + " s");
  $("#hmaxReadout").textContent = "h_max " + h + " s" + est;
}

$("#scHmaxSlider").addEventListener("input", () => {
  const v = +$("#scHmaxSlider").value;
  const h = Number(Math.pow(10, -2 + v / 100).toPrecision(2));
  $("#scHmax").value = h;
  refresh(false);
});

/* ---------------- wire up ---------------- */

$("#scenarioCard").addEventListener("input", () => refresh(false));

$("#btnAddPhase").onclick = () => {
  sc.phases.push({
    thrMode: "hold", thrPct: 0, thrRise: 0.3,
    brkMode: "hold", brkPct: 0, brkRise: 0.3,
    exitType: "duration", exitValue: 5, maxTime: 60,
  });
  refresh(true);
};

$("#btnExample").onclick = () => { sc = exampleScenario(); bindScenarioInputs(); refresh(true); };

$("#btnDownload").onclick = () => download(safeName() + ".adf", adfText);

$("#btnCopy").onclick = async () => {
  try { await navigator.clipboard.writeText(adfText); } catch {}
  const b = $("#btnCopy"); const old = b.textContent;
  b.textContent = "Copied!"; setTimeout(() => (b.textContent = old), 1200);
};

$("#btnSaveJson").onclick = () => download(safeName() + ".scenario.json", JSON.stringify(sc, null, 2), "application/json");

$("#btnLoadJson").onclick = () => $("#fileJson").click();
$("#fileJson").addEventListener("change", e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const obj = JSON.parse(reader.result);
      if (obj && Array.isArray(obj.phases) && obj.phases.length) {
        sc = obj; bindScenarioInputs(); refresh(true);
      } else { alert("Not a valid scenario file."); }
    } catch { alert("Could not parse that file."); }
  };
  reader.readAsText(file);
  e.target.value = "";
});

window.addEventListener("resize", () => refresh(false));

/* ---------------- preset maneuvers ----------------
   The tip-in / coast / tip-in family at a chosen pedal level:
     1. 0 -> 50 kph, step accelerator to X%
     2. release, coast down to 20 kph
     3. at 20 kph, step back to X% and hold 5 s                     */

const PRESET_PCTS = [10, 20, 30, 40, 50, 60, 70, 100];

function presetTip(pct) {
  return {
    name: `TipInOut_${pct}pct_50_20`,
    startSpeedKph: 0,
    engineInit: 300,
    hmax: 0.01,
    printInterval: 0.01,
    smoothingHz: 10,
    preview: JSON.parse(JSON.stringify(sc.preview)),   // keep preview car
    phases: [
      { thrMode: "step", thrPct: pct, thrRise: 0.3,
        brkMode: "hold", brkPct: 0, brkRise: 0.3,
        exitType: "speed_above", exitValue: 50, maxTime: 90 },
      { thrMode: "step", thrPct: 0, thrRise: 0.3,
        brkMode: "hold", brkPct: 0, brkRise: 0.3,
        exitType: "speed_below", exitValue: 20, maxTime: 90 },
      { thrMode: "step", thrPct: pct, thrRise: 0.3,
        brkMode: "hold", brkPct: 0, brkRise: 0.3,
        exitType: "duration", exitValue: 5, maxTime: 60 },
    ],
  };
}

PRESET_PCTS.forEach(pct => {
  const b = document.createElement("button");
  b.className = "preset-chip";
  b.innerHTML = `<b>${pct}%</b><span>pedal</span>`;
  b.title = `0→50 kph at ${pct}% pedal, coast to 20 kph, ${pct}% for 5 s`;
  b.onclick = () => {
    if (!confirm(`Replace the current scenario with the ${pct}% pedal ` +
                 "tip-in preset?")) return;
    sc = presetTip(pct);
    bindScenarioInputs();
    refresh(true);
  };
  $("#presetChips").appendChild(b);
});

/* ---------------- MotionSolve pipeline bridge ----------------
   Only active when the page is hosted by the pipeline app (pywebview).
   In a plain browser window.pywebview never appears and the RUN button
   and run panel stay hidden - the builder works exactly as before.    */

window.msPipe = {
  log(line) {
    const p = $("#runLog");
    p.textContent += line + "\n";
    p.scrollTop = p.scrollHeight;
  },
  status(s) { $("#runStatus").textContent = s; },
  progress(frac, text) {
    const bar = $("#runBar");
    if (frac === null) {                 // indeterminate phase
      bar.classList.add("pulse");
      bar.style.width = "100%";
    } else {
      bar.classList.remove("pulse");
      bar.style.width = (frac * 100).toFixed(1) + "%";
    }
    $("#runPhase").textContent = text || "";
  },
  done(ok, mf4, runDir) {
    if ($("#runStatus").textContent !== "stopped") {
      $("#runStatus").textContent = ok ? "done — viewer opened" : "FAILED (see log)";
    }
    const bar = $("#runBar");
    bar.classList.remove("pulse");
    bar.style.width = ok ? "100%" : bar.style.width;
    bar.classList.toggle("failed", !ok);
    $("#btnRun").disabled = false;
    $("#btnRunCycle").disabled = false;
    $("#btnStop").classList.add("hidden");
    $("#btnRunFolder").classList.remove("hidden");
    if (ok) $("#btnRunViewer").classList.remove("hidden");
  },
};

/* shared run-panel preparation for single runs and the AVL cycle batch */
function openRunPanel(statusText) {
  $("#runCard").classList.remove("hidden");
  $("#btnRunFolder").classList.add("hidden");
  $("#btnRunViewer").classList.add("hidden");
  $("#btnStop").classList.remove("hidden");
  $("#runLog").textContent = "";
  $("#runStatus").textContent = statusText;
  $("#runPhase").textContent = "";
  const bar = $("#runBar");
  bar.classList.remove("failed");
  bar.style.width = "0%";
  const vi = typeof vehInfo === "function" ? vehInfo() : {};
  const rv = $("#runVehName");
  rv.textContent = "🚗 " + (vi.name || "unnamed vehicle") +
    (vi.serial ? " · " + vi.serial : "");
  rv.classList.remove("hidden");
  $("#btnRun").disabled = true;
  $("#btnRunCycle").disabled = true;
  $("#runCard").scrollIntoView({ behavior: "smooth" });
}

/* RUN AVL CYCLE: every preset pedal level, back-to-back, at the presets'
   h_max of 0.01 s (10 ms). One run folder + MF4 per level. */
$("#btnRunCycle").onclick = async () => {
  const runs = PRESET_PCTS.map(pct => {
    const saved = sc;
    sc = presetTip(pct);                       // ADF generator reads global sc
    const adf = generateSegments().map(sg => sg.text).join("");
    sc = saved;
    return { name: `TipInOut_${pct}pct_50_20`, adf };
  });
  if (!confirm(
      `RUN AVL CYCLE — ${runs.length} MotionSolve runs, back to back:\n` +
      `pedal levels ${PRESET_PCTS.join(", ")} %\n\n` +
      `Each run gets its own folder and MF4 (h_max 0.01 s / 10 ms).\n` +
      `These start from standstill, so expect this to take a while;\n` +
      `STOP aborts the remaining runs. Continue?`)) return;
  openRunPanel("starting AVL cycle…");
  const res = await pywebview.api.run_batch(runs,
    window.vehiclePayload ? vehiclePayload() : null);
  if (!res.ok) {
    msPipe.log("ERROR: " + res.error);
    msPipe.done(false, null, null);
  }
};

/* EPA drive cycles (closed-loop demand-curve scenarios) */
function runDriveCycle(name, blurb) {
  return async () => {
    if (!confirm(`Run the ${name} drive cycle?\n\n${blurb}\n\nThe vehicle ` +
                 `from Vehicle Builder is used; results land in the runs ` +
                 `folder as ${name}_<timestamp> with its own MF4.`)) return;
    openRunPanel(`starting ${name}…`);
    const res = await pywebview.api.run_cycle(name,
      window.vehiclePayload ? vehiclePayload() : null);
    if (!res.ok) {
      msPipe.log("ERROR: " + res.error);
      msPipe.done(false, null, null);
    }
  };
}
/* ---------------- real-drive import (logged MF4 -> scenario) ------------ */

let impPath = null;

function impFillSelects(channels) {
  const opts = channels.map(c =>
    `<option value="${escHtml(c.name)}">${escHtml(c.name)}` +
    `${c.unit ? " [" + escHtml(c.unit) + "]" : ""}</option>`).join("");
  for (const id of ["impSpeedCh", "impYawCh", "impSteerCh", "impLatCh", "impLonCh"]) {
    $("#" + id).innerHTML = opts;
  }
  // best-guess defaults by name
  const pick = (id, re) => {
    const hit = channels.find(c => re.test(c.name));
    if (hit) $("#" + id).value = hit.name;
  };
  pick("impSpeedCh", /speed|veloc|vx/i);
  pick("impYawCh", /yaw/i);
  pick("impSteerCh", /steer/i);
  pick("impLatCh", /lat(itude)?$/i);
  pick("impLonCh", /lon(gitude)?$|lng/i);
}

function impLateralRows() {
  const mode = $("#impLateral").value;
  $("#impYawRow").style.display = mode === "yaw" ? "" : "none";
  $("#impSteerRow").style.display = mode === "steer" ? "" : "none";
  $("#impGpsRow").style.display = mode === "gps" ? "" : "none";
}
$("#impLateral").addEventListener("change", impLateralRows);

$("#btnImpPick").onclick = async () => {
  const r = await pywebview.api.import_drive_pick();
  if (!r.ok) { if (r.error) alert(r.error); return; }
  impPath = r.path;
  $("#impFile").textContent = r.path.split(/[\\/]/).pop() +
    "  (" + r.channels.length + " channels)";
  impFillSelects(r.channels);
  impLateralRows();
  $("#impBody").classList.remove("hidden");
  $("#btnImpRun").classList.add("hidden");
  $("#impStats").textContent = "";
};

$("#btnImpBuild").onclick = async () => {
  if (!impPath) return;
  readVehicleInputs && readVehicleInputs();
  const cfg = {
    path: impPath,
    name: $("#impName").value,
    speed_ch: $("#impSpeedCh").value,
    speed_unit: $("#impSpeedUnit").value,
    lateral: $("#impLateral").value,
    yaw_ch: $("#impYawCh").value, yaw_unit: $("#impYawUnit").value,
    steer_ch: $("#impSteerCh").value, steer_unit: $("#impSteerUnit").value,
    lat_ch: $("#impLatCh").value, lon_ch: $("#impLonCh").value,
    t_start: $("#impT0").value || null,
    t_end: $("#impT1").value || null,
  };
  if (typeof vehInfo === "function") {
    cfg.steer_ratio = veh.steerRatio;
    cfg.wheelbase_mm = veh.wheelbaseMm;
  }
  $("#impStats").textContent = "extracting…";
  const r = await pywebview.api.import_drive_build(cfg);
  if (!r.ok) { $("#impStats").textContent = "ERROR: " + r.error; return; }
  const s = r.stats;
  let txt = `${s.duration_s} s · ${s.dist_km} km · Vmax ${s.v_max_kph} km/h` +
    ` · starts at ${s.v_start_kph} km/h · ${s.n_samples} samples` +
    ` · lateral: ${s.lateral}`;
  if (s.path_len_km !== undefined) {
    txt += ` · path ${s.path_len_km} km`;
    if (s.path_vs_odo_pct !== undefined) {
      txt += ` (${s.path_vs_odo_pct}% of odometer` +
        (Math.abs(s.path_vs_odo_pct - 100) > 5 ? " ⚠ check channels/units" : " ✓") + ")";
    }
  }
  if (s.v_start_kph < 3) {
    txt += "  ⚠ starts near standstill — will solve slowly at first";
  }
  $("#impStats").textContent = txt;
  $("#btnImpRun").classList.remove("hidden");
};

$("#btnImpRun").onclick = async () => {
  openRunPanel("starting imported drive…");
  const res = await pywebview.api.run_imported(
    window.vehiclePayload ? vehiclePayload() : null);
  if (!res.ok) {
    msPipe.log("ERROR: " + res.error);
    msPipe.done(false, null, null);
  }
};

$("#btnUdds").onclick = runDriveCycle("UDDS",
  "EPA city cycle: 1369 s, ~17 stops. Every stop is a standstill dwell — " +
  "this is the LONG one (plan for hours).");
$("#btnHwfet").onclick = runDriveCycle("HWFET",
  "EPA highway cycle: 765 s, no stops after the initial launch — " +
  "solves far faster than UDDS.");

function applyState(state) {
  $("#runVoltage").value = state.settings.pack_voltage;

  const deckEl = $("#setupDeck");
  deckEl.textContent = state.settings.deck;
  deckEl.classList.toggle("missing", !state.deck_ok);

  const info = state.deck_info || {};
  let lines = [];
  if (!state.deck_ok) {
    lines.push("⚠ deck file not found — pick the solver .xml exported from MotionView");
  } else {
    lines.push("exported " + (info.modified || "?") +
      (info.nam_ok ? "  ·  .nam ✓" : "  ·  ⚠ .nam MISSING (PLT→MF4 will fail)"));
    if ((info.fmus || []).length)
      lines.push("FMUs: " + info.fmus.join(", "));
    if ((info.mats || []).length)
      lines.push("Motor/VCU parameters: " + info.mats.join(", "));
    if ((info.tires || []).length)
      lines.push("Tire: " + info.tires.join(", "));
  }
  $("#setupDeckInfo").innerHTML = lines.map(escHtml).join("<br>");

  $("#setupRuns").textContent = state.settings.runs_dir;
  const msEl = $("#setupMS");
  msEl.textContent = state.settings.motionsolve;
  msEl.classList.toggle("missing", !state.motionsolve_ok);
}

window.addEventListener("pywebviewready", async () => {
  $("#btnRun").classList.remove("hidden");
  $("#btnRunCycle").classList.remove("hidden");
  $("#driveCycleRow").classList.remove("hidden");
  $("#importCard").classList.remove("hidden");
  $("#btnOpenViewer").classList.remove("hidden");
  $("#btnOpenPlt").classList.remove("hidden");
  $("#toolsSep").classList.remove("hidden");
  $("#setupCard").classList.remove("hidden");
  try {
    const state = await pywebview.api.get_state();
    applyState(state);
    if (window.renderOverrides) renderOverrides(state);   // vehicle tab ⚡ section
  } catch { /* state fetch is cosmetic */ }
});

$("#btnPickDeck").onclick = async () => applyState(await pywebview.api.pick_deck());
$("#btnPickRuns").onclick = async () => applyState(await pywebview.api.pick_runs_dir());
$("#btnOpenRuns").onclick = () => pywebview.api.open_runs_root();

$("#btnRun").onclick = async () => {
  openRunPanel("starting…");
  const res = await pywebview.api.run_scenario(sc.name || safeName(), adfText,
    window.vehiclePayload ? vehiclePayload() : null);
  if (!res.ok) {
    msPipe.log("ERROR: " + res.error);
    msPipe.done(false, null, null);
  }
};

$("#btnStop").onclick = async () => {
  $("#runStatus").textContent = "stopped";
  $("#btnStop").disabled = true;
  await pywebview.api.stop_run();
  $("#btnStop").disabled = false;
  $("#btnStop").classList.add("hidden");
};

$("#btnOpenViewer").onclick = () => pywebview.api.open_viewer_app();
$("#btnOpenPlt").onclick = () => pywebview.api.open_plt_converter();

$("#runVoltage") && $("#runVoltage").addEventListener("change", () => {
  if (window.pywebview) pywebview.api.set_voltage($("#runVoltage").value);
});
$("#btnRunFolder").onclick = () => pywebview.api.open_run_folder();
$("#btnRunViewer").onclick = () => pywebview.api.open_in_viewer();

/* ---------------- init ---------------- */
bindScenarioInputs();
renderPhases();
refresh(false);
