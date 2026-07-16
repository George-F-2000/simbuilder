/* ============================================================================
   motorbuilder.js — the Motor Builder tab of SimBuilder.

   Shape an efficiency island with sliders, watch the live heatmap, then pin
   the map to a motor. The map is stored NORMALIZED (fractions of the
   motor's max rpm and peak torque) on veh.motors[i].effMapInline, so one
   shape fits any motor; motor_gen.py scales it onto the physical grid when
   it generates the run's .mat files.

   Precedence in generation: MotorBuilder map > uploaded file > synthetic.

   Depends on app.js ($, $$, download, escHtml) and vehicle.js (veh,
   vehRefresh). Loaded last.
   ========================================================================== */

const MB_NS = 15, MB_NT = 14;   // the model's native efficiency grid

let mb = {
  peakEff: 96.5,   // %
  spd0: 55,        // % of max rpm
  trq0: 45,        // % of peak torque
  spdF: 60,        // falloff widths (bigger = wider island)
  trqF: 60,
};

try {
  const raw = localStorage.getItem("simbuilder.motorbuilder.v1");
  if (raw) mb = Object.assign(mb, JSON.parse(raw));
} catch {}

const MB_SLIDERS = [
  ["mbPeak", "peakEff", v => v.toFixed(1) + " %"],
  ["mbSpd0", "spd0", v => v + " %"],
  ["mbTrq0", "trq0", v => v + " %"],
  ["mbSpdF", "spdF", v => v + ""],
  ["mbTrqF", "trqF", v => v + ""],
];

/* ---------------- the map ---------------- */

function mbGrid() {
  const spd = [...Array(MB_NS).keys()].map(i => i / (MB_NS - 1));
  const trq = [...Array(MB_NT).keys()].map(j => j / (MB_NT - 1));
  const peak = mb.peakEff / 100;
  const s0 = mb.spd0 / 100, t0 = mb.trq0 / 100;
  const sf = mb.spdF / 100, tf = mb.trqF / 100;
  const eff = spd.map((s, i) => trq.map(t => {
    if (i === 0) return 0;   // zero speed -> zero efficiency (model convention)
    const d = ((s - s0) / sf) ** 2 + ((t - t0) / tf) ** 2;
    return Math.max(0.5, Math.min(peak, peak - 0.35 * d));
  }));
  return { spd_frac: spd, trq_frac: trq, eff };
}

/* ---------------- heatmap ---------------- */

function effColor(e) {
  if (e <= 0) return "#1a2430";
  // 0.5 (blue) -> peak (warm yellow)
  const f = Math.max(0, Math.min(1, (e - 0.5) / 0.485));
  const h = 220 - 175 * f;          // 220 blue -> 45 yellow
  const l = 30 + 28 * f;
  return `hsl(${h} 75% ${l}%)`;
}

function mbDraw(grid) {
  const canvas = $("#mbCanvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const mL = 58, mB = 44, mT = 8, mR = 10;   // margins for axes
  const cw = (W - mL - mR) / MB_NS, ch = (H - mT - mB) / MB_NT;
  ctx.clearRect(0, 0, W, H);

  for (let i = 0; i < MB_NS; i++) {
    for (let j = 0; j < MB_NT; j++) {
      const e = grid.eff[i][j];
      const x = mL + i * cw;
      const y = H - mB - (j + 1) * ch;   // torque grows upward
      ctx.fillStyle = effColor(e);
      ctx.fillRect(x, y, cw + 0.5, ch + 0.5);
      if (e > 0) {
        ctx.fillStyle = e > 0.8 ? "#00000090" : "#ffffff90";
        ctx.font = "9px Consolas, monospace";
        ctx.textAlign = "center";
        ctx.fillText(Math.round(e * 100), x + cw / 2, y + ch / 2 + 3);
      }
    }
  }

  ctx.fillStyle = "#5a6572";
  ctx.font = "12px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("motor speed  (% of max rpm)  →", mL + (W - mL - mR) / 2, H - 12);
  ctx.save();
  ctx.translate(16, mT + (H - mT - mB) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("torque  (% of peak)  →", 0, 0);
  ctx.restore();
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("0", mL, H - mB + 12);
  ctx.textAlign = "right";
  ctx.fillText("100", W - mR, H - mB + 12);
  ctx.textAlign = "right";
  ctx.fillText("100", mL - 4, mT + 10);
  ctx.fillText("0", mL - 4, H - mB);
}

/* ---------------- refresh ---------------- */

function mbRefresh() {
  for (const [id, prop, fmtv] of MB_SLIDERS) {
    $("#" + id).value = mb[prop];
    $("#" + id + "Val").textContent = fmtv(mb[prop]);
  }
  mbDraw(mbGrid());
  try {
    localStorage.setItem("simbuilder.motorbuilder.v1", JSON.stringify(mb));
  } catch {}
}
window.mbRefresh = mbRefresh;

MB_SLIDERS.forEach(([id, prop]) => {
  $("#" + id).addEventListener("input", () => {
    mb[prop] = parseFloat($("#" + id).value);
    mbRefresh();
  });
});

/* ---------------- hover readout ---------------- */

$("#mbCanvas").addEventListener("mousemove", e => {
  const canvas = $("#mbCanvas");
  const r = canvas.getBoundingClientRect();
  const W = canvas.width, H = canvas.height;
  const mL = 58, mB = 44, mT = 8, mR = 10;
  const x = (e.clientX - r.left) * (W / r.width);
  const y = (e.clientY - r.top) * (H / r.height);
  const i = Math.floor((x - mL) / ((W - mL - mR) / MB_NS));
  const j = Math.floor((H - mB - y) / ((H - mT - mB) / MB_NT));
  if (i >= 0 && i < MB_NS && j >= 0 && j < MB_NT) {
    const g = mbGrid();
    $("#mbHover").textContent =
      Math.round(g.spd_frac[i] * 100) + "% rpm, " +
      Math.round(g.trq_frac[j] * 100) + "% torque → η " +
      (g.eff[i][j] * 100).toFixed(1) + " %";
  }
});

/* ---------------- apply / export ---------------- */

function mbApply(idx) {
  if (!veh.motors[idx]) {
    $("#mbStatus").textContent = "That motor doesn't exist (check motor count).";
    return;
  }
  veh.motors[idx].effMapInline = mbGrid();
  veh.motors[idx].effMapPath = "";
  vehRefresh(true);   // update the motor card's map label
  $("#mbStatus").textContent =
    "Map pinned to " + (veh.motors[idx].name || "motor " + (idx + 1)) +
    " — every run now uses it. (Reset from its Vehicle Builder card.)";
}

function mbCsv(idx) {
  const m = veh.motors[idx];
  if (!m) return;
  const g = mbGrid();
  const torques = g.trq_frac.map(f => (f * m.torqueNm).toFixed(2));
  const rows = [["speed_rpm\\torque_Nm", ...torques].join(",")];
  g.spd_frac.forEach((f, i) => {
    rows.push([(f * m.maxRpm).toFixed(1),
               ...g.eff[i].map(e => e.toFixed(4))].join(","));
  });
  download((m.name || "motor").replace(/[^\w\-]+/g, "_") + "_eff_map.csv",
           rows.join("\n"), "text/csv");
}

$("#mbApply1").onclick = () => mbApply(0);
$("#mbApply2").onclick = () => mbApply(1);
$("#mbCsv1").onclick = () => mbCsv(0);
$("#mbCsv2").onclick = () => mbCsv(1);

/* ---------------- init ---------------- */
mbRefresh();
