"use strict";

const BOOT = JSON.parse(document.getElementById("bootstrap").textContent);
const $ = (id) => document.getElementById(id);

// --------------------------------------------------------------------------- //
// helpers
// --------------------------------------------------------------------------- //
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const pct = (x) => (x * 100).toFixed(1) + "%";
const odds = (o) => (o > 0 ? "+" : "") + Math.round(o);
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: r.ok, data: await r.json() };
}
async function getJSON(url) {
  const r = await fetch(url);
  return await r.json();
}

// --------------------------------------------------------------------------- //
// API key card
// --------------------------------------------------------------------------- //
if (!BOOT.has_key) $("keyCard").classList.remove("hidden");

$("saveKey").addEventListener("click", async () => {
  const key = $("keyInput").value.trim();
  const msg = $("keyMsg");
  if (!key) { msg.className = "msg err"; msg.textContent = "Enter a key."; return; }
  msg.className = "msg"; msg.innerHTML = '<span class="spinner"></span>Validating…';
  const { data } = await postJSON("/api/key", { key });
  if (data.ok) {
    msg.className = "msg ok";
    msg.textContent = `Saved. ${data.remaining ?? "?"} requests remaining.`;
    setTimeout(() => $("keyCard").classList.add("hidden"), 1200);
  } else {
    msg.className = "msg err";
    msg.textContent = data.error || "Could not validate key.";
  }
});

// --------------------------------------------------------------------------- //
// History storage (Supabase + local-JSON fallback)
// --------------------------------------------------------------------------- //
function paintStorage(st) {
  const sb = st && st.mode === "supabase";
  const text = sb ? "Storage: Supabase" : "Storage: Local JSON";
  const cls = "storage-badge " + (sb ? "sb" : "json");
  $("storageTop").textContent = text;
  $("storageTop").className = cls;
  $("storageBadge").textContent = sb ? "Supabase" : "Local JSON";
  $("storageBadge").className = cls;
}
paintStorage(BOOT.storage);

$("storageToggle").addEventListener("click", () => {
  const open = $("storageBody").classList.toggle("hidden") === false;
  $("storageToggle").setAttribute("aria-expanded", String(open));
});

// prefill the URL (key is never sent back to the browser)
getJSON("/api/storage").then((st) => {
  if (st.url) $("sbUrl").value = st.url;
  paintStorage(st);
}).catch(() => {});

$("saveSupabase").addEventListener("click", async () => {
  const url = $("sbUrl").value.trim();
  const key = $("sbKey").value.trim();
  const msg = $("sbMsg");
  if (!url || !key) { msg.className = "msg err"; msg.textContent = "Enter both URL and anon key."; return; }
  msg.className = "msg"; msg.innerHTML = '<span class="spinner"></span>Connecting…';
  const { data } = await postJSON("/api/supabase", { url, key });
  msg.className = "msg " + (data.ok ? "ok" : "err");
  msg.textContent = data.message || (data.ok ? "Connected." : "Could not connect.");
  if (data.storage) paintStorage(data.storage);
});

// --------------------------------------------------------------------------- //
// top-level section nav (Sports Betting / Stocks / Crypto), responsive + collapsible
// --------------------------------------------------------------------------- //
(function () {
  const nav = $("mainNav"), toggle = $("navToggle");
  const sections = ["sports", "markets", "stocks", "crypto", "academy"];
  function show(sec) {
    sections.forEach((s) => $("section-" + s).classList.toggle("hidden", s !== sec));
    [...nav.querySelectorAll(".nav-btn")].forEach((b) =>
      b.classList.toggle("active", b.dataset.section === sec));
    nav.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }
  nav.addEventListener("click", (e) => {
    const b = e.target.closest(".nav-btn");
    if (b) show(b.dataset.section);
  });
  toggle.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });
})();

// --------------------------------------------------------------------------- //
// sport select (used by the matchup odds lookup)
// --------------------------------------------------------------------------- //
const sportSel = $("sport");
BOOT.sports.forEach((s) => {
  const o = document.createElement("option");
  o.value = s; o.textContent = s;
  sportSel.appendChild(o);
});

