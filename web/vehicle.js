/* ============================================================================
   vehicle.js — the Vehicle Builder tab of SimBuilder.

   Two kinds of fields, honestly labelled:
     ⚡ affects the simulation — injected into every run by the pipeline app:
        tire .tir override, motor/VCU .mat parameter overrides, pack voltage.
     📋 spec sheet — recorded (vehicle.json in each run folder, and in the
        browser's storage) and used for the fun derived stats + the scenario
        preview model, but the multibody model itself comes from the
        MotionView-exported deck.

   Depends on helpers from app.js: $, $$ (if present), download(), escHtml().
   ========================================================================== */

const SUSPENSIONS = [
  "McPherson strut", "Double wishbone", "Multi-link (5-link)",
  "Multi-link (4-link)", "Trailing arm", "Twist beam", "Solid axle (link)",
  "Solid axle (leaf)", "Pushrod (race)",
];

function defaultVehicle() {
  return {
    name: "My EV",
    motorCount: 2,
    motors: [
      { name: "Front PMSM", powerKW: 92, torqueNm: 210, maxRpm: 15000,
        ratedVoltageV: 380, ratedCurrentA: 400, gearRatio: 3.7, effMapPath: "" },
      { name: "Rear PMSM", powerKW: 65, torqueNm: 380, maxRpm: 15000,
        ratedVoltageV: 380, ratedCurrentA: 400, gearRatio: 3.7, effMapPath: "" },
    ],
    generateMotors: true,
    applyMass: false,
    ems: { enabled: false, strategy: "loss_optimal", threshold: 250 },
    packVoltage: 380, packKWh: 100,
    massKg: 2230, cd: 0.28, frontalM2: 2.6,
    wheelbaseMm: 3094, trackFMm: 1680, trackRMm: 1680,
    suspF: "McPherson strut", suspR: "Multi-link (5-link)",
    steerRatio: 15.8,
    rimIn: 15, tireSpec: "205/60R15",
    tirePath: "",          // ⚡ .tir override (empty = deck default)
    matOverrides: {},      // ⚡ {original .mat basename: replacement path}
    notes: "",
  };
}

let veh = defaultVehicle();

/* ---------------- persistence ---------------- */

function vehStore() {
  try { localStorage.setItem("simbuilder.vehicle.v1", JSON.stringify(veh)); }
  catch {}
}

function vehLoadStored() {
  try {
    const raw = localStorage.getItem("simbuilder.vehicle.v1");
    if (raw) {
      const obj = JSON.parse(raw);
      if (obj && obj.motors) veh = Object.assign(defaultVehicle(), obj);
    }
  } catch {}
  // backfill fields added after a vehicle was stored (shallow merge misses
  // nested motor objects)
  (veh.motors || []).forEach(m => { if (m.effMapPath === undefined) m.effMapPath = ""; });
  if (veh.generateMotors === undefined) veh.generateMotors = true;
  if (veh.applyMass === undefined) veh.applyMass = false;
  if (!veh.ems) veh.ems = { enabled: false, strategy: "loss_optimal", threshold: 250 };
  // migration: gear ratio became ⚡ real in v2. Vehicles stored before that
  // carry the old placeholder default (10.5) which never matched the deck
  // (3.7) - patching it in silently would change the car. Reset those.
  if (!veh._v) {
    (veh.motors || []).forEach(m => { if (m.gearRatio === 10.5) m.gearRatio = 3.7; });
    veh._v = 2;
  }
}

/* ---------------- field binding ---------------- */

// [element id, veh property, numeric?]
const VEH_FIELDS = [
  ["vhName", "name", false],
  ["vhMass", "massKg", true], ["vhCd", "cd", true], ["vhArea", "frontalM2", true],
  ["vhWheelbase", "wheelbaseMm", true],
  ["vhTrackF", "trackFMm", true], ["vhTrackR", "trackRMm", true],
  ["vhSteer", "steerRatio", true],
  ["vhPackV", "packVoltage", true], ["vhPackKWh", "packKWh", true],
  ["vhRim", "rimIn", true], ["vhTire", "tireSpec", false],
  ["vhNotes", "notes", false],
];

const MOTOR_FIELDS = [
  ["name", false], ["powerKW", true], ["torqueNm", true], ["maxRpm", true],
  ["ratedVoltageV", true], ["ratedCurrentA", true], ["gearRatio", true],
];

