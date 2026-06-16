"use strict";
// ======================================================================== //
// Crypto section — token safety checker. Loaded after app.js + analytics.js,
// so it shares $, esc, pct, postJSON, and btCard.
// ======================================================================== //

function fmtUsd(n) {
  if (typeof n !== "number" || isNaN(n)) return "—";
  if (n >= 1e9) return "$" + (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return "$" + (n / 1e3).toFixed(1) + "K";
  if (n >= 1) return "$" + n.toFixed(2);
  return "$" + n.toPrecision(3);
}

function ageFromMs(ms) {
  if (!ms) return "—";
  const h = (Date.now() - ms) / 3.6e6;
  if (h < 24) return Math.max(1, Math.round(h)) + "h";
  return Math.round(h / 24) + "d";
}

const LEVEL_LABEL = { avoid: "🚫", high: "⚠", elevated: "⚠", clear: "✓" };

function renderCryptoReport(d) {
  const f = d.flags || {}, m = d.market || {};
  const name = m.name || f.name || "Token";
  const sym = m.symbol || f.symbol || "";

  const flags = (d.red_flags || []).map((x) =>
    `<li class="rf-${x.severity}">${esc(x.msg)}</li>`).join("");
  const flagsBlock = flags
    ? `<ul class="rf-list">${flags}</ul>`
    : `<p class="chart-note">No major contract red flags detected. That does <b>not</b> make it a good buy — meme coins are gambling. Liquidity can still be pulled and prices still go to zero.</p>`;

  const notes = (d.notes || []).map((n) => `<div class="rf-note">ℹ ${esc(n)}</div>`).join("");

  $("cryptoReport").innerHTML = `
    <div class="crypto-head">
      <div class="crypto-name">${esc(name)} ${sym ? `<span class="dim">${esc(sym)}</span>` : ""}</div>
      <div class="verdict-badge verdict-${d.level}">${LEVEL_LABEL[d.level] || ""} ${esc(d.verdict)}</div>
    </div>
    ${notes}
    <div class="bt-section-label">Red flags (${(d.red_flags || []).length})</div>
    ${flagsBlock}
    <div class="bt-section-label">Market</div>
    <div class="bt-tiles">
      ${btCard("Price", fmtUsd(m.price_usd), "")}
      ${btCard("Liquidity", fmtUsd(m.liquidity), (typeof m.liquidity === "number" && m.liquidity < 10000) ? "bad" : "")}
      ${btCard("24h volume", fmtUsd(m.volume_24h), "")}
      ${btCard("FDV", fmtUsd(m.fdv), "")}
      ${btCard("Age", ageFromMs(m.pair_created_ms), "")}
      ${btCard("Top holder", typeof f.top_holder_pct === "number" ? pct(f.top_holder_pct) : "—", (typeof f.top_holder_pct === "number" && f.top_holder_pct >= 0.3) ? "bad" : "")}
    </div>
    <p class="chart-note">Sources: GoPlus Security (contract) + DexScreener (market). Always do your own research — this catches obvious traps, not every one.</p>`;
}

async function runCryptoCheck() {
  const addr = $("cryptoAddr").value.trim();
  const chain = $("cryptoChain").value;
  const msg = $("cryptoMsg"), btn = $("cryptoCheck");
  if (!addr) { msg.className = "msg err"; msg.textContent = "Paste a token address."; return; }
  msg.className = "msg"; msg.textContent = "";
  btn.disabled = true;
  $("cryptoReport").innerHTML = '<div class="report-empty"><span class="spinner"></span>Checking contract & liquidity…</div>';
  let res;
  try {
    res = await postJSON("/api/crypto/token", { address: addr, chain });
  } catch (e) {
    btn.disabled = false;
    $("cryptoReport").innerHTML = '<div class="report-empty">Request failed.</div>';
    return;
  }
  btn.disabled = false;
  const data = res.data;
  if (data.error) {
    $("cryptoReport").innerHTML = `<div class="report-empty">${esc(data.error)}</div>`;
    return;
  }
  renderCryptoReport(data);
}

$("cryptoCheck").addEventListener("click", runCryptoCheck);
$("cryptoAddr").addEventListener("keydown", (e) => { if (e.key === "Enter") runCryptoCheck(); });

// --- crypto sub-tabs (Screener / Safety Check) --------------------------- //
$("cryptoTabs").addEventListener("click", (e) => {
  const t = e.target.closest(".ctab");
  if (!t) return;
  const which = t.dataset.ctab;
  [...$("cryptoTabs").children].forEach((c) => c.classList.toggle("active", c === t));
  ["screener", "safety", "whale", "discover"].forEach((p) =>
    $("cpanel-" + p).classList.toggle("hidden", p !== which));
  if (which === "whale") initWhale();
  if (which === "discover") loadLeaderboard();
});

// shared: add a wallet to the watchlist (used by Discover + future)
async function trackWallet(address, chain, label) {
  const w = await getJSON("/api/crypto/wallets");
  const wallets = w.wallets || [];
  if (wallets.some((x) => (x.address || "").toLowerCase() === address.toLowerCase())) return "already";
  wallets.push({ address, chain, label: label || "" });
  await postJSON("/api/crypto/wallets", { wallets });
  whaleWallets = wallets;
  return "added";
}

function shortAddr(a) { return a ? a.slice(0, 6) + "…" + a.slice(-4) : "?"; }

// --- smart-wallet discovery ---------------------------------------------- //
async function loadLeaderboard() {
  try {
    const d = await getJSON("/api/crypto/leaderboard");
    renderLeaderboard(d.leaderboard || []);
  } catch (e) { /* ignore */ }
}

function lbRow(r, i) {
  const pnl = typeof r.pnl === "number" ? ` · <span class="${r.pnl >= 0 ? "pos" : "neg"}">$${r.pnl.toLocaleString()}</span>` : "";
  return `<tr>
    <td>${i + 1}</td>
    <td><a href="${esc(r.url || "#")}" target="_blank" rel="noopener">${esc(shortAddr(r.wallet))}</a> <span class="dim">${esc(r.chain || "")}</span></td>
    <td><span class="lb-count">${r.count}×</span></td>
    <td class="dim">${esc((r.tokens || []).join(", "))}${pnl}</td>
    <td><button class="lb-track" data-addr="${esc(r.wallet)}" data-chain="${esc(r.chain)}">Track</button></td>
  </tr>`;
}

function renderLeaderboard(rows) {
  const wrap = $("discLeaderboard");
  if (!rows.length) {
    wrap.innerHTML = '<div class="empty-note">Empty. Analyze a few tokens that already pumped to surface repeat early-buyers.</div>';
    return;
  }
  wrap.innerHTML = '<table class="bets-table lb-table"><thead><tr><th>#</th><th>Wallet</th><th>Winners</th><th>Tokens</th><th></th></tr></thead><tbody>'
    + rows.map(lbRow).join("") + "</tbody></table>";
}

function renderDiscoverResult(d) {
  const wrap = $("discResult");
  const ws = d.wallets || [];
  if (!ws.length) { wrap.innerHTML = '<div class="chart-note">No early buyers surfaced for this token.</div>'; return; }
  const rows = ws.map((w) => {
    const extra = typeof w.pnl === "number" ? `<span class="${w.pnl >= 0 ? "pos" : "neg"}">$${w.pnl.toLocaleString()}</span>`
      : (w.ts ? `<span class="dim">${whaleAgo(w.ts)} ago</span>` : "");
    return `<tr><td>${esc(shortAddr(w.wallet))}</td><td>${extra}</td>
      <td><button class="lb-track" data-addr="${esc(w.wallet)}" data-chain="${esc(d.chain)}">Track</button></td></tr>`;
  }).join("");
  wrap.innerHTML = `<div class="bt-section-label">Early buyers of ${esc(d.symbol || "token")} (${ws.length})</div>
    <table class="bets-table"><tbody>${rows}</tbody></table>`;
}

$("discResult").addEventListener("click", trackHandler);
$("discLeaderboard").addEventListener("click", trackHandler);
async function trackHandler(e) {
  const btn = e.target.closest(".lb-track");
  if (!btn) return;
  btn.disabled = true;
  const r = await trackWallet(btn.dataset.addr, btn.dataset.chain, "");
  btn.textContent = r === "already" ? "✓ tracking" : "✓ tracked";
  btn.classList.add("tracked");
}

$("discRun").addEventListener("click", async () => {
  const addr = $("discAddr").value.trim();
  const btn = $("discRun"), msg = $("discMsg");
  if (!addr) { msg.style.color = "var(--red)"; msg.textContent = "Enter a token address."; return; }
  btn.disabled = true; msg.style.color = "var(--muted, #8b949e)"; msg.textContent = "Scanning early buyers…";
  $("discResult").innerHTML = "";
  try {
    const { data } = await postJSON("/api/crypto/discover", { address: addr, chain: $("discChain").value });
    if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; }
    else { msg.textContent = ""; renderDiscoverResult(data); renderLeaderboard(data.leaderboard || []); }
  } catch (e) {
    msg.style.color = "var(--red)"; msg.textContent = "Discovery request failed.";
  } finally { btn.disabled = false; }
});

