"use strict";
// ======================================================================== //
// Stocks section — options strategy calculator + live chain (CBOE).
// Loaded after app.js/analytics.js/crypto.js; shares $, esc, pct, postJSON, btCard.
// ======================================================================== //

// --- sub-tabs ------------------------------------------------------------ //
$("stockTabs").addEventListener("click", (e) => {
  const t = e.target.closest(".ctab");
  if (!t) return;
  [...$("stockTabs").children].forEach((c) => c.classList.toggle("active", c === t));
  ["calc", "chain", "insider"].forEach((p) => $("spanel-" + p).classList.toggle("hidden", p !== t.dataset.stab));
});

const SPREADS = ["bull_call", "bear_put", "bull_put", "bear_call"];

function syncStrategyFields() {
  const isSpread = SPREADS.includes($("ocStrategy").value);
  $("ocSingle").style.display = isSpread ? "none" : "flex";
  $("ocSpread").style.display = isSpread ? "flex" : "none";
}
$("ocStrategy").addEventListener("change", syncStrategyFields);
syncStrategyFields();

// --- strategy calculator ------------------------------------------------- //
const MONEY = new Set(["premium_income", "max_profit", "max_loss", "breakeven", "collateral",
  "capital", "capital_at_risk", "cost", "width", "effective_buy_price"]);
const PCTS = new Set(["static_return", "static_return_annualized", "if_called_return",
  "if_called_annualized", "return_if_otm", "annualized", "downside_protection",
  "discount_to_current", "prob_keep_shares", "prob_keep_premium", "prob_profit"]);
const LABELS = {
  premium_income: "Premium income", max_profit: "Max profit", max_loss: "Max loss",
  breakeven: "Breakeven", collateral: "Collateral", capital: "Capital", capital_at_risk: "At risk",
  cost: "Cost", width: "Spread width", effective_buy_price: "Effective buy price",
  static_return: "Static return", static_return_annualized: "Static (annualized)",
  if_called_return: "If-called return", if_called_annualized: "If-called (annualized)",
  return_if_otm: "Return (if OTM)", annualized: "Annualized", downside_protection: "Downside protection",
  discount_to_current: "Discount if assigned", risk_reward: "Risk / reward",
  prob_keep_shares: "P(keep shares)", prob_keep_premium: "P(keep premium)", prob_profit: "P(profit)",
};

function fmtMoney(n) { return typeof n === "number" ? "$" + n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"; }

function renderStrategy(d) {
  const tiles = [];
  for (const [k, v] of Object.entries(d)) {
    if (k === "strategy" || k.endsWith("_note") || k === "is_credit") continue;
    if (v === null || v === undefined) {
      if (k === "max_profit") tiles.push(btCard(LABELS[k] || k, "Unlimited", "good", d.max_profit_note || ""));
      continue;
    }
    const label = LABELS[k] || k.replace(/_/g, " ");
    let val, cls = "";
    if (k === "risk_reward") val = v.toFixed(2) + " : 1";
    else if (PCTS.has(k)) val = pct(v);
    else if (MONEY.has(k)) val = fmtMoney(v);
    else continue;
    if (k === "max_loss") cls = "bad";
    if (k === "max_profit" || k === "premium_income") cls = "good";
    tiles.push(btCard(label, val, cls, d[k + "_note"] || ""));
  }
  $("ocResult").innerHTML =
    `<div class="bt-verdict"><b>${esc(d.strategy)}</b>${d.max_loss_note ? ` · <span class="dim">max loss: ${esc(d.max_loss_note)}</span>` : ""}</div>
     <div class="bt-tiles">${tiles.join("")}</div>`;
}

$("ocCalc").addEventListener("click", async () => {
  const s = $("ocStrategy").value;
  const body = {
    strategy: s, premium: $("ocPremium").value, contracts: $("ocContracts").value || 1,
    days: $("ocDays").value || null, iv: $("ocIv").value ? parseFloat($("ocIv").value) / 100 : null,
  };
  if (SPREADS.includes(s)) { body.strike_a = $("ocStrikeA").value; body.strike_b = $("ocStrikeB").value; }
  else { body.stock_price = $("ocStock").value; body.strike = $("ocStrike").value; }
  const { data } = await postJSON("/api/stocks/strategy", body);
  if (data.error) { $("ocResult").innerHTML = `<div class="bt-verdict"><span class="bad">${esc(data.error)}</span></div>`; }
  else renderStrategy(data);
});

// --- options chain ------------------------------------------------------- //
let chainData = null;

function chRows(rows, price) {
  return rows.map((r) => {
    const mid = (r.bid != null && r.ask != null) ? ((r.bid + r.ask) / 2) : r.last;
    return `<tr class="${r.itm ? "ch-itm" : ""}">
      <td><b>${r.strike}</b></td>
      <td>${r.bid ?? "—"}</td><td>${r.ask ?? "—"}</td>
      <td>${r.iv != null ? (r.iv * 100).toFixed(0) + "%" : "—"}</td>
      <td>${r.delta != null ? r.delta.toFixed(2) : "—"}</td>
      <td class="dim">${r.volume ?? 0}</td><td class="dim">${r.open_interest ?? 0}</td>
      <td><button class="ch-use" data-strike="${r.strike}" data-prem="${mid != null ? mid.toFixed(2) : ""}" title="use in calculator">↗</button></td>
    </tr>`;
  }).join("");
}

function renderChain(d) {
  chainData = d;
  $("chQuote").innerHTML = `<b>${esc(d.symbol)}</b> $${d.price} · ${d.expirations.length} expirations · showing <b>${esc(d.selected_label)}</b> (near the money)`;
  const head = '<thead><tr><th>Strike</th><th>Bid</th><th>Ask</th><th>IV</th><th>Δ</th><th>Vol</th><th>OI</th><th></th></tr></thead>';
  $("chTables").innerHTML = `
    <div class="ch-col"><div class="ch-side-label pos">CALLS</div><table class="bets-table ch-table">${head}<tbody>${chRows(d.calls, d.price)}</tbody></table></div>
    <div class="ch-col"><div class="ch-side-label neg">PUTS</div><table class="bets-table ch-table">${head}<tbody>${chRows(d.puts, d.price)}</tbody></table></div>`;
}

async function loadChain(expiry) {
  const t = $("chTicker").value.trim();
  const msg = $("chMsg");
  if (!t) { msg.style.color = "var(--red)"; msg.textContent = "Enter a ticker."; return; }
  msg.style.color = "var(--muted, #8b949e)"; msg.textContent = "Loading chain…";
  const { data } = await postJSON("/api/stocks/options", { ticker: t, expiry: expiry || null });
  if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; return; }
  msg.textContent = "";
  // (re)populate expiry dropdown
  const sel = $("chExpiry");
  if (!expiry || sel.options.length === 0) {
    sel.innerHTML = data.expirations.map((e) => `<option value="${esc(e.value)}">${esc(e.label)}</option>`).join("");
  }
  sel.value = data.selected_expiry;
  renderChain(data);
}