function bindVehicleInputs() {
  $("#vhSuspF").innerHTML = SUSPENSIONS.map(s => `<option>${s}</option>`).join("");
  $("#vhSuspR").innerHTML = SUSPENSIONS.map(s => `<option>${s}</option>`).join("");
  $("#vhSuspF").value = veh.suspF;
  $("#vhSuspR").value = veh.suspR;
  $("#vhMotorCount").value = String(veh.motorCount);
  $("#vhGenMotors").checked = !!veh.generateMotors;
  $("#vhApplyMass").checked = !!veh.applyMass;
  $("#vhEmsEnable").checked = !!veh.ems.enabled;
  $("#vhEmsStrategy").value = veh.ems.strategy;
  $("#vhEmsThreshold").value = veh.ems.threshold;
  for (const [id, prop] of VEH_FIELDS) $("#" + id).value = veh[prop];
  renderMotorCards();
  renderEms();
}

const EMS_DESC = {
  loss_optimal: "At every operating point, picks the front/rear split that " +
    "minimises combined electrical loss from both motors' efficiency maps — " +
    "the physics-optimal answer (single motor when light, sharing when heavy).",
  rule: "Runs one motor until demand passes the threshold, then ramps toward " +
    "an even split — a classic production rule-based VCU.",
  fuzzy: "Fuzzy-logic blend of demand and speed memberships — smooth " +
    "transitions between single-motor and shared operation.",
  even: "Always 50/50 between the axles — naive baseline for comparison.",
  single_motor: "Always one axle — the other motor idles. Baseline / limp mode.",
};

// Fuller "textbook page" per strategy: plain-English, the engineering, and
// the trade-off. Written to be clear to an ME and to a total layperson.
const EMS_LEARN = {
  loss_optimal: `
    <h4>In plain English</h4>
    <p>Every electric motor has a "sweet spot" — a load where it turns the
    most battery energy into actual push and wastes the least as heat (like a
    car engine that sips fuel cruising at 2000 rpm but guzzles when you lug it
    or scream it). This strategy asks, every instant: <i>for the exact torque
    the driver wants right now, which way of dividing it between the front and
    rear motor wastes the least electricity?</i> — and does that.</p>
    <p>The surprising result: when you're driving gently, it's better to use
    <b>one</b> motor working comfortably than <b>both</b> motors loafing in
    their inefficient low-load corners. When you demand a lot, one motor alone
    would be strained past its good zone, so it splits the work to keep both
    near their sweet spots.</p>
    <h4>The engineering</h4>
    <p>At each operating point (motor speed ω, total torque demand T) it
    searches candidate splits and minimises combined electrical loss
    <code>Σ τ&#8339;·ω·(1/η&#8339;(ω,τ&#8339;) − 1)</code>, using each motor's
    real efficiency map η, subject to the torque envelopes. "Instantaneous"
    means it decides moment-by-moment with no memory. This is the ECMS /
    static-optimal answer; for a single drive cycle with no battery-SOC
    constraint it is also the globally optimal one.</p>
    <h4>Trade-off</h4>
    <p>Best efficiency — but it can "chatter" (flick a motor on and off around
    the switch-over), which hurts smoothness and NVH. That efficiency-vs-
    drivability tension is exactly what your MF4 → drivability pipeline is
    there to measure.</p>`,

  rule: `
    <h4>In plain English</h4>
    <p>A simple foreman with one rule: <i>"you handle it alone until the load
    gets big, then call your buddy in."</i> Below a torque you set, one motor
    does everything; above it, the second motor joins and takes a bigger share
    the harder you push.</p>
    <h4>The engineering</h4>
    <p>Split ratio r = 0 below the threshold, then ramps linearly toward a
    target share as demand climbs to maximum. Deterministic, cheap to compute,
    trivial to calibrate and certify — which is why real production vehicle
    controllers often use exactly this. It has no knowledge of the efficiency
    maps, so it's a sensible <i>approximation</i> of the optimal split, not the
    optimum itself.</p>
    <h4>Trade-off</h4>
    <p>Simple, predictable, robust. Leaves some efficiency on the table versus
    loss-optimal, and the threshold is a knob you have to tune for the car.</p>`,

  fuzzy: `
    <h4>In plain English</h4>
    <p>Real decisions aren't crisp — "exactly 250 N·m and not a newton less =
    switch" is a bit silly. Fuzzy logic replaces the hard line with a dimmer
    switch driven by soft words: <i>"if demand is HIGH and speed is MEDIUM,
    share a lot."</i> The split changes <b>smoothly</b> instead of snapping,
    which simply feels better to drive.</p>
    <h4>The engineering</h4>
    <p>Each input (demand, speed) is scored for how much it belongs to fuzzy
    sets like low / medium / high (membership 0–1). A small rule base fires
    those memberships, and the weighted result is "defuzzified" into a single
    split fraction. You tune behaviour by reshaping the membership curves and
    editing rules — it captures engineering intuition without needing an exact
    model.</p>
    <h4>Trade-off</h4>
    <p>Smoother than hard rule-based (better drivability), still a heuristic
    (not provably optimal), and it gives you more knobs to turn.</p>`,

  even: `
    <h4>In plain English</h4>
    <p>Always split the work 50/50, no thinking. Both motors do equal duty all
    the time. It's the simplest thing you could possibly do — and that's the
    point: it's the <b>baseline</b> you measure the clever strategies against.</p>
    <h4>The engineering</h4>
    <p>Split ratio r = 0.5 everywhere. A reference case: any strategy worth its
    added complexity has to beat this on efficiency and/or drivability, or why
    bother.</p>
    <h4>Trade-off</h4>
    <p>Dead simple and wears both motors evenly. Usually inefficient at light
    load, because it forces both motors to idle in their poor low-load
    corners.</p>`,

  single_motor: `
    <h4>In plain English</h4>
    <p>Only ever use one motor; the other just coasts. Like flying a
    twin-engine plane on a single engine — fine when you're asking for modest
    power, but it runs out of muscle the moment you floor it, because help
    never arrives.</p>
    <h4>The engineering</h4>
    <p>Split ratio r = 0 everywhere; the secondary motor idles. Efficient at
    light load, but it <b>saturates</b> at high demand — peak torque simply
    can't be delivered because the second axle never contributes. Handy as a
    lower-bound baseline, for isolating single-axle behaviour, or as a
    limp-home mode.</p>
    <h4>Trade-off</h4>
    <p>Efficient when light, but capacity-limited. Never the answer for a
    performance run; very useful as a control case.</p>`,
};