$("discClear").addEventListener("click", async () => {
  await postJSON("/api/crypto/leaderboard/clear", {});
  renderLeaderboard([]);
});

// --- whale tracker ------------------------------------------------------- //
let whaleWallets = [];
let whaleInit = false;

async function initWhale() {
  if (whaleInit) return;
  whaleInit = true;
  try {
    const ks = await getJSON("/api/crypto/whale_keys");
    $("whaleKeyStatus").innerHTML = `Etherscan ${ks.etherscan ? "✓" : "✗"} · Helius ${ks.helius ? "✓" : "✗"}`;
    const w = await getJSON("/api/crypto/wallets");
    whaleWallets = w.wallets || [];
    renderWhaleList();
  } catch (e) { /* ignore */ }
}

function renderWhaleList() {
  const wrap = $("whaleList");
  if (!whaleWallets.length) {
    wrap.innerHTML = '<div class="chart-note">No wallets yet. Add one above to start tracking.</div>';
    return;
  }
  wrap.innerHTML = whaleWallets.map((w, i) =>
    `<div class="whale-item"><span class="wl-chain">${esc(w.chain)}</span>
       <b>${esc(w.label || "(no label)")}</b>
       <span class="dim">${esc(w.address.slice(0, 6))}…${esc(w.address.slice(-4))}</span>
       <button class="wl-rm" data-i="${i}" title="remove">✕</button></div>`).join("");
}