$("chLoad").addEventListener("click", () => { $("chExpiry").innerHTML = ""; loadChain(); });
$("chExpiry").addEventListener("change", () => loadChain($("chExpiry").value));

// click ↗ on a contract -> fill calculator + jump to calc tab
$("chTables").addEventListener("click", (e) => {
  const b = e.target.closest(".ch-use");
  if (!b) return;
  $("ocStrategy").value = "covered_call"; syncStrategyFields();
  if (chainData) $("ocStock").value = chainData.price;
  $("ocStrike").value = b.dataset.strike;
  if (b.dataset.prem) $("ocPremium").value = b.dataset.prem;
  $("stockTabs").querySelector('[data-stab="calc"]').click();
  $("ocResult").scrollIntoView({ behavior: "smooth", block: "center" });
});

// --- insider buys -------------------------------------------------------- //
function insMoney(n) {
  if (typeof n !== "number") return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return "$" + (n / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return "$" + (n / 1e3).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

function renderInsider(d) {
  const s = d.summary;
  const netCls = s.net_value > 0 ? "good" : (s.net_value < 0 ? "bad" : "");
  const verdict = s.n_buys > 0
    ? `<span class="good">${s.n_buyers} insider(s) bought ${insMoney(s.buy_value)} on the open market</span> — the bullish tell. Net (buys − sells): <b>${insMoney(s.net_value)}</b>.`
    : `<span class="dim">No open-market insider buys in the recent filings.</span> Only sells/grants — which are routine, not a signal. (Sold ${insMoney(s.sell_value)}.)`;
  $("insSummary").innerHTML = `
    <div class="bt-verdict">${esc(d.company)} (${esc(d.ticker)}): ${verdict}</div>
    <div class="bt-tiles">
      ${btCard("Insider buying", insMoney(s.buy_value), s.buy_value > 0 ? "good" : "", `${s.n_buys} buy(s)`)}
      ${btCard("Insider selling", insMoney(s.sell_value), "", `${s.n_sells} sell(s)`)}
      ${btCard("Net", insMoney(s.net_value), netCls)}
      ${btCard("Distinct buyers", s.n_buyers, s.n_buyers > 0 ? "good" : "")}
    </div>`;

  const txns = d.transactions || [];
  if (!txns.length) { $("insTable").innerHTML = '<div class="empty-note">No recent Form 4 transactions found.</div>'; return; }
  const rows = txns.slice(0, 60).map((t) => {
    const badge = t.is_buy ? '<span class="ins-badge buy">BUY</span>'
      : (t.is_sell ? '<span class="ins-badge sell">SELL</span>' : `<span class="ins-badge dimb">${esc(t.label)}</span>`);
    return `<tr class="${t.is_buy ? "ins-buy-row" : ""}">
      <td class="dim">${esc(t.date)}</td><td>${badge}</td>
      <td>${esc(t.owner)} <span class="dim">${esc(t.role || "")}</span></td>
      <td>${typeof t.shares === "number" ? t.shares.toLocaleString() : "—"}</td>
      <td>${t.price != null ? "$" + t.price : "—"}</td>
      <td>${insMoney(t.value)}</td></tr>`;
  }).join("");
  $("insTable").innerHTML = '<table class="bets-table ins-table"><thead><tr><th>Date</th><th>Type</th><th>Insider</th><th>Shares</th><th>Price</th><th>Value</th></tr></thead><tbody>'
    + rows + "</tbody></table>";
}

async function loadInsider() {
  const t = $("insTicker").value.trim();
  const msg = $("insMsg");
  if (!t) { msg.style.color = "var(--red)"; msg.textContent = "Enter a ticker."; return; }
  msg.style.color = "var(--muted, #8b949e)"; msg.textContent = "Pulling SEC filings…";
  $("insSummary").innerHTML = ""; $("insTable").innerHTML = "";
  const { data } = await postJSON("/api/stocks/insider", { ticker: t });
  if (data.error) { msg.style.color = "var(--red)"; msg.textContent = data.error; return; }
  msg.textContent = "";
  renderInsider(data);
}
$("insLoad").addEventListener("click", loadInsider);
$("insTicker").addEventListener("keydown", (e) => { if (e.key === "Enter") loadInsider(); });