function renderEms() {
  const on = $("#vhEmsEnable").checked;
  const strat = $("#vhEmsStrategy").value;
  $("#emsBody").style.opacity = on ? "1" : "0.5";
  $("#vhEmsStrategy").disabled = !on;
  $("#vhEmsThreshold").disabled = !on;
  $("#emsThresholdWrap").style.display = strat === "rule" ? "" : "none";
  $("#emsDesc").textContent = EMS_DESC[strat] || "";
  $("#emsLearnBody").innerHTML = EMS_LEARN[strat] || "";
}

function readVehicleInputs() {
  veh.suspF = $("#vhSuspF").value;
  veh.suspR = $("#vhSuspR").value;
  veh.motorCount = parseInt($("#vhMotorCount").value, 10) || 1;
  veh.generateMotors = $("#vhGenMotors").checked;
  veh.applyMass = $("#vhApplyMass").checked;
  veh.ems = {
    enabled: $("#vhEmsEnable").checked,
    strategy: $("#vhEmsStrategy").value,
    threshold: parseFloat($("#vhEmsThreshold").value) || 250,
  };
  for (const [id, prop, isNum] of VEH_FIELDS) {
    const v = $("#" + id).value;
    veh[prop] = isNum ? (parseFloat(v) || 0) : v;
  }
  $$(".motor-card").forEach((card, i) => {
    if (!veh.motors[i]) veh.motors[i] = defaultVehicle().motors[0];
    for (const [prop, isNum] of MOTOR_FIELDS) {
      const el = card.querySelector(`[data-m="${prop}"]`);
      if (el) veh.motors[i][prop] = isNum ? (parseFloat(el.value) || 0) : el.value;
    }
  });
}

