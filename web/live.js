/* live.js — the Live telemetry tab of SimBuilder.
   The Python side (main.py Api._start_live -> live_tail.LiveTailer) tails the
   growing .plt and pushes:
       msPipe.liveReset()                      run starting, clear everything
       msPipe.liveInit(channels, picks, units) channel directory + streamed set
       msPipe.liveFrame([{t, vals:{key:v}}])   batched samples (~5 Hz)
   Channels have wildly different units (km/h vs N·m vs watts), so each visible
   channel is NORMALISED to its own running min/max for the shared plot; the
   legend shows each channel's ACTUAL current value + unit. That's the logger-
   overview feel — you watch the shapes evolve and read the live numbers. */

(function () {
  "use strict";
  const MAXPTS = 6000;                 // rolling cap per channel
  const COLORS = ["#2dc7b0", "#e0873a", "#6ea0e8", "#d05c7c", "#9b7fe0",
                  "#7cbf50", "#e0b84a", "#54b9c7", "#c76ba0", "#8a97a6"];

  const S = {
    channels: [],                      // full [{key,label,unit,col,slot}]
    streamed: [],                      // subset actually streamed (picks)
    units: "",
    t: [],                             // time axis
    series: {},                        // key -> value array (parallel to t)
    range: {},                         // key -> [min,max] seen
    visible: [],                       // keys currently plotted (ordered)
    color: {},                         // key -> color
    started: false,
  };

  function reset() {
    S.channels = []; S.streamed = []; S.t = []; S.series = {}; S.range = {};
    S.visible = []; S.color = {}; S.started = false;
    const st = document.getElementById("liveStatus");
    if (st) { st.textContent = "Solver starting — waiting for the first channels…";
              st.className = "live-status pending"; }
    const list = document.getElementById("liveChanList");
    if (list) list.innerHTML = "";
    const cnt = document.getElementById("liveChanCount");
    if (cnt) cnt.textContent = "";
    drawLive();
  }

  function init(channels, picks, units) {
    S.channels = channels || [];
    S.units = units || "";
    const pick = new Set(picks || []);
    S.streamed = S.channels.filter(c => pick.has(c.key));
    S.streamed.forEach(c => { S.series[c.key] = []; S.range[c.key] = [Infinity, -Infinity]; });
    // default-plot the first few so the chart isn't a wall of lines
    S.visible = S.streamed.slice(0, 4).map(c => c.key);
    S.streamed.forEach((c, i) => { S.color[c.key] = COLORS[i % COLORS.length]; });
    S.started = true;
    const st = document.getElementById("liveStatus");
    if (st) { st.textContent = "● Run finished — " + S.streamed.length +
                " channels loaded (" + S.channels.length + " in the model)";
              st.className = "live-status streaming"; }
    const cnt = document.getElementById("liveChanCount");
    if (cnt) cnt.textContent = "(" + S.streamed.length + " streaming of " +
                               S.channels.length + " in the model)";
    buildChanList();
    drawLive();
  }

  function frame(frames) {
    if (!S.started || !frames || !frames.length) return;
    for (const f of frames) {
      S.t.push(f.t);
      for (const c of S.streamed) {
        const v = f.vals[c.key];
        const val = (v === undefined || v === null) ? NaN : v;
        S.series[c.key].push(val);
        if (!Number.isNaN(val)) {
          const r = S.range[c.key];
          if (val < r[0]) r[0] = val;
          if (val > r[1]) r[1] = val;
        }
      }
    }
    if (S.t.length > MAXPTS) {
      const drop = S.t.length - MAXPTS;
      S.t.splice(0, drop);
      for (const c of S.streamed) S.series[c.key].splice(0, drop);
    }
    updateLegendValues();
    drawLive();
  }

  function buildChanList() {
    const list = document.getElementById("liveChanList");
    if (!list) return;
    const filter = (document.getElementById("liveChanFilter").value || "")
                     .toLowerCase();
    list.innerHTML = "";
    S.streamed.forEach(c => {
      if (filter && !c.label.toLowerCase().includes(filter)) return;
      const on = S.visible.includes(c.key);
      const row = document.createElement("label");
      row.className = "live-chan" + (on ? " on" : "");
      row.innerHTML =
        '<input type="checkbox" ' + (on ? "checked" : "") + '>' +
        '<span class="sw" style="background:' + S.color[c.key] +
        (on ? "" : ";opacity:.25") + '"></span>' +
        '<span class="nm">' + esc(c.label) + '</span>' +
        (c.unit ? '<span class="un">' + esc(c.unit) + "</span>" : "");
      row.querySelector("input").onchange = e => {
        if (e.target.checked) { if (!S.visible.includes(c.key)) S.visible.push(c.key); }
        else S.visible = S.visible.filter(k => k !== c.key);
        buildChanList(); drawLive();
      };
      list.appendChild(row);
    });
  }

  function updateLegendValues() {
    const leg = document.getElementById("liveLegend");
    if (!leg) return;
    const last = S.t.length - 1;
    leg.innerHTML = "";
    if (last < 0) return;
    leg.appendChild(mkTag("t", S.t[last].toFixed(2) + " s", "var(--fg,#888)"));
    S.visible.forEach(key => {
      const c = S.streamed.find(x => x.key === key); if (!c) return;
      const v = S.series[key][last];
      const txt = Number.isNaN(v) ? "—" :
        (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)) +
        (c.unit ? " " + c.unit : "");
      leg.appendChild(mkTag(c.label, txt, S.color[key]));
    });
  }

  function mkTag(label, val, color) {
    const el = document.createElement("span");
    el.className = "live-tag";
    el.innerHTML = '<i style="background:' + color + '"></i>' +
      '<b>' + esc(label) + '</b> ' + esc(val);
    return el;
  }

  function drawLive() {
    const cv = document.getElementById("livePlot");
    if (!cv) return;
    const dark = document.body.classList.contains("dark");
    const ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height;
    const padL = 46, padR = 14, padT = 14, padB = 26;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = dark ? "#171a1e" : "#fbfaf6";
    ctx.fillRect(0, 0, W, H);

    const grid = dark ? "#2b3138" : "#e6e1d6";
    const axis = dark ? "#8a929c" : "#6a7078";
    const n = S.t.length;
    // frame
    ctx.strokeStyle = grid; ctx.lineWidth = 1;
    ctx.strokeRect(padL, padT, W - padL - padR, H - padT - padB);

    if (n < 2 || !S.visible.length) {
      ctx.fillStyle = axis; ctx.font = "13px system-ui,sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(S.started ? "waiting for samples…" :
        "no run streaming — start a solve to watch it live",
        W / 2, H / 2);
      return;
    }

    const t0 = S.t[0], t1 = S.t[n - 1] || (t0 + 1);
    const X = t => padL + (t - t0) / (t1 - t0 || 1) * (W - padL - padR);
    const Y = u => (H - padB) - u * (H - padT - padB);   // u in 0..1 (normalised)

    // horizontal gridlines + normalised ticks
    ctx.strokeStyle = grid; ctx.fillStyle = axis;
    ctx.font = "10px system-ui,sans-serif"; ctx.textAlign = "right";
    for (let k = 0; k <= 4; k++) {
      const yy = Y(k / 4);
      ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // x ticks (time)
    ctx.textAlign = "center";
    for (let k = 0; k <= 5; k++) {
      const tv = t0 + (t1 - t0) * k / 5;
      ctx.fillText(tv.toFixed(1) + "s", X(tv), H - padB + 15);
    }
    ctx.textAlign = "left"; ctx.fillStyle = axis;
    ctx.fillText("each signal auto-scaled to its own range — read live values in the legend",
                 padL + 4, padT + 12);

    // series (normalised each to its own running range)
    S.visible.forEach(key => {
      const arr = S.series[key], r = S.range[key];
      const span = (r[1] - r[0]) || 1;
      ctx.strokeStyle = S.color[key]; ctx.lineWidth = 1.6;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        const v = arr[i];
        if (Number.isNaN(v)) { started = false; continue; }
        const u = 0.04 + 0.92 * (v - r[0]) / span;   // pad off the edges
        const px = X(S.t[i]), py = Y(u);
        if (!started) { ctx.moveTo(px, py); started = true; }
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  // filter box + scan controls
  document.addEventListener("DOMContentLoaded", function () {
    const f = document.getElementById("liveChanFilter");
    if (f) f.addEventListener("input", buildChanList);
    const sb = document.getElementById("liveScanBtn");
    if (sb) sb.onclick = scan;
    const ab = document.getElementById("liveAddFolderBtn");
    if (ab) ab.onclick = function () {
      if (window.pywebview) pywebview.api.add_scan_folder().then(renderRuns).catch(() => {});
    };
  });

  // ---- solver vitals + health (live, from the solver's stdout) -----------
  const V = { t: [], h: [], wall: 0, running: false };

  function setEl(id, txt) { const e = document.getElementById(id); if (e) e.textContent = txt; }

  function vitalsReset() {
    V.t = []; V.h = []; V.wall = 0; V.running = false;
    ["vtSim", "vtPct", "vtWall", "vtH", "vtOrder", "vtPhi"].forEach(id => setEl(id, "—"));
    drawHealth();
  }

  function vitals(t, order, h, phi, wall) {
    V.running = true;
    V.t.push(t); V.h.push(h); V.wall = wall;
    if (V.t.length > 8000) { V.t.shift(); V.h.shift(); }
    setEl("vtSim", t.toFixed(2));
    setEl("vtWall", wall.toFixed(0) + "s");
    setEl("vtH", h.toExponential(1));
    setEl("vtOrder", String(order));
    setEl("vtPhi", phi.toExponential(1));
    const st = document.getElementById("liveStatus");
    if (st && !st.classList.contains("streaming")) {
      st.textContent = "● Solving — watching the solver advance live";
      st.className = "live-status streaming";
    }
  }

  function vitalsBatch(arr) {
    if (!arr || !arr.length) return;
    for (const v of arr) vitals(v.t, v.order, v.h, v.phi, v.wall);
    drawHealth();
  }

  function liveStatus(text, state) {
    const st = document.getElementById("liveStatus");
    if (st) {
      st.textContent = text;
      st.className = "live-status" + (state === "done" || state === "live" ? " streaming" : "");
    }
    if (state === "done") V.running = false;
  }

  function setPct(frac) {
    if (frac != null) setEl("vtPct", (frac * 100).toFixed(0) + "%");
  }

  function drawHealth() {
    const cv = document.getElementById("liveHealth");
    if (!cv) return;
    const dark = document.body.classList.contains("dark");
    const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
    const pL = 54, pR = 12, pT = 8, pB = 18;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = dark ? "#171a1e" : "#f7f9fb"; ctx.fillRect(0, 0, W, H);
    const grid = dark ? "#2b3138" : "#e6e1d6", axis = dark ? "#8a929c" : "#6a7078";
    ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.strokeRect(pL, pT, W - pL - pR, H - pT - pB);
    const n = V.t.length;
    if (n < 2) {
      ctx.fillStyle = axis; ctx.font = "12px system-ui"; ctx.textAlign = "center";
      ctx.fillText(V.running ? "waiting for steps…" : "no run solving", W / 2, H / 2);
      return;
    }
    const t0 = V.t[0], t1 = V.t[n - 1] || (t0 + 1);
    const hs = V.h.filter(x => x > 0);
    const lo = Math.log10(Math.min.apply(null, hs)), hi = Math.log10(Math.max.apply(null, hs));
    const span = (hi - lo) || 1;
    const X = t => pL + (t - t0) / (t1 - t0 || 1) * (W - pL - pR);
    const Y = h => (H - pB) - (Math.log10(h) - lo) / span * (H - pT - pB);
    ctx.strokeStyle = grid; ctx.fillStyle = axis; ctx.font = "9px system-ui"; ctx.textAlign = "right";
    for (let k = 0; k <= 2; k++) {
      const yy = pT + k / 2 * (H - pT - pB), hv = Math.pow(10, hi - k / 2 * span);
      ctx.globalAlpha = .5; ctx.beginPath(); ctx.moveTo(pL, yy); ctx.lineTo(W - pR, yy); ctx.stroke();
      ctx.globalAlpha = 1; ctx.fillText(hv.toExponential(0), pL - 4, yy + 3);
    }
    const css = getComputedStyle(document.documentElement);
    ctx.strokeStyle = css.getPropertyValue("--accent") || "#2dc7b0"; ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      if (V.h[i] <= 0) continue;
      const px = X(V.t[i]), py = Y(V.h[i]);
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // ---- scan for / attach to any run (even ones the app didn't launch) -----
  function fmtAge(s) {
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    return Math.round(s / 3600) + "h ago";
  }

  function renderRuns(res) {
    const box = document.getElementById("liveRunList");
    if (!box) return;
    box.innerHTML = "";
    const runs = (res && res.runs) || [];
    const hdr = document.getElementById("liveScanNote");
    if (hdr) hdr.textContent = runs.length
      ? (res.solver_running ? "● a solver is running" : "no solver running")
        + " — " + runs.length + " run(s) found"
      : "no runs found — start a solve, or add a folder to scan";
    runs.forEach(r => {
      const row = document.createElement("div");
      row.className = "live-run" + (r.live ? " live" : r.done ? " done" : "");
      var meta = (r.live ? "LIVE" : r.done ? "done" : "idle")
        + (r.sim_last != null ? " &middot; t=" + r.sim_last + "s" : "")
        + " &middot; " + fmtAge(r.age_s);
      row.innerHTML =
        '<span class="rdot"></span>' +
        '<span class="rn">' + esc(r.name) + "</span>" +
        '<span class="rmeta">' + meta + "</span>" +
        '<button class="rattach">' + (r.live ? "Watch" : "Open") + "</button>";
      row.querySelector(".rattach").onclick = () => attach(r.dir, r.name);
      box.appendChild(row);
    });
  }

  function scan() {
    if (!window.pywebview) return;
    const note = document.getElementById("liveScanNote");
    if (note) note.textContent = "scanning…";
    pywebview.api.scan_runs().then(renderRuns).catch(() => {});
  }

  function attach(dir, name) {
    if (!window.pywebview) return;
    const st = document.getElementById("liveStatus");
    if (st) { st.textContent = "attaching to " + name + "…"; st.className = "live-status pending"; }
    pywebview.api.attach_run(dir).then(() => {}).catch(() => {});
  }

  window.liveOnEnter = function () {
    buildChanList(); updateLegendValues(); drawLive(); drawHealth();
    scan();   // refresh the run list whenever the tab is opened
  };

  // extend the msPipe bridge (defined in app.js)
  if (window.msPipe) {
    const _reset = reset;
    window.msPipe.liveReset = function () { _reset(); vitalsReset(); };
    window.msPipe.liveInit = init;
    window.msPipe.liveFrame = frame;
    window.msPipe.liveVitals = vitals;
    window.msPipe.liveVitalsBatch = vitalsBatch;
    window.msPipe.liveStatus = liveStatus;
    // piggyback on the existing progress push to fill the % tile + mark done
    const _prog = window.msPipe.progress;
    window.msPipe.progress = function (frac, text) {
      if (_prog) _prog.call(window.msPipe, frac, text);
      setPct(frac);
    };
    const _done = window.msPipe.done;
    window.msPipe.done = function (ok, mf4, runDir) {
      if (_done) _done.call(window.msPipe, ok, mf4, runDir);
      V.running = false;
      const st = document.getElementById("liveStatus");
      if (st) {
        st.textContent = ok ? "● Run finished — loading channels…"
                            : "Run stopped/failed — see the log";
        st.className = "live-status" + (ok ? " streaming" : "");
      }
      if (ok) setEl("vtPct", "100%");
    };
  }
})();
