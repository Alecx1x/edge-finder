"use strict";
// ======================================================================== //
// Prediction Markets section — Polymarket (trending / movers / smart money /
// watchlist) + Kalshi lookup. Loaded after app.js, analytics.js, crypto.js,
// so it reuses $, esc, pct, getJSON, postJSON, fmtUsd, btCard, Chart.
// ======================================================================== //

const PM = { markets: {}, wlCharts: [] };

// ---- formatting helpers ---- //
function prob(p) { return (typeof p === "number") ? (p * 100).toFixed(1) + "%" : "—"; }
function ppChange(x) {
  if (typeof x !== "number" || x === 0) return '<span class="dim">·</span>';
  const v = (x * 100).toFixed(1);
  const cls = x > 0 ? "pos" : "neg";
  return `<span class="${cls}">${x > 0 ? "▲" : "▼"} ${Math.abs(v)} pp</span>`;
}
function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return Math.max(1, Math.round(s)) + "s";
  if (s < 5400) return Math.round(s / 60) + "m";
  if (s < 172800) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

// ---- market table (shared by Trending + Big Movers) ---- //
function marketRows(markets) {
  if (!markets.length) return '<p class="chart-note">No markets matched. Lower the volume filter and try again.</p>';
  const rows = markets.map((m) => {
    PM.markets[m.id] = m;
    const lead = m.lead_label && m.lead_label !== "Yes" ? ` <span class="dim">(${esc(m.lead_label)})</span>` : "";
    return `<tr>
      <td class="pm-q"><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.question)}</a>${lead}</td>
      <td class="num">${prob(m.yes_price)}</td>
      <td class="num">${ppChange(m.change24)}</td>
      <td class="num">${fmtUsd(m.volume24)}</td>
      <td class="pm-actions">
        <button class="btn ghost pm-whales" data-id="${esc(m.id)}" title="See the biggest trades on this market">🐋</button>
        <button class="btn ghost pm-track" data-id="${esc(m.id)}" title="Add to your watchlist">＋ Track</button>
      </td>
    </tr>`;
  }).join("");
  return `<table class="pm-table">
    <thead><tr><th>Market</th><th class="num">YES</th><th class="num">24h move</th><th class="num">24h vol</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function wireMarketTable(container) {
  container.addEventListener("click", async (e) => {
    const wb = e.target.closest(".pm-whales");
    const tb = e.target.closest(".pm-track");
    if (wb) { openOneMarket(wb.dataset.id); }
    if (tb) {
      const m = PM.markets[tb.dataset.id];
      if (!m) return;
      tb.disabled = true; tb.textContent = "…";
      await postJSON("/api/markets/watch", m);
      tb.textContent = "✓ Tracked";
    }
  });
}

// ---- Trending ---- //
async function loadTrending() {
  const box = $("trResults"), msg = $("trMsg");
  msg.innerHTML = '<span class="spinner"></span>Loading…';
  const minVol = $("trMinVol").value || 0;
  const d = await getJSON("/api/markets/trending?min_vol=" + encodeURIComponent(minVol));
  msg.textContent = "";
  if (d.error) { box.innerHTML = `<p class="msg err">${esc(d.error)}</p>`; return; }
  box.innerHTML = `<p class="chart-note">${esc(d.note || "")}</p>` + marketRows(d.markets || []);
}

// ---- Big movers ---- //
async function loadMovers() {
  const box = $("mvResults"), msg = $("mvMsg");
  msg.innerHTML = '<span class="spinner"></span>Loading…';
  const minVol = $("mvMinVol").value || 0;
  const d = await getJSON("/api/markets/movers?min_vol=" + encodeURIComponent(minVol));
  msg.textContent = "";
  if (d.error) { box.innerHTML = `<p class="msg err">${esc(d.error)}</p>`; return; }
  box.innerHTML = `<p class="chart-note">${esc(d.note || "")}</p>` + marketRows(d.markets || []);
}

// ---- Smart money: global big trades feed ---- //
function tradeRows(trades) {
  if (!trades.length) return '<p class="chart-note">No trades above that size in the recent window.</p>';
  const rows = trades.map((t) => {
    const sideCls = t.side === "BUY" ? "pos" : "neg";
    return `<tr>
      <td class="num"><b>${fmtUsd(t.usd)}</b></td>
      <td><span class="${sideCls}">${esc(t.side)}</span> ${esc(t.outcome || "")}</td>
      <td class="pm-q">${esc(t.title || "")}</td>
      <td><a href="https://polymarket.com/profile/${esc(t.wallet)}" target="_blank" rel="noopener" title="${esc(t.wallet)}">${esc(t.trader)}</a></td>
      <td class="num dim">${ago(t.ts)}</td>
    </tr>`;
  }).join("");
  return `<table class="pm-table">
    <thead><tr><th class="num">Size</th><th>Trade</th><th>Market</th><th>Trader</th><th class="num">Ago</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

async function loadBigTrades() {
  const box = $("btResults"), msg = $("btMsgPm");
  msg.innerHTML = '<span class="spinner"></span>Loading…';
  const minUsd = $("btMinUsd").value || 0;
  const d = await getJSON("/api/markets/big_trades?min_usd=" + encodeURIComponent(minUsd));
  msg.textContent = "";
  if (d.error) { box.innerHTML = `<p class="msg err">${esc(d.error)}</p>`; return; }
  box.innerHTML = `<p class="chart-note">${esc(d.note || "")}</p>` + tradeRows(d.trades || []);
}

// ---- Smart money: big-money wallet leaderboard ---- //
async function loadLeaderboardPM() {
  const box = $("lbResults");
  box.innerHTML = '<span class="spinner"></span>Ranking…';
  const d = await getJSON("/api/markets/leaderboard");
  if (d.error) { box.innerHTML = `<p class="msg err">${esc(d.error)}</p>`; return; }
  const ws = d.wallets || [];
  if (!ws.length) { box.innerHTML = '<p class="chart-note">No sizeable wallets in the recent window.</p>'; return; }
  const rows = ws.map((w, i) => `<tr>
    <td class="num dim">${i + 1}</td>
    <td><a href="https://polymarket.com/profile/${esc(w.wallet)}" target="_blank" rel="noopener" title="${esc(w.wallet)}">${esc(w.trader)}</a> 🔗</td>
    <td class="num"><b>${fmtUsd(w.total_usd)}</b></td>
    <td class="num dim">${w.n} trade${w.n > 1 ? "s" : ""}</td>
  </tr>`).join("");
  box.innerHTML = `<p class="chart-note">${esc(d.note || "")}</p>
    <table class="pm-table"><thead><tr><th class="num">#</th><th>Wallet</th><th class="num">Money traded</th><th class="num">Trades</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

// ---- Smart money: drill into one market's trades ---- //
async function openOneMarket(id) {
  // jump to the Smart Money tab and show this market's trade breakdown
  showMarketTab("smart");
  const card = $("oneMarketCard"), body = $("oneMarketBody");
  const m = PM.markets[id];
  $("oneMarketTitle").textContent = m ? m.question : "Market trades";
  card.classList.remove("hidden");
  body.innerHTML = '<span class="spinner"></span>Loading trades…';
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const d = await getJSON("/api/markets/trades?id=" + encodeURIComponent(id));
  if (d.error) { body.innerHTML = `<p class="msg err">${esc(d.error)}</p>`; return; }

  const leanBlock = d.lean
    ? `<div class="pm-lean"><b>Money is leaning ${esc(d.lean)}</b> — net <span class="pos">${fmtUsd(d.lean_usd)}</span> of buying pressure on that outcome in the recent window.</div>`
    : `<div class="pm-lean dim">No clear directional lean — buying and selling are roughly balanced right now.</div>`;
  const whaleBlock = d.whale
    ? `<div class="pm-whale">🐋 Whale: <a href="https://polymarket.com/profile/${esc(d.whale.wallet)}" target="_blank" rel="noopener">${esc(d.whale.trader)}</a> stacked <b>${fmtUsd(d.whale.usd)}</b> on <b>${esc(d.whale.outcome)}</b>.</div>`
    : "";
  body.innerHTML = leanBlock + whaleBlock +
    `<div class="bets-table-wrap">${tradeRows((d.trades || []).slice(0, 30))}</div>`;
}

// ---- Watchlist ---- //
async function loadWatch() {
  renderWatch(await getJSON("/api/markets/watch"));
}
function renderWatch(d) {
  PM.wlCharts.forEach((c) => { try { c.destroy(); } catch (e) {} });
  PM.wlCharts = [];
  const box = $("wlResults");
  const items = (d && d.watch) || [];
  if (!items.length) {
    box.className = "report-empty";
    box.innerHTML = "Nothing tracked yet — add markets from Trending or Big Movers.";
    return;
  }
  box.className = "";
  box.innerHTML = items.map((w, i) => {
    const tot = ppChange(w.change_total);
    const prev = w.change_since_prev != null ? ` · since last snapshot ${ppChange(w.change_since_prev)}` : "";
    return `<div class="pm-watch-card">
      <div class="pm-watch-head">
        <a href="${esc(w.url || "#")}" target="_blank" rel="noopener">${esc(w.question || w.id)}</a>
        <button class="btn ghost pm-untrack" data-id="${esc(w.id)}" title="Stop tracking">🗑</button>
      </div>
      <div class="pm-watch-meta">
        Now <b>${prob(w.last_price)}</b> · ${w.n_snapshots} snapshot${w.n_snapshots !== 1 ? "s" : ""} ·
        total drift ${tot}${prev}
      </div>
      <div class="pm-watch-spark"><canvas id="wlSpark-${i}"></canvas></div>
    </div>`;
  }).join("");

  items.forEach((w, i) => {
    const pts = (w.snapshots || []).filter((s) => s.yes_price != null);
    if (pts.length < 2) return;
    const ctx = $("wlSpark-" + i);
    if (!ctx) return;
    PM.wlCharts.push(new Chart(ctx, {
      type: "line",
      data: {
        labels: pts.map(() => ""),
        datasets: [{
          data: pts.map((s) => s.yes_price * 100),
          borderColor: "#34d399", borderWidth: 2, pointRadius: 0, tension: 0.25, fill: false,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.parsed.y.toFixed(1) + "%" } } },
        scales: { x: { display: false }, y: { ticks: { callback: (v) => v + "%", color: "#7b8190" }, grid: { color: "rgba(255,255,255,.05)" } } },
      },
    }));
  });
}

// ---- Kalshi lookup ---- //
async function loadKalshi() {
  const box = $("kalResult"), msg = $("kalMsg");
  const ticker = $("kalTicker").value.trim();
  if (!ticker) { msg.className = "hint err"; msg.textContent = "Enter a ticker."; return; }
  msg.innerHTML = '<span class="spinner"></span>Looking up…';
  const d = await getJSON("/api/markets/kalshi?ticker=" + encodeURIComponent(ticker));
  msg.textContent = "";
  if (d.error) { box.className = "report-empty"; box.innerHTML = `<span class="msg err">${esc(d.error)}</span>`; return; }
  box.className = "";
  const cents = (v) => (v == null ? "—" : v + "¢");
  box.innerHTML = `
    <div class="crypto-head">
      <div class="crypto-name">${esc(d.title || d.ticker)}${d.subtitle ? ` <span class="dim">${esc(d.subtitle)}</span>` : ""}</div>
      <div class="verdict-badge">${esc((d.status || "").toUpperCase())}</div>
    </div>
    <div class="bt-tiles">
      ${btCard("YES prob", d.yes_prob != null ? prob(d.yes_prob) : "—", "")}
      ${btCard("YES bid", cents(d.yes_bid), "")}
      ${btCard("YES ask", cents(d.yes_ask), "")}
      ${btCard("Last", cents(d.last_price), "")}
      ${btCard("Volume", typeof d.volume === "number" ? d.volume.toLocaleString() : "—", "")}
      ${btCard("Open interest", typeof d.open_interest === "number" ? d.open_interest.toLocaleString() : "—", "")}
    </div>
    <p class="chart-note">${esc(d.ticker)} · <a href="${esc(d.url)}" target="_blank" rel="noopener">open on Kalshi ↗</a>.
      Empty fields mean the market has no live two-sided quotes yet.</p>`;
}

// ---- tab switching ---- //
const MTABS = ["trending", "movers", "smart", "watch", "kalshi"];
function showMarketTab(which) {
  [...$("marketTabs").children].forEach((c) => c.classList.toggle("active", c.dataset.mtab === which));
  MTABS.forEach((p) => $("mpanel-" + p).classList.toggle("hidden", p !== which));
  if (which === "watch") loadWatch();
}
$("marketTabs").addEventListener("click", (e) => {
  const t = e.target.closest(".ctab");
  if (t) showMarketTab(t.dataset.mtab);
});

// ---- wiring ---- //
$("trRun").addEventListener("click", loadTrending);
$("mvRun").addEventListener("click", loadMovers);
$("btRunPm").addEventListener("click", loadBigTrades);
$("lbRun").addEventListener("click", loadLeaderboardPM);
$("kalRun").addEventListener("click", loadKalshi);
$("kalTicker").addEventListener("keydown", (e) => { if (e.key === "Enter") loadKalshi(); });
$("oneMarketClose").addEventListener("click", () => $("oneMarketCard").classList.add("hidden"));
$("wlSnap").addEventListener("click", async () => {
  const msg = $("wlMsg");
  msg.innerHTML = '<span class="spinner"></span>Snapshotting current prices…';
  const d = await postJSON("/api/markets/watch/snapshot", {});
  renderWatch(d.data);
  msg.textContent = `Updated ${(d.data.watch || []).length} market(s).`;
});
wireMarketTable($("trResults"));
wireMarketTable($("mvResults"));
$("wlResults").addEventListener("click", async (e) => {
  const rm = e.target.closest(".pm-untrack");
  if (!rm) return;
  renderWatch(await (await fetch("/api/markets/watch/" + encodeURIComponent(rm.dataset.id), { method: "DELETE" })).json());
});

// auto-load trending the first time the Prediction Markets section is opened
(function () {
  let loaded = false;
  $("mainNav").addEventListener("click", (e) => {
    const b = e.target.closest('[data-section="markets"]');
    if (b && !loaded) { loaded = true; loadTrending(); loadBigTrades(); }
  });
})();