function renderMotorCards() {
  const wrap = $("#motorCards");
  wrap.innerHTML = "";
  const tpl = $("#motorTemplate");
  for (let i = 0; i < veh.motorCount; i++) {
    const m = veh.motors[i] || (veh.motors[i] = JSON.parse(
      JSON.stringify(defaultVehicle().motors[Math.min(i, 1)])));
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".motor-title").textContent =
      veh.motorCount === 1 ? "Motor" : (i === 0 ? "Motor 1 — front" : "Motor 2 — rear");
    for (const [prop] of MOTOR_FIELDS) {
      const el = node.querySelector(`[data-m="${prop}"]`);
      if (el) el.value = m[prop];
    }
    // efficiency map upload (⚡): native picker via the pipeline app
    const pathEl = node.querySelector(".eff-path");
    const resetBtn = node.querySelector(".reset-eff");
    const pickBtn = node.querySelector(".pick-eff");
    const showEff = () => {
      pathEl.textContent = m.effMapInline
        ? "MotorBuilder custom map"
        : (m.effMapPath || "synthetic (built from ratings)");
      resetBtn.classList.toggle("hidden", !m.effMapPath && !m.effMapInline);
    };
    showEff();
    resetBtn.onclick = () => {
      m.effMapPath = "";
      delete m.effMapInline;
      showEff();
      vehRefresh(false);
    };
    if (window.pywebview) {
      pickBtn.onclick = async () => {
        const p = await pywebview.api.pick_file(
          "Efficiency map (*.csv;*.mat)|*.csv;*.mat");
        if (p) { m.effMapPath = p; delete m.effMapInline; showEff(); vehRefresh(false); }
      };
    } else {
      pickBtn.disabled = true;
      pickBtn.title = "Available inside the SimBuilder app";
    }
    node.addEventListener("input", () => vehRefresh(false));
    wrap.appendChild(node);
  }
}

/* ---------------- derived stats (the fun part) ---------------- */

function parseTireSpec(spec) {
  // "205/60R15" -> width mm, aspect %, rim in
  const m = /^\s*(\d{3})\s*\/\s*(\d{2})\s*R\s*(\d{2})\s*$/i.exec(spec || "");
  if (!m) return null;
  const width = +m[1], aspect = +m[2], rim = +m[3];
  const diaMm = rim * 25.4 + 2 * width * aspect / 100;
  return { width, aspect, rim, diaMm, circumM: Math.PI * diaMm / 1000 };
}

function fmtStat(v, dec = 1) {
  return Number.isFinite(v) ? v.toFixed(dec) : "—";
}

/* ---------------- serial number: a fingerprint of the spec ----------------
   Deterministic FNV-1a hash of everything that defines the car (motors up
   to motorCount, gearing, mass, tire, pack, EMS, overrides - excluding
   notes and the serial itself). Any change -> new serial; identical spec ->
   identical serial. The same digits are written into the MF4 as the
   VehicleSerial channel, so a run can be matched to its exact config.   */

function stableStringify(o) {
  if (o === null || typeof o !== "object") return JSON.stringify(o);
  if (Array.isArray(o)) return "[" + o.map(stableStringify).join(",") + "]";
  return "{" + Object.keys(o).sort().map(k =>
    JSON.stringify(k) + ":" + stableStringify(o[k])).join(",") + "}";
}

function computeSerial(v) {
  const proj = Object.assign({}, v);
  delete proj.serial; delete proj.notes; delete proj._v;
  proj.motors = (v.motors || []).slice(0, v.motorCount || 1);
  const s = stableStringify(proj);
  let h = 0x811c9dc5;                      // FNV-1a 32-bit
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return "SN-" + String(h >>> 0).padStart(10, "0");
}