// --------------------------------------------------------------------------- //
// matchup odds lookup -> edge report (entry point for logging a bet)
// --------------------------------------------------------------------------- //
$("analyze").addEventListener("click", () => runAnalyze());
$("analyzeManual").addEventListener("click", () => runAnalyze({ manual: true }));
[$("nameA"), $("nameB")].forEach((el) =>
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") runAnalyze(); }));

function showManualOdds(name_a, name_b) {
  $("manualLabelA").textContent = `Odds for ${name_a}`;
  $("manualLabelB").textContent = `Odds for ${name_b}`;
  $("manualOdds").classList.remove("hidden");
}

async function runAnalyze(opts = {}) {
  const sport = sportSel.value;
  const name_a = $("nameA").value.trim();
  const name_b = $("nameB").value.trim();
  const msg = $("analyzeMsg");
  const btn = opts.manual ? $("analyzeManual") : $("analyze");

  if (!name_a || !name_b) { msg.className = "msg err"; msg.textContent = "Both names required."; return; }

  const body = { sport, name_a, name_b };
  if (opts.manual) {
    const oa = $("manualOddsA").value.trim();
    const ob = $("manualOddsB").value.trim();
    if (!oa || !ob) { msg.className = "msg err"; msg.textContent = "Enter odds for both sides."; return; }
    body.odds_a = oa; body.odds_b = ob;
  } else {
    // a fresh auto search — hide any manual panel from a previous miss
    $("manualOdds").classList.add("hidden");
  }

  msg.className = "msg"; msg.textContent = "";
  btn.disabled = true;
  $("report").innerHTML = '<div class="report-empty"><span class="spinner"></span>Fetching odds & gathering data…</div>';

  const { data } = await postJSON("/api/analyze", body);
  btn.disabled = false;

  if (data.need_manual_odds) {
    msg.className = "msg"; msg.textContent = data.message || "Enter odds manually to continue.";
    showManualOdds(data.name_a, data.name_b);
    $("report").innerHTML = '<div class="report-empty">No odds found automatically — enter them above to analyze available stats.</div>';
    return;
  }
  if (data.error) {
    msg.className = "msg err"; msg.textContent = data.error;
    if (data.need_key) $("keyCard").classList.remove("hidden");
    $("report").innerHTML = '<div class="report-empty">No report — see message above.</div>';
    return;
  }
  msg.className = "msg ok";
  msg.textContent = data.odds_source ? `Odds via ${data.odds_source}.` : "";
  renderReport(data.report);
  onAnalysis(data.report);
  if (data.report.quota && data.report.quota.remaining != null) {
    $("quota").textContent = `Odds API quota remaining: ${data.report.quota.remaining}`;
  }
}

// --------------------------------------------------------------------------- //
// render report
// --------------------------------------------------------------------------- //
function edgeCell(edge) {
  const v = (edge * 100).toFixed(1);
  const cls = edge >= 0.02 ? "pos" : edge <= -0.02 ? "neg" : "dim";
  return `<span class="${cls}">${edge >= 0 ? "+" : ""}${v} pts</span>`;
}

function renderReport(rep) {
  const m = rep.matchup, a = m.a, b = m.b;
  const meta = [esc(m.league), `${m.bookmaker_count || 0} books`, m.commence_time ? esc(m.commence_time) : null]
    .filter(Boolean).join("  ·  ");

  let html = `
    <div class="matchup-head">
      <div class="vs">${esc(a.name)}<span class="v">vs</span>${esc(b.name)}</div>
      <div class="meta">${esc(rep.sport)}  ·  ${meta}</div>
    </div>

    <table>
      <thead><tr>
        <th>Side</th><th class="num">Odds</th><th class="num">Implied</th>
        <th class="num">Model</th><th class="num">Edge</th>
      </tr></thead>
      <tbody>
        ${["a", "b"].map((s) => `
          <tr>
            <td>${esc(rep.matchup[s].name)}</td>
            <td class="num">${odds(rep.matchup[s].odds)}</td>
            <td class="num">${pct(rep.implied[s])}</td>
            <td class="num">${pct(rep.model[s])}</td>
            <td class="num">${edgeCell(rep.edge[s])}</td>
          </tr>`).join("")}
      </tbody>
    </table>
    ${recBlock(rep)}`;

  $("report").innerHTML = html;
}

function recBlock(rep) {
  const rec = rep.recommendation;
  const tier = rec.tier;
  const label = rec.bet
    ? `<span class="label c-${tier}">BET ${esc(rec.name)}</span><span class="edge c-${tier}">+${(rec.edge * 100).toFixed(1)} pts edge</span>`
    : `<span class="label dim">PASS — no actionable edge vs the market</span>`;

  const warn = `<div class="warn">ℹ This per-fight model rarely beats the closing line (see the Backtest tab). Use it to fetch odds and log bets; trust the <b>Value Finder</b> + <b>Beat the Close</b> tabs for real edge.</div>`;

  return `
    <div class="rec tier-${tier}">
      ${label}
      ${warn}
    </div>
    ${sparkBlock(rep)}
    <div class="logbet-row">
      <button id="logBet" class="btn" type="button">＋ Log This Bet</button>
      <span id="logBetMsg" class="hint"></span>
    </div>`;
}

// edge-score sparkline across successive analysis runs of this matchup
function sparkBlock(rep) {
  const pts = (rep.edge_history && rep.edge_history.points) || [];
  if (!pts.length) return "";
  return `<div class="edge-spark">
    <span class="spark-label">Edge history</span>
    <div class="spark-canvas"><canvas id="edgeSpark"></canvas></div>
    <span class="spark-runs">${pts.length} run${pts.length > 1 ? "s" : ""}</span>
  </div>`;
}