async function saveWallets() {
  const { data } = await postJSON("/api/crypto/wallets", { wallets: whaleWallets });
  if (data.wallets) { whaleWallets = data.wallets; renderWhaleList(); }
}

$("whaleAdd").addEventListener("click", () => {
  const addr = $("whaleAddr").value.trim();
  if (!addr) return;
  whaleWallets.push({ address: addr, chain: $("whaleChain").value, label: $("whaleLabel").value.trim() });
  $("whaleAddr").value = ""; $("whaleLabel").value = "";
  saveWallets();
});

$("whaleList").addEventListener("click", (e) => {
  const btn = e.target.closest(".wl-rm");
  if (!btn) return;
  whaleWallets.splice(+btn.dataset.i, 1);
  saveWallets();
});

$("whaleSaveKeys").addEventListener("click", async () => {
  const body = {};
  if ($("whaleEthKey").value.trim()) body.etherscan = $("whaleEthKey").value.trim();
  if ($("whaleHelKey").value.trim()) body.helius = $("whaleHelKey").value.trim();
  const { data } = await postJSON("/api/crypto/whale_keys", body);
  $("whaleKeyStatus").innerHTML = `Etherscan ${data.etherscan ? "✓" : "✗"} · Helius ${data.helius ? "✓" : "✗"} — saved`;
  $("whaleEthKey").value = ""; $("whaleHelKey").value = "";
});

function whaleAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m";
  if (s < 86400) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

function fmtAmt(n) {
  if (typeof n !== "number") return "";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toPrecision(3).replace(/\.?0+$/, "");
}