function vehDerived() {
  const tire = parseTireSpec(veh.tireSpec);
  const motors = veh.motors.slice(0, veh.motorCount);
  const totalKW = motors.reduce((s, m) => s + (m.powerKW || 0), 0);
  const totalNm = motors.reduce((s, m) => s + (m.torqueNm || 0), 0);
  const stats = [];

  stats.push(["Serial number", veh.serial || "—"]);
  stats.push(["Combined power", fmtStat(totalKW, 0) + " kW  (" +
    fmtStat(totalKW * 1.341, 0) + " hp)"]);
  stats.push(["Combined motor torque", fmtStat(totalNm, 0) + " N·m"]);
  stats.push(["Power-to-weight", fmtStat(veh.massKg ? totalKW * 1000 / veh.massKg : NaN, 0) + " W/kg"]);
  stats.push(["CdA", fmtStat(veh.cd * veh.frontalM2, 3) + " m²"]);

  if (tire) {
    stats.push(["Tire diameter", fmtStat(tire.diaMm, 0) + " mm  (radius " +
      fmtStat(tire.diaMm / 2000, 3) + " m)"]);
    if (tire.rim !== +veh.rimIn) {
      stats.push(["⚠ Rim mismatch", "tire spec says R" + tire.rim +
        " but rim field says " + veh.rimIn + '"']);
    }
    motors.forEach((m, i) => {
      if (m.gearRatio > 0 && m.maxRpm > 0) {
        // wheel rpm at max motor rpm -> vehicle speed
        const kph = (m.maxRpm / m.gearRatio) * tire.circumM * 60 / 1000;
        const label = veh.motorCount === 1 ? "Top speed (gearing)" :
          "Top speed (gearing, M" + (i + 1) + ")";
        stats.push([label, fmtStat(kph, 0) + " km/h @ " +
          fmtStat(m.maxRpm, 0) + " rpm / " + m.gearRatio + ":1"]);
        stats.push([(veh.motorCount === 1 ? "Wheel torque" : "Wheel torque (M" + (i + 1) + ")"),
          fmtStat(m.torqueNm * m.gearRatio, 0) + " N·m"]);
      }
    });
  } else {
    stats.push(["Tire spec", "enter like 205/60R15 to unlock tire math"]);
  }

  const wKg = veh.packKWh > 0 && veh.massKg > 0 ?
    veh.packKWh * 1000 / veh.massKg : NaN;
  stats.push(["Pack energy density (veh.)", fmtStat(wKg, 0) + " Wh/kg of car"]);
  return stats;
}

function renderDerived() {
  $("#vehStats").innerHTML = vehDerived().map(([k, v]) =>
    `<div class="stat-row"><span class="stat-k">${escHtml(k)}</span>` +
    `<span class="stat-v">${escHtml(v)}</span></div>`).join("");
}

/* ---------------- top-view car diagram ---------------- */

function renderCarSvg() {
  const svg = $("#carSvg");
  const wb = Math.max(veh.wheelbaseMm, 1500), tf = Math.max(veh.trackFMm, 800),
        tr = Math.max(veh.trackRMm, 800);
  const tire = parseTireSpec(veh.tireSpec);
  const tireLen = tire ? tire.diaMm : 650;
  const tireW = tire ? tire.width : 205;

  // fit the car into the middle of the 420x270 viewBox, leaving margins for
  // the dimension labels: ~46px each side (rotated track labels), ~44px
  // bottom (wheelbase label). Labels were previously clipped off-canvas.
  const totalL = wb + tireLen, totalW = Math.max(tf, tr) + tireW;
  const s = Math.min(310 / totalL, 180 / totalW);
  const cx = 210, cy = 105;
  const x1 = cx - (wb / 2) * s, x2 = cx + (wb / 2) * s;   // front / rear axle
  const w = (tireLen * s) / 2, h = (tireW * s) / 2;

  const wheel = (x, y) =>
    `<rect x="${x - w}" y="${y - h}" width="${2 * w}" height="${2 * h}"
       rx="${h * 0.5}" class="svg-wheel"/>`;
  const body =
    `<rect x="${x1 - w * 0.6}" y="${cy - (Math.min(tf, tr) / 2) * s * 0.72}"
       width="${(x2 - x1) + w * 1.2}" height="${Math.min(tf, tr) * s * 0.72}"
       rx="14" class="svg-body"/>`;

  const dimBottom = cy + (Math.max(tf, tr) / 2) * s + h + 14;
  const dxF = x1 - w - 14;              // front track dimension, left side
  const dxR = x2 + w + 14;              // rear track dimension, right side

  svg.innerHTML =
    body +
    wheel(x1, cy - (tf / 2) * s) + wheel(x1, cy + (tf / 2) * s) +
    wheel(x2, cy - (tr / 2) * s) + wheel(x2, cy + (tr / 2) * s) +
    // wheelbase (bottom)
    `<line x1="${x1}" y1="${dimBottom}" x2="${x2}" y2="${dimBottom}" class="svg-dim"/>` +
    `<text x="${cx}" y="${dimBottom + 14}" class="svg-label"
       text-anchor="middle">wheelbase ${veh.wheelbaseMm} mm</text>` +
    // front track (left)
    `<line x1="${dxF}" y1="${cy - (tf / 2) * s}" x2="${dxF}"
       y2="${cy + (tf / 2) * s}" class="svg-dim"/>` +
    `<text x="${dxF - 8}" y="${cy}" class="svg-label" text-anchor="middle"
       transform="rotate(-90 ${dxF - 8} ${cy})">track F ${veh.trackFMm} mm</text>` +
    // rear track (right)
    `<line x1="${dxR}" y1="${cy - (tr / 2) * s}" x2="${dxR}"
       y2="${cy + (tr / 2) * s}" class="svg-dim"/>` +
    `<text x="${dxR + 12}" y="${cy}" class="svg-label" text-anchor="middle"
       transform="rotate(90 ${dxR + 12} ${cy})">track R ${veh.trackRMm} mm</text>` +
    `<text x="${cx}" y="${cy + 4}" class="svg-name" text-anchor="middle">${escHtml(veh.name || "")}</text>`;
}

