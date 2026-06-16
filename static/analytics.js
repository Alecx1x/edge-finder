"use strict";
// ======================================================================== //
// History & Analytics (features 1-5). Loaded after app.js; shares its globals
// ($, esc, pct, odds, postJSON, getJSON, BOOT) and Chart.js.
// ======================================================================== //
let lastReport = null;
let bankroll = Number(BOOT.bankroll) || 0;
let lastKelly = null;
let activeTab = "value";
let betsData = null;
let betSort = { field: "logged_at", asc: false };
const charts = { edge: null, odds: null, cal: null, btEquity: null, btCal: null, tune: null };
let backtestRan = false;

function destroyChart(k) { if (charts[k]) { charts[k].destroy(); charts[k] = null; } }
function americanToDecimal(o) { return o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o); }

// called by app.js after every successful analysis
function onAnalysis(rep) {
  lastReport = rep;
  drawEdgeSpark(rep);
  wireLogBet();
  updateKelly();
  if (activeTab === "odds") drawOddsChart();
}

// --- feature 3: edge sparkline ------------------------------------------- //
function drawEdgeSpark(rep) {
  const pts = (rep.edge_history && rep.edge_history.points) || [];
  const cv = $("edgeSpark");
  if (!cv || !pts.length) return;
  destroyChart("edge");
  charts.edge = new Chart(cv, {
    type: "line",
    data: {
      labels: pts.map((_, i) => i + 1),
      datasets: [{
        data: pts.map((p) => +(p.edge * 100).toFixed(2)),
        borderColor: "#39d3e0", borderWidth: 2, tension: 0.25, fill: false,
        pointRadius: pts.length > 1 ? 2 : 3, pointBackgroundColor: "#39d3e0",
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `edge ${c.parsed.y} pts` } } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

// --- feature 2: Log This Bet --------------------------------------------- //
function wireLogBet() {
  const btn = $("logBet");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (!lastReport) return;
    const rep = lastReport, rec = rep.recommendation, side = rec.side;
    const payload = {
      sport: rep.sport,
      name_a: rep.matchup.a.name, name_b: rep.matchup.b.name,
      bet_side: side, bet_name: rep.matchup[side].name, bet_odds: rep.matchup[side].odds,
      odds_a: rep.matchup.a.odds, odds_b: rep.matchup.b.odds,
      edge: rec.edge, model_prob: rep.model[side], stake: kellyStake(),
    };
    btn.disabled = true;
    const { data } = await postJSON("/api/bets", payload);
    btn.disabled = false;
    const msg = $("logBetMsg");
    if (data.ok) {
      msg.style.color = "var(--green)";
      msg.textContent = `Logged bet #${data.bet.id}.`;
      betsData = null;
      if (activeTab === "bets") loadBets();
    } else {
      msg.style.color = "var(--red)";
      msg.textContent = data.error || "Could not log bet.";
    }
  });
}

// --- feature 4: Kelly Criterion ------------------------------------------ //
function computeKelly(rep) {
  const side = rep.recommendation.side;
  const p = rep.model[side];                 // model win prob for the bet side
  const o = rep.matchup[side].odds;
  const dec = americanToDecimal(o), b = dec - 1;
  const full = b > 0 ? (b * p - (1 - p)) / b : 0;
  return { side, name: rep.matchup[side].name, p, odds: o, dec, full, half: full / 2, edge: rep.edge[side] };
}

function updateKelly() {
  if (!lastReport) return;
  $("kellyCard").classList.remove("hidden");
  const k = computeKelly(lastReport);
  lastKelly = k;
  const negative = k.edge < 0 || k.full <= 0;
  const fullF = Math.max(0, k.full), halfF = Math.max(0, k.half);
  let html = `<div class="kelly-meta">Bet side: <b>${esc(k.name)}</b> · model ${pct(k.p)} to win @ ${odds(k.odds)} (${k.dec.toFixed(2)} dec)</div>
    <div class="kelly-grid">
      <div class="kelly-tile"><div class="k-label">Full Kelly</div><div class="k-pct">${(fullF * 100).toFixed(1)}%</div><div class="k-amt">$${(fullF * bankroll).toFixed(2)}</div></div>
      <div class="kelly-tile"><div class="k-label">Half Kelly</div><div class="k-pct">${(halfF * 100).toFixed(1)}%</div><div class="k-amt">$${(halfF * bankroll).toFixed(2)}</div></div>
    </div>`;
  if (negative) {
    html += `<div class="kelly-warn">⚠ Negative edge — Kelly says no bet. The model prices this side at or below the market, so any stake is −EV.</div>`;
  }
  $("kellyBody").innerHTML = html;
}

function kellyStake() {
  return lastKelly && lastKelly.half > 0 ? +(lastKelly.half * bankroll).toFixed(2) : null;
}

$("bankrollInput").value = bankroll;
$("bankrollInput").addEventListener("change", async () => {
  const v = parseFloat($("bankrollInput").value);
  const msg = $("bankrollMsg");
  if (isNaN(v) || v < 0) { msg.style.color = "var(--red)"; msg.textContent = "invalid"; return; }
  bankroll = v;
  updateKelly();
  const { data } = await postJSON("/api/bankroll", { bankroll: v });
  msg.style.color = data.ok ? "var(--green)" : "var(--red)";
  msg.textContent = data.ok ? "saved" : (data.error || "error");
  setTimeout(() => { msg.textContent = ""; }, 1500);
});

// --- tabs ---------------------------------------------------------------- //
$("analyticsTabs").addEventListener("click", (e) => {
  const t = e.target.closest(".tab");
  if (!t) return;
  activeTab = t.dataset.tab;
  [...$("analyticsTabs").children].forEach((c) => c.classList.toggle("active", c === t));
  ["odds", "bets", "cal", "backtest", "tune", "value", "clv", "arb", "promo", "pickem", "sweeps"].forEach((name) => $("tab-" + name).classList.toggle("hidden", name !== activeTab));
  if (activeTab === "odds") drawOddsChart();
  else if (activeTab === "bets") loadBets();
  else if (activeTab === "cal") loadCalibration();
  else if (activeTab === "clv") loadClv();
});

// --- feature 1: odds movement -------------------------------------------- //
function sharpFlag(snaps, i, side) {
  if (i === 0) return false;
  const prev = snaps[i - 1], cur = snaps[i];
  const impPrev = side === "a" ? prev.implied_a : prev.implied_b;
  const impCur = side === "a" ? cur.implied_a : cur.implied_b;
  const pub = side === "a" ? cur.public_a : cur.public_b;
  if (pub == null) return false;
  // line shortened on this side (implied prob up) while public tickets are light = sharp money
  return (impCur - impPrev) > 0.005 && pub < 50;
}

function sharpMessage(oh) {
  const s = oh.snapshots;
  if (s.length < 2) return null;
  const i = s.length - 1;
  for (const side of ["a", "b"]) {
    if (sharpFlag(s, i, side)) {
      const name = side === "a" ? oh.a : oh.b;
      const pub = side === "a" ? s[i].public_a : s[i].public_b;
      return `line moved toward ${name} while only ${pub.toFixed(0)}% of tickets backed them — classic sharp action.`;
    }
  }
  return null;
}

function drawOddsChart() {
  const note = $("oddsNote");
  const oh = lastReport && lastReport.odds_history;
  destroyChart("odds");
  if (!oh || !oh.snapshots || !oh.snapshots.length) {
    note.textContent = "Run Find Edge on a matchup to record and chart its odds movement.";
    return;
  }
  const snaps = oh.snapshots;
  const labels = snaps.map((s) => new Date(s.ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }));
  const colA = snaps.map((_, i) => sharpFlag(snaps, i, "a") ? "#e3b341" : "#39d3e0");
  const colB = snaps.map((_, i) => sharpFlag(snaps, i, "b") ? "#e3b341" : "#f85149");
  charts.odds = new Chart($("oddsChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: oh.a, data: snaps.map((s) => s.odds_a), borderColor: "#39d3e0", pointRadius: 5, pointBackgroundColor: colA, tension: 0.2 },
        { label: oh.b, data: snaps.map((s) => s.odds_b), borderColor: "#f85149", pointRadius: 5, pointBackgroundColor: colB, tension: 0.2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b949e" } } },
      scales: {
        x: { ticks: { color: "#8b949e", maxRotation: 0, autoSkip: true } },
        y: { ticks: { color: "#8b949e" }, title: { display: true, text: "American odds", color: "#8b949e" } },
      },
    },
  });
  const msg = sharpMessage(oh);
  note.innerHTML = msg
    ? `<span class="sharp">⚡ Sharp money:</span> ${esc(msg)}`
    : `${snaps.length} snapshot${snaps.length > 1 ? "s" : ""} recorded. Amber points = line moved against public betting %.`;
}

// --- feature 2: bet log table -------------------------------------------- //
async function loadBets() {
  const wrap = $("betsTable");
  if (betsData === null) {
    wrap.innerHTML = '<div class="empty-note"><span class="spinner"></span>Loading…</div>';
    const d = await getJSON("/api/bets");
    betsData = d.bets || [];
  }
  renderBets();
}

function cmpBets(x, y) {
  const f = betSort.field;
  let xv = f === "matchup" ? x.name_a : x[f];
  let yv = f === "matchup" ? y.name_a : y[f];
  if (xv == null) xv = "";
  if (yv == null) yv = "";
  const r = (typeof xv === "number" && typeof yv === "number")
    ? xv - yv : String(xv).localeCompare(String(yv));
  return betSort.asc ? r : -r;
}

function renderBets() {
  const wrap = $("betsTable");
  if (!betsData.length) {
    wrap.innerHTML = '<div class="empty-note">No bets logged yet. Run an analysis and click “Log This Bet”.</div>';
    return;
  }
  const rows = [...betsData].sort(cmpBets);
  const cols = [["logged_at", "Date"], ["matchup", "Matchup"], ["bet_name", "Bet"],
                ["bet_odds", "Odds"], ["edge", "Edge"], ["model_prob", "Model"], ["result", "Result"]];
  let html = '<table class="bets-table"><thead><tr>';
  for (const [f, l] of cols) {
    const sc = betSort.field === f ? `sorted ${betSort.asc ? "asc" : ""}` : "";
    html += `<th class="${sc}" data-f="${f}">${l}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const b of rows) {
    const date = new Date(b.logged_at).toLocaleDateString([], { month: "short", day: "numeric" });
    const res = b.result
      ? `<span class="res-badge res-${b.result}">${b.result.toUpperCase()}</span>`
      : `<div class="res-btns" data-id="${b.id}"><button data-r="win">W</button><button data-r="loss">L</button><button data-r="push">P</button></div>`;
    html += `<tr>
      <td>${date}</td>
      <td>${esc(b.name_a)} <span class="dim">v</span> ${esc(b.name_b)}</td>
      <td>${esc(b.bet_name)}</td>
      <td>${odds(b.bet_odds)}</td>
      <td class="${b.edge >= 0 ? "pos" : "neg"}">${(b.edge * 100).toFixed(1)}</td>
      <td>${pct(b.model_prob)}</td>
      <td>${res}</td></tr>`;
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
}

$("betsTable").addEventListener("click", async (e) => {
  const th = e.target.closest("th[data-f]");
  if (th) {
    const f = th.dataset.f;
    if (betSort.field === f) betSort.asc = !betSort.asc;
    else { betSort.field = f; betSort.asc = true; }
    renderBets();
    return;
  }
  const rb = e.target.closest(".res-btns button");
  if (rb) {
    const id = +rb.parentElement.dataset.id;
    const { data } = await postJSON(`/api/bets/${id}/result`, { result: rb.dataset.r });
    if (data.ok) { betsData = null; await loadBets(); }
  }
});

// --- feature 5: calibration dashboard ------------------------------------ //
async function loadCalibration() {
  const note = $("calNote");
  const cv = $("calChart");
  destroyChart("cal");
  const d = await getJSON("/api/calibration");
  if (!d.enough) {
    cv.style.display = "none";
    note.textContent = `Calibration needs at least ${d.min_required} logged bets — you have ${d.total}. Log and settle more bets to unlock this dashboard.`;
    return;
  }
  cv.style.display = "";
  charts.cal = new Chart(cv, {
    type: "bar",
    data: {
      labels: d.buckets.map((b) => b.label),
      datasets: [
        { label: "Predicted win %", data: d.buckets.map((b) => b.predicted != null ? +(b.predicted * 100).toFixed(1) : null), backgroundColor: "#4493f8" },
        { label: "Actual win %", data: d.buckets.map((b) => b.actual != null ? +(b.actual * 100).toFixed(1) : null), backgroundColor: "#3fb950" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b949e" } } },
      scales: { x: { ticks: { color: "#8b949e" } }, y: { beginAtZero: true, max: 100, ticks: { color: "#8b949e" } } },
    },
  });
  const settled = d.buckets.reduce((n, b) => n + b.settled, 0);
  note.textContent = `${d.total} bets logged, ${settled} settled. Bars compare model-predicted win rate vs realized outcomes per probability band.`;
}

// --- backtest dashboard -------------------------------------------------- //
function fmtPct(x, digits = 1) {
  return typeof x === "number" ? `${(x * 100).toFixed(digits)}%` : "n/a";
}

function btCard(label, value, cls, sub) {
  return `<div class="bt-tile ${cls || ""}">
    <div class="bt-tile-label">${label}</div>
    <div class="bt-tile-value">${value}</div>
    ${sub ? `<div class="bt-tile-sub">${sub}</div>` : ""}
  </div>`;
}

function renderBacktest(s) {
  const pred = s.prediction, bet = s.betting.model, base = s.betting.baseline_favorite;
  const beats = pred.beats_market;
  const roiCls = (typeof bet.roi === "number" && bet.roi >= 0) ? "good" : "bad";

  // Plain-English verdict
  let verdict;
  if (beats && typeof bet.roi === "number" && bet.roi > 0) {
    verdict = `<span class="good">This model both predicts better than the market AND turned a profit over ${bet.n} bets. Worth a closer look — and a walk-forward test before trusting it.</span>`;
  } else if (typeof bet.roi === "number" && bet.roi <= 0) {
    verdict = `<span class="bad">No edge here.</span> The market is ${beats ? "not " : ""}sharper than this model, and betting its picks lost money (${fmtPct(bet.roi)} ROI over ${bet.n} bets). That's the honest result — these signals don't beat the closing line yet. Next: let the data re-weight the signals (phase 2) and add ones the market doesn't already price.`;
  } else {
    verdict = `Not enough bets cleared the threshold to judge. Lower the “min edge” and re-run.`;
  }

  $("btScorecard").innerHTML = `
    <div class="bt-verdict">${verdict}</div>
    <div class="bt-section-label">Prediction quality — can the model out-guess the closing line? (lower Brier = better)</div>
    <div class="bt-tiles">
      ${btCard("Model Brier", pred.model.brier, beats ? "good" : "")}
      ${btCard("Market Brier", pred.market.brier, beats ? "" : "good", "the bar to beat")}
      ${btCard("Verdict", beats ? "Model wins" : "Market sharper", beats ? "good" : "bad")}
      ${btCard("Signal coverage", fmtPct(s.avg_availability), "", "how far the model moves off the line")}
    </div>
    <div class="bt-section-label">Betting result — would placing these bets have made money?</div>
    <div class="bt-tiles">
      ${btCard("Bets placed", bet.n, "", `of ${s.n_fights} fights · edge ≥ ${fmtPct(s.edge_threshold, 0)}`)}
      ${btCard("Win rate", fmtPct(bet.win_rate), "")}
      ${btCard("ROI (flat)", fmtPct(bet.roi), roiCls, "$1 per bet")}
      ${btCard("ROI (½ Kelly)", fmtPct(bet.roi_kelly), (typeof bet.roi_kelly === "number" && bet.roi_kelly >= 0) ? "good" : "bad", `bankroll 100 → ${bet.final_bankroll}`)}
      ${btCard("Baseline", fmtPct(base.roi), "", "always bet the favourite")}
    </div>`;

  drawEquityChart(s.equity_curve);
  drawBacktestCalibration(pred.calibration);
}

function drawEquityChart(curve) {
  destroyChart("btEquity");
  const note = $("btEquityNote");
  if (!curve || !curve.length) {
    note.textContent = "No bets were placed at this threshold, so there's no equity curve. Lower the minimum edge and re-run.";
    return;
  }
  charts.btEquity = new Chart($("btEquityChart"), {
    type: "line",
    data: {
      labels: curve.map((p) => p.date),
      datasets: [
        { label: "½-Kelly bankroll (start 100)", data: curve.map((p) => p.kelly_bankroll),
          borderColor: "#3fb950", borderWidth: 2, pointRadius: 0, tension: 0.1, yAxisID: "yK" },
        { label: "Flat cumulative profit (units)", data: curve.map((p) => p.flat_profit),
          borderColor: "#e3b341", borderWidth: 2, pointRadius: 0, tension: 0.1, yAxisID: "yF" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b949e" } } },
      scales: {
        x: { ticks: { color: "#8b949e", maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
        yK: { position: "left", ticks: { color: "#3fb950" }, title: { display: true, text: "Kelly bankroll", color: "#3fb950" } },
        yF: { position: "right", ticks: { color: "#e3b341" }, grid: { drawOnChartArea: false }, title: { display: true, text: "Flat profit", color: "#e3b341" } },
      },
    },
  });
  note.innerHTML = `Each point is a placed bet, oldest → newest. A line sliding down = the strategy bleeding money. The Kelly line hitting zero = bankruptcy.`;
}

function drawBacktestCalibration(buckets) {
  destroyChart("btCal");
  const note = $("btCalNote");
  if (!buckets || !buckets.length) { note.textContent = ""; return; }
  charts.btCal = new Chart($("btCalChart"), {
    type: "bar",
    data: {
      labels: buckets.map((b) => b.label),
      datasets: [
        { label: "Model predicted win %", data: buckets.map((b) => b.predicted != null ? +(b.predicted * 100).toFixed(1) : null), backgroundColor: "#4493f8" },
        { label: "Actually won %", data: buckets.map((b) => b.actual != null ? +(b.actual * 100).toFixed(1) : null), backgroundColor: "#3fb950" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b949e" } } },
      scales: { x: { ticks: { color: "#8b949e" } }, y: { beginAtZero: true, max: 100, ticks: { color: "#8b949e" } } },
    },
  });
  note.innerHTML = `When the model says a side is X% likely, did that group actually win ~X%? Bars that line up = well-calibrated. Bars where “actual” towers over “predicted” mean the model is under-confident (a lever for phase 2).`;
}

$("btRun").addEventListener("click", async () => {
  const btn = $("btRun"), msg = $("btMsg");
  const edge = Math.max(0, parseFloat($("btEdge").value) || 0) / 100;
  const body = { edge_threshold: edge, date_from: $("btFrom").value || null, date_to: $("btTo").value || null };
  btn.disabled = true;
  msg.style.color = "var(--muted, #8b949e)";
  msg.textContent = "Replaying thousands of fights…";
  try {
    const { data } = await postJSON("/api/backtest", body);
    if (data.error) {
      msg.style.color = "var(--red)";
      msg.textContent = data.error;
    } else {
      msg.textContent = "";
      backtestRan = true;
      renderBacktest(data);
    }
  } catch (e) {
    msg.style.color = "var(--red)";
    msg.textContent = "Backtest request failed.";
  } finally {
    btn.disabled = false;
  }
});

// --- auto-tune (walk-forward) dashboard ---------------------------------- //
let lastTune = null;

function tuneVerdict(r) {
  const w = r.tuned_weights, test = r.test, base = r.baseline_test;
  const ignored = (w.elo || 0) === 0 && (w.recent_form || 0) === 0;
  const gap = r.overfit_gap;
  if (ignored) {
    return `<span class="bad">The tuner chose to ignore your signals entirely</span> (every weight → 0) and just trust the closing line. That's the strongest possible verdict that Elo + recent form add <b>no edge the market hasn't already priced</b>. The honest move is to bet nothing — until you find information the market doesn't have.`;
  }
  if (typeof test.roi_flat === "number" && test.roi_flat > 0 &&
      (base.roi_flat == null || test.roi_flat > base.roi_flat)) {
    return `<span class="good">Promising:</span> the tuned weights stayed profitable on the unseen test slice (${fmtPct(test.roi_flat)} ROI). Before trusting it, re-run with different splits — one lucky test window isn't proof.`;
  }
  let s = `<span class="bad">No durable edge.</span> The best weights found on training history `;
  if (typeof gap === "number" && gap > 0.02) {
    s += `looked better in-sample but <b>dropped ${(gap * 100).toFixed(1)} points</b> on the unseen test slice — that drop is overfitting, the mirage that empties bankrolls. `;
  } else {
    s += `lost money on the unseen test slice too (${fmtPct(test.roi_flat)} ROI). `;
  }
  s += `The test number is the truth, and it says these signals don't beat the market yet.`;
  return s;
}

function tuneRow(label, train, test, fmt) {
  const f = fmt || fmtPct;
  return `<tr><td>${label}</td><td>${f(train)}</td><td class="tune-test">${f(test)}</td></tr>`;
}

function renderTune(r) {
  lastTune = r;
  const w = r.tuned_weights;
  const objLabel = r.objective === "roi" ? "profit (ROI)" : "prediction accuracy";
  $("tuneScorecard").innerHTML = `
    <div class="bt-verdict">${tuneVerdict(r)}</div>
    <div class="bt-section-label">What it did</div>
    <p class="chart-note" style="margin-top:0">
      Optimized for <b>${objLabel}</b>. Trained on ${r.n_train} fights
      (${r.train_from} → ${r.train_to}), then graded on ${r.n_test}
      <b>unseen</b> fights (${r.test_from} → ${r.test_to}).
      Best weights found: <b>Elo ${w.elo}</b>, <b>recent form ${w.recent_form}</b>.
    </p>
    <table class="tune-table">
      <thead><tr><th>Metric</th><th>Train</th><th class="tune-test">Test (trust this)</th></tr></thead>
      <tbody>
        ${tuneRow("ROI (flat)", r.train.roi_flat, r.test.roi_flat)}
        ${tuneRow("ROI (½ Kelly)", r.train.roi_kelly, r.test.roi_kelly)}
        ${tuneRow("Brier (lower=better)", r.train.brier, r.test.brier, (x) => typeof x === "number" ? x.toFixed(4) : "n/a")}
        ${tuneRow("Bets placed", r.train.n_bets, r.test.n_bets, (x) => x)}
      </tbody>
    </table>
    <p class="chart-note">Baseline (your current equal weights) on the same test slice:
      ROI <b>${fmtPct(r.baseline_test.roi_flat)}</b>.</p>
    <button id="tuneApply" class="btn" type="button">Apply these weights to my model</button>
    <span id="tuneApplyMsg" class="hint"></span>`;

  $("tuneApply").addEventListener("click", applyTunedWeights);
  drawTuneChart(r);
}

function drawTuneChart(r) {
  destroyChart("tune");
  const pct = (x) => typeof x === "number" ? +(x * 100).toFixed(1) : null;
  charts.tune = new Chart($("tuneChart"), {
    type: "bar",
    data: {
      labels: ["ROI flat %", "ROI ½-Kelly %"],
      datasets: [
        { label: "Train (in-sample)", data: [pct(r.train.roi_flat), pct(r.train.roi_kelly)], backgroundColor: "#e3b341" },
        { label: "Test (unseen — the truth)", data: [pct(r.test.roi_flat), pct(r.test.roi_kelly)], backgroundColor: "#3fb950" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b949e" } } },
      scales: { x: { ticks: { color: "#8b949e" } }, y: { ticks: { color: "#8b949e" }, title: { display: true, text: "ROI %", color: "#8b949e" } } },
    },
  });
  $("tuneChartNote").innerHTML = "Amber = how it looked on data it was tuned on. Green = how it held up on fights it never saw. When green sits well below amber, that gap is overfitting.";
}

async function applyTunedWeights() {
  if (!lastTune) return;
  const btn = $("tuneApply"), msg = $("tuneApplyMsg");
  btn.disabled = true;
  const { data } = await postJSON("/api/weights", { weights: lastTune.tuned_weights });
  btn.disabled = false;
  if (data.ok) {
    msg.style.color = "var(--green)";
    msg.textContent = "Applied. New analyses use these weights (reload to update the sliders).";
  } else {
    msg.style.color = "var(--red)";
    msg.textContent = data.error || "Could not apply weights.";
  }
}

$("tuneRun").addEventListener("click", async () => {
  const btn = $("tuneRun"), msg = $("tuneMsg");
  const body = {
    objective: $("tuneObjective").value,
    train_frac: (Math.max(30, Math.min(90, parseFloat($("tuneTrain").value) || 70))) / 100,
    edge_threshold: Math.max(0, parseFloat($("tuneEdge").value) || 0) / 100,
  };
  btn.disabled = true;
  msg.style.color = "var(--muted, #8b949e)";
  msg.textContent = "Searching weights & walk-forward testing…";
  try {
    const { data } = await postJSON("/api/tune", body);
    if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; }
    else { msg.textContent = ""; renderTune(data); }
  } catch (e) {
    msg.style.color = "var(--red)";
    msg.textContent = "Auto-tune request failed.";
  } finally {
    btn.disabled = false;
  }
});

// --- value finder (+EV scanner) ------------------------------------------ //
function renderScan(res) {
  const summary = $("valSummary"), wrap = $("valTable");
  const q = res.quota || {};
  let head = `Scanned ${res.leagues.length} league(s): ${res.leagues.map(esc).join(", ") || "none"}.`;
  if (q.remaining != null) head += ` · <b>${q.remaining}</b> requests left this month.`;
  if (res.no_pinnacle) {
    head += ` <span class="warn-text">Pinnacle wasn't in the results — using a weaker market-consensus fair line. Add “eu” to regions for a true sharp reference.</span>`;
  }
  summary.innerHTML = head;

  if (!res.opportunities.length) {
    wrap.innerHTML = '<div class="empty-note">No +EV bets at this threshold right now. Lower Min EV, widen regions, or try again later — value appears and vanishes as lines move.</div>';
    return;
  }
  let html = '<table class="bets-table val-table"><thead><tr>'
    + '<th>EV</th><th>Bet</th><th>Odds</th><th>Book</th><th>Stake</th><th>Fair</th><th>Event</th><th></th></tr></thead><tbody>';
  res.opportunities.forEach((o, i) => {
    const evCls = o.ev_pct >= 0.05 ? "pos" : "";
    const badge = o.book_type === "sharp"
      ? '<span class="book-badge sharp">sharp</span>'
      : (o.book_type === "soft" ? '<span class="book-badge soft">soft</span>' : "");
    const risk = o.limit_risk ? ' <span class="book-badge risk" title="Edge this big is often a stale/erroneous line — books may void or limit. Verify before betting.">⚠ verify</span>' : "";
    html += `<tr>
      <td class="${evCls}"><b>${(o.ev_pct * 100).toFixed(1)}%</b></td>
      <td>${esc(o.selection)}${risk}</td>
      <td>${odds(o.price)}</td>
      <td>${esc(o.book)} ${badge}</td>
      <td>$${o.suggested_stake}</td>
      <td>${pct(o.fair_prob)}</td>
      <td class="dim">${esc(o.event)}<br><span class="val-league">${esc(o.league)}</span></td>
      <td><button class="track-btn" data-i="${i}" title="Log this to your Bet Log (Step 2)">＋ Track</button></td>
    </tr>`;
  });
  html += "</tbody></table>";
  wrap.innerHTML = html;
  lastScan = res.opportunities;
}

// one-click: send a Value Finder pick straight to the Bet Log (no re-typing)
let lastScan = null;
$("valTable").addEventListener("click", async (e) => {
  const btn = e.target.closest(".track-btn");
  if (!btn || !lastScan) return;
  const o = lastScan[+btn.dataset.i];
  if (!o) return;
  btn.disabled = true;
  const payload = {
    sport: o.sport,
    name_a: o.selection, name_b: o.opponent || "Other side",
    bet_side: "a", bet_name: o.selection, bet_odds: o.price,
    odds_a: o.price, odds_b: o.opponent_price,
    edge: o.ev_pct, model_prob: o.fair_prob, stake: o.suggested_stake,
  };
  const { data } = await postJSON("/api/bets", payload);
  if (data.ok) {
    btn.textContent = "✓ Tracked";
    btn.classList.add("tracked");
    betsData = null;   // force Bet Log refresh next time it's opened
  } else {
    btn.disabled = false;
    btn.textContent = "✗ retry";
  }
});

$("valRun").addEventListener("click", async () => {
  const btn = $("valRun"), msg = $("valMsg");
  const body = {
    sport: $("valSport").value,
    min_ev: Math.max(0, parseFloat($("valEv").value) || 0) / 100,
    regions: $("valRegions").value,
    max_keys: Math.max(1, Math.min(12, parseInt($("valMaxKeys").value) || 4)),
  };
  btn.disabled = true;
  msg.style.color = "var(--muted, #8b949e)";
  msg.textContent = "Scanning the board…";
  try {
    const { data } = await postJSON("/api/scan", body);
    if (data.error) {
      msg.style.color = "var(--red)";
      msg.textContent = data.error;
    } else {
      msg.textContent = "";
      renderScan(data);
    }
  } catch (e) {
    msg.style.color = "var(--red)";
    msg.textContent = "Scan request failed.";
  } finally {
    btn.disabled = false;
  }
});

// --- beat the close (CLV) ------------------------------------------------ //
let clvBets = null;

async function loadClv() {
  const [summary, bets] = await Promise.all([
    getJSON("/api/clv"), getJSON("/api/bets"),
  ]);
  clvBets = bets.bets || [];
  renderClvScorecard(summary);
  renderClvTable();
}

function clvVerdict(s) {
  if (!s.enough) {
    return `Capture the close on <b>${s.min_required - s.n}</b> more bet(s) to unlock the verdict. CLV needs a sample before it means anything.`;
  }
  const br = s.beat_rate, clv = s.avg_clv;
  if (br >= 0.55 && clv > 0) {
    return `<span class="good">You're beating the close.</span> Getting better prices than the market settles at, ${fmtPct(br)} of the time (avg CLV ${fmtPct(clv)}), is the strongest evidence that you're genuinely sharp — not just lucky. This is the green light to scale stakes carefully and consider paid scanning tools.`;
  }
  if (br >= 0.45) {
    return `<span class="warn-text">Roughly even with the close.</span> You're not consistently beating the market yet (${fmtPct(br)} beat rate, avg CLV ${fmtPct(clv)}). No proven edge — keep logging before you scale up.`;
  }
  return `<span class="bad">You're getting worse prices than the close.</span> ${fmtPct(br)} beat rate (avg CLV ${fmtPct(clv)}) means the value isn't translating — the market is moving against your bets. Don't increase stakes; this is the signal to rethink, not double down.`;
}

function renderClvScorecard(s) {
  $("clvScorecard").innerHTML = `
    <div class="bt-verdict">${clvVerdict(s)}</div>
    <div class="bt-tiles">
      ${btCard("Beat-close rate", fmtPct(s.beat_rate), s.beat_rate != null && s.beat_rate >= 0.55 ? "good" : "", `${s.beat}/${s.n} bets`)}
      ${btCard("Avg CLV", fmtPct(s.avg_clv), (typeof s.avg_clv === "number" && s.avg_clv > 0) ? "good" : "bad", "your price vs close")}
      ${btCard("Avg EV vs close", fmtPct(s.avg_ev), (typeof s.avg_ev === "number" && s.avg_ev > 0) ? "good" : "", "when both close odds entered")}
      ${btCard("Captured", s.n, "", `need ${s.min_required} for a verdict`)}
    </div>`;
}

function renderClvTable() {
  const wrap = $("clvTable");
  if (!clvBets.length) {
    wrap.innerHTML = '<div class="empty-note">No bets logged yet. Log a bet in the Bet Log tab, then record its close here.</div>';
    return;
  }
  let html = '<table class="bets-table clv-table"><thead><tr>'
    + '<th>Matchup</th><th>Your bet</th><th>Close / CLV</th></tr></thead><tbody>';
  for (const b of clvBets) {
    const betCell = `${esc(b.bet_name)} @ ${odds(b.bet_odds)}`;
    let last;
    if (typeof b.clv_pct === "number") {
      const cls = b.clv_pct > 0 ? "pos" : "neg";
      const evTxt = typeof b.ev_vs_close === "number" ? ` · EV ${(b.ev_vs_close * 100).toFixed(1)}%` : "";
      last = `<span class="${cls}">${(b.clv_pct * 100).toFixed(1)}% CLV</span> <span class="dim">(closed ${odds(b.close_odds)})${evTxt}</span>`;
    } else {
      last = `<div class="clv-entry" data-id="${b.id}">
        <input class="clv-side" type="text" placeholder="your side close (-120)" />
        <input class="clv-other" type="text" placeholder="other side (opt)" />
        <button data-act="save">Save</button>
        <button data-act="auto" title="Pull from the API — costs 1 request">Auto</button>
        <span class="clv-msg"></span></div>`;
    }
    html += `<tr><td>${esc(b.name_a)} <span class="dim">v</span> ${esc(b.name_b)}</td>
      <td>${betCell}</td><td>${last}</td></tr>`;
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
}

$("clvTable").addEventListener("click", async (e) => {
  const btn = e.target.closest(".clv-entry button");
  if (!btn) return;
  const box = btn.closest(".clv-entry");
  const id = box.dataset.id;
  const msg = box.querySelector(".clv-msg");
  let data;
  if (btn.dataset.act === "save") {
    const side = box.querySelector(".clv-side").value.trim();
    const other = box.querySelector(".clv-other").value.trim();
    if (!side) { msg.style.color = "var(--red)"; msg.textContent = "enter your side's close"; return; }
    btn.disabled = true;
    ({ data } = await postJSON(`/api/bets/${id}/close`, { close_side: side, other_close: other || null }));
  } else {
    btn.disabled = true;
    msg.style.color = "var(--muted, #8b949e)";
    msg.textContent = "fetching…";
    ({ data } = await postJSON(`/api/bets/${id}/capture`, {}));
  }
  if (data.ok) { await loadClv(); }
  else { btn.disabled = false; msg.style.color = "var(--red)"; msg.textContent = data.error || "failed"; }
});

// --- "My books" filter --------------------------------------------------- //
async function loadBooks() {
  let d;
  try { d = await getJSON("/api/books"); } catch (e) { return; }
  const selected = new Set(d.selected || []);
  const groups = {};
  (d.available || []).forEach((b) => { (groups[b.group] = groups[b.group] || []).push(b); });
  let html = "";
  for (const [group, books] of Object.entries(groups)) {
    html += `<div class="books-group"><div class="books-group-label">${esc(group)}</div>`;
    for (const b of books) {
      const on = selected.has(b.key) ? "checked" : "";
      html += `<label class="book-chk"><input type="checkbox" value="${esc(b.key)}" ${on}/> ${esc(b.title)}</label>`;
    }
    html += "</div>";
  }
  $("booksList").innerHTML = html;
  // if the user already has a selection, label the summary so it's obvious
  const fb = $("booksFilter");
  if (selected.size) fb.querySelector("summary").dataset.count = `${selected.size} selected`;
}

async function saveBooks(keys) {
  const msg = $("booksMsg");
  const { data } = await postJSON("/api/books", { books: keys });
  if (data.ok) {
    msg.style.color = "var(--green)";
    msg.textContent = keys.length ? `Saved — scans now show only your ${keys.length} book(s).` : "Cleared — scans show all books.";
    $("booksFilter").querySelector("summary").dataset.count = keys.length ? `${keys.length} selected` : "";
  } else {
    msg.style.color = "var(--red)"; msg.textContent = data.error || "Save failed.";
  }
}

$("booksSave").addEventListener("click", () => {
  const keys = [...$("booksList").querySelectorAll("input:checked")].map((c) => c.value);
  saveBooks(keys);
});
$("booksClear").addEventListener("click", () => {
  $("booksList").querySelectorAll("input:checked").forEach((c) => { c.checked = false; });
  saveBooks([]);
});
loadBooks();

// --- arbitrage scanner --------------------------------------------------- //
function renderArb(res) {
  const summary = $("arbSummary"), wrap = $("arbResults");
  const q = res.quota || {};
  let head = `Scanned ${res.leagues.length} league(s): ${res.leagues.map(esc).join(", ") || "none"}.`;
  if (q.remaining != null) head += ` · <b>${q.remaining}</b> requests left.`;
  summary.innerHTML = head;
  if (!res.arbs.length) {
    wrap.innerHTML = '<div class="empty-note">No arbitrage right now — totally normal, they\'re rare and last seconds. Try again or widen regions.</div>';
    return;
  }
  let html = "";
  for (const a of res.arbs) {
    const legs = a.legs.map((l) => {
      const badge = l.book_type === "sharp" ? '<span class="book-badge sharp">sharp</span>'
        : (l.book_type === "soft" ? '<span class="book-badge soft">soft</span>' : "");
      return `<tr><td>$${l.stake}</td><td>${esc(l.selection)}</td><td>${odds(l.odds)}</td><td>${esc(l.book)} ${badge}</td></tr>`;
    }).join("");
    html += `<div class="arb-card">
      <div class="arb-head">
        <span class="arb-profit pos">${(a.profit_pct * 100).toFixed(2)}% locked</span>
        <span class="dim">${esc(a.event)} · ${esc(a.league)}</span>
        <span class="arb-ret">stake $${a.total_stake} → $${a.guaranteed_return} (profit $${a.profit})</span>
      </div>
      <table class="bets-table arb-legs"><thead><tr><th>Stake</th><th>Bet</th><th>Odds</th><th>Book</th></tr></thead>
        <tbody>${legs}</tbody></table>
    </div>`;
  }
  wrap.innerHTML = html;
}

$("arbRun").addEventListener("click", async () => {
  const btn = $("arbRun"), msg = $("arbMsg");
  const body = {
    sport: $("arbSport").value,
    total_stake: Math.max(1, parseFloat($("arbStake").value) || 100),
    min_profit: Math.max(0, parseFloat($("arbMinProfit").value) || 0) / 100,
    regions: $("arbRegions").value,
    max_keys: Math.max(1, Math.min(12, parseInt($("arbMaxKeys").value) || 4)),
  };
  btn.disabled = true;
  msg.style.color = "var(--muted, #8b949e)";
  msg.textContent = "Scanning for arbs…";
  try {
    const { data } = await postJSON("/api/arb", body);
    if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; }
    else { msg.textContent = ""; renderArb(data); }
  } catch (e) {
    msg.style.color = "var(--red)"; msg.textContent = "Arb scan failed.";
  } finally { btn.disabled = false; }
});

// --- matched-betting calculator ------------------------------------------ //
function renderPromo(r, isFree) {
  const lockedCls = r.locked >= 0 ? "good" : "bad";
  const retention = r.retention != null
    ? btCard("Free-bet kept", fmtPct(r.retention), "good", "as real cash")
    : "";
  $("promoResult").innerHTML = `
    <div class="bt-verdict">
      Lay <b>$${r.lay_stake}</b> on the exchange (liability <b>$${r.liability}</b>).
      Whichever way it lands, you ${r.locked >= 0 ? "keep" : "lose"}
      <b class="${lockedCls === "good" ? "pos" : "neg"}">$${Math.abs(r.locked).toFixed(2)}</b>
      ${isFree ? "from the free bet." : "(your qualifying cost)."}
    </div>
    <div class="bt-tiles">
      ${btCard("Lay stake", "$" + r.lay_stake, "", "on the exchange")}
      ${btCard("Liability", "$" + r.liability, "", "exchange risk")}
      ${btCard("If book wins", "$" + r.profit_back.toFixed(2), r.profit_back >= 0 ? "good" : "bad")}
      ${btCard("If exchange wins", "$" + r.profit_lay.toFixed(2), r.profit_lay >= 0 ? "good" : "bad")}
      ${btCard("Locked result", "$" + r.locked.toFixed(2), lockedCls)}
      ${retention}
    </div>`;
}

$("promoRun").addEventListener("click", async () => {
  const type = $("promoType").value;
  const body = {
    bet_type: type,
    back_odds: parseFloat($("promoBack").value),
    lay_odds: parseFloat($("promoLay").value),
    back_stake: parseFloat($("promoStake").value),
    commission: Math.max(0, parseFloat($("promoComm").value) || 0) / 100,
  };
  const { data } = await postJSON("/api/promo", body);
  if (data.error) {
    $("promoResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error)}</span></div>`;
  } else {
    renderPromo(data, type === "free_snr");
  }
});

// --- pick'em entry builder ----------------------------------------------- //
let pkLegs = [{}, {}];   // start with two legs

function renderPkLegs() {
  $("pkLegs").innerHTML = pkLegs.map((lg, i) => `
    <div class="pk-leg" data-i="${i}">
      <input class="pk-label" type="text" placeholder="e.g. LeBron pts o25.5" value="${esc(lg.label || "")}" />
      <select class="pk-side">
        <option value="over" ${lg.side === "over" || !lg.side ? "selected" : ""}>Over</option>
        <option value="under" ${lg.side === "under" ? "selected" : ""}>Under</option>
      </select>
      <input class="pk-over" type="text" inputmode="numeric" placeholder="sharp over (-115)" value="${esc(lg.over_odds ?? "")}" />
      <input class="pk-under" type="text" inputmode="numeric" placeholder="sharp under (-105)" value="${esc(lg.under_odds ?? "")}" />
      <button class="pk-rm" type="button" title="remove leg">✕</button>
    </div>`).join("");
}
renderPkLegs();

function readPkLegs() {
  return [...$("pkLegs").querySelectorAll(".pk-leg")].map((row) => ({
    label: row.querySelector(".pk-label").value.trim(),
    side: row.querySelector(".pk-side").value,
    over_odds: row.querySelector(".pk-over").value.trim(),
    under_odds: row.querySelector(".pk-under").value.trim(),
  }));
}

$("pkAddLeg").addEventListener("click", () => { pkLegs = readPkLegs(); pkLegs.push({}); renderPkLegs(); });
$("pkLegs").addEventListener("click", (e) => {
  if (e.target.classList.contains("pk-rm")) {
    pkLegs = readPkLegs();
    pkLegs.splice(+e.target.closest(".pk-leg").dataset.i, 1);
    if (!pkLegs.length) pkLegs = [{}];
    renderPkLegs();
  }
});

$("pkCalc").addEventListener("click", async () => {
  const legs = readPkLegs();
  const body = { multiplier: parseFloat($("pkMult").value) || 0, legs };
  const { data } = await postJSON("/api/pickem", body);
  if (data.error && !data.legs) {
    $("pkResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error)}</span></div>`;
    return;
  }
  const e = data.entry;
  const legRows = data.legs.map((lg) =>
    `<tr><td>${esc(lg.label || "(leg)")}</td><td>${esc(lg.side)}</td><td>${lg.prob != null ? pct(lg.prob) : "—"}</td></tr>`).join("");
  if (!e) {
    $("pkResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error || "Fill in valid sharp odds for every leg.")}</span></div>`;
    return;
  }
  const evCls = e.ev > 0 ? "good" : "bad";
  $("pkResult").innerHTML = `
    <div class="bt-verdict">
      ${e.n_legs}-leg entry hits <b>${pct(e.win_prob)}</b> of the time. At <b>${e.multiplier}×</b>
      that's <b class="${e.ev > 0 ? "pos" : "neg"}">${(e.ev * 100).toFixed(1)}% EV</b>.
      ${e.ev > 0 ? "Worth playing." : `You'd need at least <b>${e.breakeven_multiplier}×</b> to break even — pass or find fatter legs.`}
    </div>
    <table class="bets-table"><thead><tr><th>Leg</th><th>Pick</th><th>True hit %</th></tr></thead><tbody>${legRows}</tbody></table>
    <div class="bt-tiles" style="margin-top:12px">
      ${btCard("Entry win %", pct(e.win_prob), "")}
      ${btCard("Payout", e.multiplier + "×", "")}
      ${btCard("EV", (e.ev * 100).toFixed(1) + "%", evCls)}
      ${btCard("Breakeven", e.breakeven_multiplier + "×", "")}
    </div>`;
});

// --- sweeps tools -------------------------------------------------------- //
$("swCheck").addEventListener("click", async () => {
  const body = {
    your_odds: $("swYour").value.trim(),
    ref_side_odds: $("swRefSide").value.trim(),
    ref_other_odds: $("swRefOther").value.trim(),
    stake: parseFloat($("swStake").value) || 100,
  };
  const { data } = await postJSON("/api/sweeps_ev", body);
  if (data.error) {
    $("swEvResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error)}</span></div>`;
    return;
  }
  const cls = data.plus_ev ? "good" : "bad";
  $("swEvResult").innerHTML = `
    <div class="bt-verdict">
      Sharp fair price says your side is <b>${pct(data.fair_prob)}</b> to win.
      Your book is <b class="${data.plus_ev ? "pos" : "neg"}">${(data.ev_pct * 100).toFixed(1)}% ${data.plus_ev ? "+EV — bet it" : "−EV — skip"}</b>
      (${data.plus_ev ? "+" : ""}$${data.expected_profit} expected on $${$("swStake").value}).
    </div>
    <div class="bt-tiles">
      ${btCard("Fair win %", pct(data.fair_prob), "")}
      ${btCard("Your implied %", pct(data.your_implied), "")}
      ${btCard("EV", (data.ev_pct * 100).toFixed(1) + "%", cls)}
    </div>`;
});

$("swBonus").addEventListener("click", async () => {
  const body = {
    sc: parseFloat($("swSc").value) || 0,
    playthrough: parseFloat($("swPlay").value) || 0,
    edge: Math.max(0, parseFloat($("swEdge").value) || 0) / 100,
  };
  const { data } = await postJSON("/api/sweeps_bonus", body);
  if (data.error) {
    $("swBonusResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error)}</span></div>`;
    return;
  }
  $("swBonusResult").innerHTML = `
    <div class="bt-verdict">${data.sc} SC is worth about <b class="pos">$${data.value}</b> in real cash
      (${pct(data.retention)} of face, after ${data.playthrough}× play-through).</div>`;
});

// Value Finder is the default tab; it needs no initial paint (button-driven).