function renderWhaleFeed(res) {
  const conv = $("whaleConvergence");
  const cv = Object.entries(res.convergence || {});
  conv.innerHTML = cv.length
    ? cv.map(([addr, c]) =>
        `<div class="conv-banner">🔥 <b>${c.count} wallets</b> bought <b>${esc(c.symbol)}</b> (${esc(c.chain)})
          <button class="scr-check conv-check" data-addr="${esc(addr)}" data-chain="${esc(c.chain)}">Check</button></div>`).join("")
    : "";

  (res.errors || []).forEach(() => {});
  const errs = (res.errors || []).length
    ? `<div class="rf-note">${res.errors.map((e) => esc((e.label || e.wallet) + ": " + e.error)).join(" · ")}</div>` : "";

  const feed = res.feed || [];
  if (!feed.length) {
    $("whaleFeed").innerHTML = errs + `<div class="empty-note">${res.note ? esc(res.note) : "No recent moves found for these wallets."}</div>`;
    return;
  }
  let html = errs + '<table class="bets-table whale-feed"><tbody>';
  for (const e of feed) {
    const dir = e.direction === "in"
      ? '<span class="pos">BUY</span>' : '<span class="neg">SELL</span>';
    html += `<tr>
      <td>${dir}</td>
      <td><b>${esc(e.token_symbol || "?")}</b> <span class="dim">${fmtAmt(e.amount)}</span></td>
      <td>${esc(e.wallet_label || e.wallet.slice(0, 6) + "…")}</td>
      <td class="dim">${esc(e.chain)}</td>
      <td class="dim">${whaleAgo(e.ts)} ago</td>
      <td><button class="scr-check conv-check" data-addr="${esc(e.token_address)}" data-chain="${esc(e.chain)}">Check</button>
          ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener" class="dim">tx↗</a>` : ""}</td>
    </tr>`;
  }
  $("whaleFeed").innerHTML = html + "</tbody></table>";
}

$("whaleFeed").addEventListener("click", whaleCheckHandler);
$("whaleConvergence").addEventListener("click", whaleCheckHandler);
async function whaleCheckHandler(e) {
  const btn = e.target.closest(".conv-check");
  if (!btn || !btn.dataset.addr) return;
  btn.disabled = true; btn.textContent = "…";
  const { data } = await postJSON("/api/crypto/token", { address: btn.dataset.addr, chain: btn.dataset.chain });
  if (data.error) { btn.replaceWith(document.createTextNode("n/a")); return; }
  const span = document.createElement("span");
  span.className = `verdict-badge verdict-${data.level}`;
  span.title = (data.red_flags || []).map((f) => f.msg).join("; ");
  span.textContent = `${LEVEL_LABEL[data.level] || ""} ${data.level}`;
  btn.replaceWith(span);
}

$("whaleRefresh").addEventListener("click", async () => {
  const btn = $("whaleRefresh"), msg = $("whaleMsg");
  btn.disabled = true; msg.style.color = "var(--muted, #8b949e)"; msg.textContent = "Pulling on-chain activity…";
  try {
    const { data } = await postJSON("/api/crypto/activity", {});
    msg.textContent = "";
    if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; }
    else renderWhaleFeed(data);
  } catch (e) {
    msg.style.color = "var(--red)"; msg.textContent = "Activity request failed.";
  } finally { btn.disabled = false; }
});

// --- trending screener --------------------------------------------------- //
let lastScreen = [];
const SEV_BADGE = { high: "rf-high", medium: "rf-medium", critical: "rf-critical" };

function fmtPctChg(x) {
  if (typeof x !== "number") return "—";
  const s = x >= 0 ? "+" : "";
  return `<span class="${x >= 0 ? "pos" : "neg"}">${s}${x.toFixed(1)}%</span>`;
}

function renderScreen(rows) {
  lastScreen = rows;
  const wrap = $("scrResults");
  if (!rows.length) {
    wrap.innerHTML = '<div class="empty-note">No tokens matched. Lower min liquidity, pick "All" chains, or try again — the trending list churns fast.</div>';
    return;
  }
  let html = '<table class="bets-table scr-table"><thead><tr>'
    + '<th>Token</th><th>Price</th><th>Liquidity</th><th>Vol 24h</th><th>24h</th><th>Age</th><th>Flags</th><th></th></tr></thead><tbody>';
  rows.forEach((r, i) => {
    const hints = (r.hints || []).map((h) =>
      `<span class="hint-badge ${h.severity}">${esc(h.msg)}</span>`).join(" ") || '<span class="dim">—</span>';
    html += `<tr data-i="${i}">
      <td><a href="${esc(r.url || "#")}" target="_blank" rel="noopener"><b>${esc(r.symbol || "?")}</b></a>
          <span class="dim">${esc(r.chain || "")}</span></td>
      <td>${fmtUsd(r.price_usd)}</td>
      <td class="${(typeof r.liquidity === "number" && r.liquidity < 10000) ? "neg" : ""}">${fmtUsd(r.liquidity)}</td>
      <td>${fmtUsd(r.volume_24h)}</td>
      <td>${fmtPctChg(r.price_change_24h)}</td>
      <td>${ageFromMs(r.pair_created_ms)}</td>
      <td>${hints}</td>
      <td><button class="scr-check" data-i="${i}">Check</button></td>
    </tr>`;
  });
  html += "</tbody></table>";
  wrap.innerHTML = html;
}

$("scrResults").addEventListener("click", async (e) => {
  const btn = e.target.closest(".scr-check");
  if (!btn) return;
  const r = lastScreen[+btn.dataset.i];
  if (!r) return;
  btn.disabled = true; btn.textContent = "…";
  const { data } = await postJSON("/api/crypto/token", { address: r.address, chain: r.chain });
  const cell = btn.parentElement;
  if (data.error) { cell.innerHTML = `<span class="dim" title="${esc(data.error)}">n/a</span>`; return; }
  cell.innerHTML = `<span class="verdict-badge verdict-${data.level}" title="${esc((data.red_flags||[]).map(f=>f.msg).join('; '))}">${LEVEL_LABEL[data.level] || ""} ${esc(data.level)}</span>`;
});

$("scrRun").addEventListener("click", async () => {
  const btn = $("scrRun"), msg = $("scrMsg");
  btn.disabled = true; msg.style.color = "var(--muted, #8b949e)"; msg.textContent = "Pulling trending tokens…";
  $("scrResults").innerHTML = "";
  const body = {
    chain: $("scrChain").value, sort: $("scrSort").value,
    min_liquidity: Math.max(0, parseFloat($("scrMinLiq").value) || 0),
  };
  try {
    const { data } = await postJSON("/api/crypto/screen", body);
    msg.textContent = "";
    if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; }
    renderScreen(data.rows || []);
  } catch (e) {
    msg.style.color = "var(--red)"; msg.textContent = "Screener request failed.";
  } finally { btn.disabled = false; }
});