/* ---------------- ⚡ simulation overrides (pywebview only) ---------------- */

// motor parameter files are managed by generation + per-motor upload; only
// the leftovers (VCU maps etc.) appear in the advanced override list
const MOTOR_MANAGED = /char|frnt|front|rear/i;

function renderOverrides(state) {
  const tireBox = $("#tireOverride");
  const matBox = $("#matOverrides");
  if (!window.pywebview) {
    tireBox.innerHTML = '<p class="hint">Tire file override (⚡) is available ' +
      "inside the SimBuilder app.</p>";
    matBox.innerHTML = '<p class="hint">Available inside the SimBuilder app.</p>';
    return;
  }
  const info = (state && state.deck_info) || window.__lastDeckInfo || {};
  window.__lastDeckInfo = info;

  tireBox.innerHTML =
    '<div class="setup-row"><span class="setup-label">Tire file (.tir) ' +
    '<span class="badge sim">⚡ affects sim</span></span>' +
    `<code class="setup-path">${escHtml(veh.tirePath || "deck default" +
      (info.tires && info.tires.length ? " — " + info.tires.join(", ") : ""))}</code>` +
    '<button class="ghost" id="btnPickTir">Change…</button>' +
    (veh.tirePath ? '<button class="ghost" id="btnResetTir">Reset</button>' : "") +
    "</div>";

  const mats = (info.mats || []).filter(m => !MOTOR_MANAGED.test(m));
  let html = "";
  for (const m of mats) {
    const ov = veh.matOverrides[m];
    html += `<div class="setup-row"><span class="setup-label mat-label" title="${escHtml(m)}">${escHtml(m)}</span>` +
      `<code class="setup-path">${escHtml(ov || "deck default")}</code>` +
      `<button class="ghost pick-mat" data-mat="${escHtml(m)}">Replace…</button>` +
      (ov ? `<button class="ghost reset-mat" data-mat="${escHtml(m)}">Reset</button>` : "") +
      "</div>";
  }
  matBox.innerHTML = html ||
    '<p class="hint">No further parameter files in this deck.</p>';

  const pickTir = $("#btnPickTir");
  if (pickTir) pickTir.onclick = async () => {
    const p = await pywebview.api.pick_file("Tire property file (*.tir)|*.tir");
    if (p) { veh.tirePath = p; vehRefresh(false); }
  };
  const resetTir = $("#btnResetTir");
  if (resetTir) resetTir.onclick = () => { veh.tirePath = ""; vehRefresh(false); };
  $$(".pick-mat").forEach(b => b.onclick = async () => {
    const p = await pywebview.api.pick_file("MATLAB data (*.mat)|*.mat");
    if (p) { veh.matOverrides[b.dataset.mat] = p; vehRefresh(false); }
  });
  $$(".reset-mat").forEach(b => b.onclick = () => {
    delete veh.matOverrides[b.dataset.mat]; vehRefresh(false);
  });
}

function updateRunChip() {
  const chip = $("#runVehChip");
  if (!chip) return;
  chip.textContent = "🚗 runs vehicle: " + (veh.name || "unnamed") +
    " · " + (veh.serial || "") + " ⚡";
  if (window.pywebview) chip.classList.remove("hidden");
  const nameEl = $("#pmInheritName");
  if (nameEl) nameEl.textContent = veh.name || "unnamed";
}

/* preview-model parameters derived from the vehicle: mass, CdA, and
   tractive force (combined wheel torque / tire radius). The scenario tab
   inherits these when its "Inherit from Vehicle Builder" box is ticked. */
function vehPreviewParams() {
  const tire = parseTireSpec(veh.tireSpec);
  const fmax = tire
    ? veh.motors.slice(0, veh.motorCount).reduce(
        (s, m) => s + (m.torqueNm || 0) * (m.gearRatio || 0), 0) /
      (tire.diaMm / 2000)
    : null;
  return { mass: veh.massKg, cda: veh.cd * veh.frontalM2, fmax };
}
window.vehPreviewParams = vehPreviewParams;
// safe accessor for app.js (veh is a top-level let, not a window property)
window.vehInfo = () => ({ name: veh.name, serial: veh.serial });

/* payload handed to the pipeline with every run */
function vehiclePayload() {
  readVehicleInputs();
  veh.serial = computeSerial(veh);
  return {
    spec: veh,
    tire_path: veh.tirePath || null,
    mat_overrides: veh.matOverrides,
    pack_voltage: veh.packVoltage,
    generate_motors: !!veh.generateMotors,
    apply_mass: !!veh.applyMass,
    ems: {
      enabled: !!veh.ems.enabled,
      strategy: veh.ems.strategy,
      params: veh.ems.strategy === "rule" ? { threshold_nm: veh.ems.threshold } : {},
    },
  };
}
window.vehiclePayload = vehiclePayload;

/* ---------------- refresh loop ---------------- */

function vehRefresh(rebuildCards) {
  readVehicleInputs();
  veh.serial = computeSerial(veh);   // fingerprint follows every change
  if (rebuildCards) renderMotorCards();
  renderDerived();
  renderCarSvg();
  renderOverrides();
  renderEms();
  updateRunChip();
  vehStore();
  // scenario preview inherits this vehicle: keep it in step live
  if (typeof refresh === "function" && $("#pmInherit") && $("#pmInherit").checked) {
    refresh(false);
  }
}

// pywebview announces itself AFTER the initial render, so re-render the
// motor cards to enable the upload buttons and show the ⚡ override rows
window.addEventListener("pywebviewready", () => vehRefresh(true));

/* ---------------- scenario-preview handoff ---------------- */

$("#btnVehToPreview").onclick = () => {
  readVehicleInputs();
  $("#pmInherit").checked = true;   // inheritance does the rest, live
  refresh(false);
  switchTab("scenario");
  $("#pmMass").scrollIntoView({ behavior: "smooth", block: "center" });
};

/* ---------------- save / load ---------------- */

$("#btnVehSave").onclick = () => {
  readVehicleInputs();
  download((veh.name || "vehicle").replace(/[^\w\-]+/g, "_") + ".vehicle.json",
    JSON.stringify(veh, null, 2), "application/json");
};
$("#btnVehLoad").onclick = () => $("#fileVehJson").click();
$("#fileVehJson").addEventListener("change", e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const obj = JSON.parse(reader.result);
      if (obj && obj.motors) {
        veh = Object.assign(defaultVehicle(), obj);
        bindVehicleInputs(); vehRefresh(true);
      } else alert("Not a vehicle file.");
    } catch { alert("Could not parse that file."); }
  };
  reader.readAsText(file);
  e.target.value = "";
});
$("#btnVehReset").onclick = () => {
  if (confirm("Reset the vehicle to defaults?")) {
    veh = defaultVehicle(); bindVehicleInputs(); vehRefresh(true);
  }
};

/* ---------------- tabs ---------------- */

function switchTab(which) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === which));
  ["scenario", "vehicle", "motor", "results"].forEach(id => {
    const el = $("#tab-" + id);
    if (el) el.classList.toggle("hidden", id !== which);
  });
  // canvases don't draw while display:none - redraw on entry
  if (which === "scenario" && typeof refresh === "function") refresh(false);
  if (which === "motor" && typeof mbRefresh === "function") mbRefresh();
  if (which === "results" && typeof resultsOnEnter === "function") resultsOnEnter();
}
$$(".tab").forEach(t => t.onclick = () => switchTab(t.dataset.tab));
switchTab("vehicle");   // Vehicle Builder is the first stop

/* ---------------- init ---------------- */

$("#vehicleForm").addEventListener("input", () => vehRefresh(false));
$("#vhMotorCount").addEventListener("change", () => vehRefresh(true));

vehLoadStored();
bindVehicleInputs();
vehRefresh(false);
