# Edge Finder — Local Prediction-Market Edge Tool

A **local web app** that compares your own weighted model against live
sportsbook odds to surface betting **edges**. Supports **MMA, Basketball,
Soccer, Tennis**.

You type two fighters/teams in the browser → it pulls current market odds (The
Odds API) → scrapes free public stats per variable → runs a weighted scoring
model → renders an edge report in the page.

## Quick start

```bash
cd edge-finder
pip install -r requirements.txt        # flask, requests, python-dotenv, rich
python main.py
```

`python main.py` starts a local Flask server (127.0.0.1) and **auto-opens a
browser tab**. On first run the page shows a setup card for your **free Odds API
key** (https://the-odds-api.com/, 500 req/month), saved locally to `.env`.
Default weights are written to `config.json`.

> **UI note (current):** the app has been refocused around the **History &
> Analytics** tabs — Backtest, Auto-Tune, Value Finder, Beat the Close, Bet Log —
> which are the main view. The old fixed *Upcoming Events* sidebar and the manual
> *Variable Weights* sliders / presets / advanced-stats panel were removed from the
> UI (Auto-Tune replaced hand-tuning; weights now come from `config.json` /
> Auto-Tune's "Apply"). A compact **Look up odds & log a bet** card + Kelly remain
> on top. The corresponding backend routes (`/api/events`, `/api/presets`,
> `/api/weights`) still exist but are no longer surfaced. Sections below that
> describe the sliders/presets/events browser are retained for reference but no
> longer reflect the live UI.

## Architecture

A thin Flask layer (`main.py`) wraps the unchanged scoring/data/odds/config
logic and serves a single-page UI:

| Route | Purpose |
|---|---|
| `GET /` | the web UI (`templates/index.html`) |
| `GET /api/status` | key status, sports, variables, current weights |
| `POST /api/key` | validate + save Odds API key to `.env` |
| `POST /api/weights` | live-edit multipliers (auto-saved to `config.json`) |
| `POST /api/analyze` | run a matchup → JSON edge report |
| `GET /api/events` | cached upcoming-events tree for the sidebar browser |
| `POST /api/events/refresh` | force-rebuild the event cache (manual refresh button) |

The frontend (`static/app.js`, `static/style.css`) renders the matchup, odds,
implied/model probabilities, edge, per-variable breakdown, and BET/PASS
recommendation. All scoring math stays server-side in the modules below.

Offline demo of the scoring/terminal renderer (no key, synthetic matchup):
`python selftest.py`

## The 7 scoring variables

| Variable | What it measures | MMA source | Other sports |
|---|---|---|---|
| Recent Form & Streaks | last-5 W/L + streak | ✅ ufcstats.com | ✅ ESPN (Basketball) |
| Injury & Health | layoff + status flags | ✅ tapology.com | ✅ ESPN (Basketball) |
| Head-to-Head History | prior meetings | ✅ ufcstats.com | ⚠ fallback |
| Travel / Schedule Fatigue | home vs away | ✅ structural | ✅ structural |
| Weather (Soccer/Tennis only) | conditions at venue | n/a | ⚠ fallback |
| Public % vs Sharp Money | tickets% vs money% | ✅ ActionNetwork | ⚠ needs history |
| Social Sentiment / Hype | headline tone | ✅ Google News RSS | ⚠ fallback |

### MMA data sources (`mma_sources.py`)
All free, no API keys:
- **ufcstats.com** (form + H2H) — the site is behind a SHA-256 JS proof-of-work
  wall; the client solves it in `hashlib`, caches the cookie, then parses each
  fighter's fight-history table. UFCStats only lists UFC fighters, so regional
  bouts degrade gracefully.
- **tapology.com** (injury/health) — resolves the fighter (clean-slug tie-break
  for duplicate names), reads days since last fight as a ring-rust/health proxy,
  and scans recent page text for injury keywords.
- **ActionNetwork** free public JSON (`/web/v2/scoreboard/ufc`) — ticket% (public)
  vs money% (sharp) per side. Populates as books post numbers near fight night;
  otherwise reports "no public betting data posted."
- **Google News RSS** (sentiment) — scores positive/negative headline ratio from
  a built-in lexicon. No paid API.

Fuzzy name matching throughout, so partial inputs ("Makhachev", "Jon Jones")
resolve. Names are **accent-folded** first (NFKD transliteration: á→a, č→c, ř→r,
ł→l), so "Prochazka" matches "Jiří Procházka" and Eastern-European fighters
resolve without the diacritics. Every source is wrapped in try/except and returns
a per-variable reason instead of crashing when unreachable.

### MMA odds: all promotions + manual fallback
The Odds API feed is queried across the **entire Mixed-Martial-Arts group**, not
UFC alone. When a matchup isn't on the API (regional shows, Oktagon, KSW, ONE,
PFL, speculative bouts), the app **scrapes BestFightOdds.com** (`bestfightodds.py`)
for the opening moneyline across promotions. If *no* odds source has the bout,
the UI reveals **manual odds entry** — type the moneyline for each side and the
analysis still runs on whatever stat data is available. The run is never blocked:
partial data with manual odds beats a hard error.

### Sport-specific advanced stats (collapsible per-sport panel)
Selecting a sport reveals a **collapsible panel** of extra variables unique to it,
each with its own 0.0–2.0 multiplier feeding the same scoring engine:

| Sport | Variables | Source | Status |
|---|---|---|---|
| MMA | Sig. strikes/min · strike acc. % · TD attempts · TD acc. % · TD def. % · sub attempts | ufcstats.com career stats | ✅ real |
| Tennis | Surface win % (tournament surface) · aces/match · break-point conversion % | Jeff Sackmann `tennis_atp` CSVs | ✅ real |
| Basketball | Pace differential · days rest | basketball-reference.com · ESPN schedule | ✅ real |
| Basketball | Last-10 ATS record | needs closing-spread history | ⚠ honest n/a |
| Soccer | xG for/against (last 5) · press intensity | fbref.com | ⚠ fbref Cloudflare-gated → graceful n/a |

- **ufcstats.com** — all six MMA stats are parsed off the fighter page already
  fetched for form/H2H (SLpM, Str. Acc., TD Avg./Acc./Def., Sub. Avg.); takedown
  *attempts* are derived as landed ÷ accuracy.
- **Jeff Sackmann `tennis_atp`** — raw GitHub match CSVs (rolling recent seasons);
  surface is inferred from the tournament name in the odds feed (clay/grass/hard).
- **basketball-reference.com** — team Pace from the season "advanced" table;
  **ESPN** schedule gives days rest before the next game.
- ATS and the soccer stats degrade gracefully with a clear reason where no stable
  key-free source exists, rather than fabricating numbers.

Each variable (core or sport-specific) has a **multiplier 0.0–2.0** (default 1.0),
editable live in-app and persisted to `config.json`.

### Upcoming-events browser (startup cache)
On boot, `event_cache.py` builds `events_cache.json` — a Sport → League → Event
card → Matchups tree of upcoming bouts/games across all four sports. The browser
sidebar ("Upcoming Events") renders it as a fully collapsible tree; clicking any
matchup auto-fills Name A, Name B, and Sport. Event cards show their date, and
cards more than 7 days out are hidden behind a **"show future events"** toggle
(shown greyed when revealed).

The cache refreshes automatically every **24 hours** (and never re-fetches while
under 24h old); a **⟳** button forces an immediate rebuild. Building is
essentially free: the primary source is The Odds API **`/events`** endpoint,
which doesn't count against the request quota and lists every upcoming event for
each active league in a sport group (all MMA promotions the API carries, NBA/WNBA,
in-season soccer leagues, active ATP/WTA tournaments). Tapology (extra MMA
promotions) and atptour.com (ATP/WTA schedule) are attempted as supplements but
degrade gracefully — Tapology's event pages are bot-walled and atptour renders
client-side, so when unreadable the cache records an honest note rather than
inventing matchups. The browser only *populates the form*; clicking **Find Edge**
still runs the full live scraper pipeline.

### History & Analytics
A tabbed **History & Analytics** panel under the edge report adds five
locally-stored tracking features (all data in JSON files alongside `config.json`;
charts drawn with a vendored Chart.js — no CDN, works offline):

1. **Odds movement tracker** — every Find Edge run appends a timestamped odds
   snapshot to `odds_history.json`. The *Odds Movement* tab line-charts both
   sides over time; points turn amber when a line moved **toward** a side while
   public ticket % stayed light on it — a sharp-money flag (public % comes from
   the existing ActionNetwork variable, when posted).
2. **Bet tracker / results log** — a **Log This Bet** button under every report
   saves the matchup, side, odds, edge, model probability and timestamp to
   `bets_log.json`. The *Bet Log* tab shows a sortable table; mark each bet
   **W / L / P** once the event settles.
3. **Edge-score history** — each run also appends the edge score to
   `matchup_history.json` keyed by the two names; a **sparkline** in the report
   shows how the edge has drifted across runs as the event approaches.
4. **Kelly Criterion calculator** — below the report, full & half Kelly stake
   fractions from the model probability + current odds, multiplied by a
   **bankroll** (saved to `config.json`) for dollar amounts. Shows a red warning
   and zero stake when the edge is negative.
5. **Calibration dashboard** — the *Calibration* tab buckets logged bets by
   predicted probability (50-60 / 60-70 / 70-80 / 80%+) and bar-charts predicted
   vs **actual** win rate per bucket. Unlocks at 10 logged bets; below that it
   shows a "need more data" count.

These are pure bookkeeping on top of the pipeline — clicking **Find Edge** still
runs the full live scraper + scoring path; the analytics layer only records and
visualizes its outputs.

### Backtesting (the "is there any edge?" tab)
The **Backtest** tab replays thousands of past UFC fights through the *unchanged*
scoring engine with your current weights, to answer two honest questions instead
of asking you to trust slider intuition:

1. **Prediction quality** — over *every* fight: is the model's probability any
   good, and does it beat just trusting the closing line? (**Brier**, **log loss**
   and a **calibration** chart, model vs. market.)
2. **Betting result** — over fights whose edge clears a threshold: would actually
   placing those bets have made money? (**ROI** flat + half-Kelly, win rate, an
   **equity curve**), with an "always bet the favourite" baseline for context.

Data comes from a lookahead-clean public dataset (`data/ufc-master.csv`, the
Ultimate UFC Dataset) loaded by `backtest_data.py`. Two signals are reconstructed
**point-in-time** so no future information leaks in: `recent_form` (from the
dataset's pre-fight streak/record columns) and **`elo`** — a strength rating
computed here by replaying results in date order, so by construction it only ever
uses earlier fights. Every other variable (the `mma_*` career stats, injuries,
line movement, sentiment) is *current-only* and would be cheating to use on a past
fight, so the loader leaves it unavailable and the engine ignores it. There is no
train/test split because the weights aren't fit to this data — the evaluation is
out-of-sample by construction. (`metrics.py` holds the shared scoring math, also
reused by the live calibration dashboard.)

Run it from the terminal without the UI:
`python backtest_engine.py --csv data/ufc-master.csv --edge 0.02`
Tests: `python test_backtest.py` (settlement math, metric extremes, the
no-lookahead honesty check, and the `/api/backtest` route).

### Auto-Tune (walk-forward — the slider replacement)
The **Auto-Tune** tab (`optimizer.py`) stops the slider-guessing: it grid-searches
the `elo` + `recent_form` weights for the best objective (profit ROI, or
prediction accuracy) — but **walk-forward**, so it can't cheat. It tunes only on
an earlier "train" slice of history, then grades those weights on a later "test"
slice it never saw. The test number is the trustworthy one; a large train→test
drop is **overfitting** made visible. An "Apply these weights" button writes the
result to `config.json` (via `/api/weights`), closing the loop so the model is
set by evidence instead of intuition.

Honest finding on the current signals: optimizing for prediction accuracy drives
both signal weights to **0** (i.e. "trust the closing line, bet nothing"), and the
best ROI weights found in-sample still lose out-of-sample — because the market has
already priced Elo and form. The lesson the tool teaches: real edge requires a
signal the closing line *doesn't* already contain. CLI:
`python optimizer.py --objective roi --train 0.7` (or `--objective log_loss`).

### Value Finder (+EV scanner — the real edge)
The **Value Finder** tab (`value_scanner.py`) chases the sustainable edge: not
out-predicting the market, but finding a book that **overpays relative to the
sharp line**. It reuses `odds_fetcher` to pull the live board but keeps *every*
book's price (the base fetcher averages them — exactly what must not happen here),
de-vigs **Pinnacle** to a fair probability, and flags any other book whose price
clears `EV% = fair_prob × decimal − 1 ≥ threshold`. When Pinnacle isn't in the
results it falls back to a de-vigged market consensus (a weaker reference, and the
UI says so).

Limit-avoidance is built in, because beating a book gets you limited: suggested
stakes are **conservative round numbers** (quarter-Kelly, capped at 2% of
bankroll), books are tagged **sharp** (tolerate winners) vs **soft** (limit fast),
and edges above ~8% are flagged **⚠ verify** (usually a stale/void-risk line).

Pinnacle lives in the Odds API **`eu`** region, so the default scan regions are
`us,eu`. **Cost note:** Odds API charges per region per league call, so `us,eu`
is ~2 credits per league — the free tier's 500/month disappears fast, so scan
deliberately. CLI: `python value_scanner.py MMA --min-ev 0.02 --regions us,eu`.
Tests are fully synthetic (`python test_value.py`) — they mock the network and
spend **zero** quota.

### Beat the Close (closing-line-value tracking)
The **Beat the Close** tab is the truest test of whether you're actually sharp —
more reliable than win/loss, which is mostly luck in small samples. After you log
a bet (Bet Log tab), record what it **closed** at here; the app computes:

- **CLV%** — how much better your price was than the close (decimal basis). >0 =
  you "beat the close".
- **EV vs close** — the bet's expected value judged by the de-vigged closing line
  (needs both sides' closing odds).
- A **beat-close rate** + verdict: consistently beating the close is the green
  light to scale stakes / consider paid tools; consistently losing to it means
  the value isn't real — don't scale.

Capture is **manual (free)** — type the closing odds — or **Auto**, which pulls
the current line via `odds_fetcher.find_matchup` (costs 1 request; use near event
start). CLV math lives in `metrics.clv_metrics` / `clv_summary`; storage in
`history_store.set_bet_close` / `clv()` (bet records gain `clv_pct`, `ev_vs_close`,
`beat`, `close_odds`, etc.; Supabase users run the `alter table` block in
`supabase_schema.sql`). Tests: `python test_clv.py` (redirects the bet log to a
temp file and mocks auto-capture — never touches real data or quota).

### One-click "Track" (Value Finder → Bet Log)
Each Value Finder row has a **＋ Track** button that logs the pick straight to the
Bet Log (no re-typing), recording the bet-time fair probability for cleaner CLV
later. `value_scanner` opportunities now carry `opponent` / `opponent_price` so
the logged bet has both sides.

### Arbitrage scanner (`arb_scanner.py`, Arbitrage tab)
Takes the **best price each book offers on every outcome**; if their implied
probabilities sum to under 100%, staking all sides locks a profit regardless of
result. Returns the per-leg stake split (so every outcome returns the same),
profit %, and guaranteed return. Reuses the value-scanner board helpers; same
`us,eu` regions + quota cost. Honest caveats surfaced in the UI: arbs are thin,
brief, need multi-book balances, and limit you fastest. CLI:
`python arb_scanner.py MMA --stake 100`. Tests: `python test_arb.py` (synthetic).

### Matched-betting calculator (`promo_calc.py`, Matched Betting tab)
Pure money-math (no API) for converting free bets / bonuses into near-guaranteed
cash: back at the book, lay on an exchange. `matched_bet(back_odds, lay_odds,
commission, back_stake, bet_type)` handles **qualifying** and **free_snr** (free
bet, stake not returned) and returns the optimal lay stake, liability, both
outcomes, the locked result, and free-bet retention %. Decimal odds. CLI:
`python promo_calc.py 5.0 5.2 --type free_snr --stake 10`. Tests: `python test_promo.py`.

### Pick'em / DFS +EV (`pickem_calc.py`, Pick'em tab)
For player-prop pick'em apps (DraftKings Pick6, Betr, PrizePicks-style) that pay a
fixed multiplier when all legs hit. For each leg you enter the same prop's **sharp
over/under odds**; `leg_prob` de-vigs them to the leg's true hit chance, and
`entry_ev(probs, multiplier)` gives the entry's win probability, EV, and breakeven
multiplier (power-play / all-must-hit). The lesson it makes obvious: coin-flip legs
lose to the app's multiplier — you only win by stacking legs that each beat the
sharp line. `/api/pickem`. Tests: `python test_pickem.py`.

### Sweeps tools (`sweeps_calc.py`, Sweeps tab)
For sweepstakes / social books (Fliff, Rebet, Thrillz, Dogg House, Courtside,
Bracco) that no odds feed carries. Two manual calculators: **manual_ev** (your
book's line vs a sharp two-way line → fair prob + EV%) and **bonus_value**
(Sweeps-Coins bonus → estimated real-cash value after play-through). `/api/sweeps_ev`,
`/api/sweeps_bonus`. Tests: `python test_sweeps.py`.

> **Note on book coverage:** The Odds API (used by Value Finder / Arbitrage) covers
> traditional licensed books. Pick'em apps and most sweeps/social books are **not**
> in that feed, so those two tabs are manual-entry calculators rather than live
> scanners — you supply the sharp reference line, they do the +EV math.

## Money Lab sections (Sports / Stocks / Crypto / Academy)
The app is now "Money Lab" with a responsive top nav switching between domains.
Everything above lives under **Sports Betting**.

### 🎓 Academy — curated learning library (`academy.py`, Academy nav)
A vetted, link-verified resource library covering the whole industry — **10 courses,
69 resources** (Foundations · Betting Markets · Finding Edges · Bankroll & Risk ·
Prediction Markets & Forecasting · Stocks & Options · Crypto · Quant & Modeling ·
Psychology & Discipline · Legal/Tax/Responsible). Each course maps to the matching
Money Lab tools, with honest flags on marketing-adjacent sources (nothing sells
picks or guaranteed profit). `academy.py` is the single source of truth — it serves
the data at `/api/academy` (rendered by `static/academy.js`) **and** generates a
portable Markdown copy: run `python academy.py` to (re)write `academy/*.md`
(a README index + one file per course) you can read on a phone or print.

### Stocks — Options Strategy Calculator (`options_calc.py`, Stocks › Strategy Calculator)
The popular Robinhood plays with honest numbers: covered call, cash-secured put,
long call/put, and the four verticals (bull-call/bear-put debits, bull-put/bear-call
credits). Each returns max profit, max loss, breakeven(s), return on capital,
annualized return, and a rough probability of profit (lognormal from IV + days to
expiry). Pure math. `/api/stocks/strategy`. Tests: `python test_options.py`.

### Stocks — Options Chain (`stock_data.py`, Stocks › Options Chain)
Live (delayed) data, key-less: **quote** via Yahoo's v8 chart endpoint, **option
chain** via **CBOE's free delayed-quotes JSON** (`cdn.cboe.com` — no auth, includes
IV + full greeks; the OCC contract symbol is parsed for expiry/type/strike, then
trimmed near the money). Click a contract's ↗ to autofill the calculator.
`/api/stocks/quote`, `/api/stocks/options`. (Yahoo's v7 options endpoint now needs
auth, so options come from CBOE.) Tests: `python test_stockdata.py`.

### Stocks — Insider Buys (`insider.py`, Stocks › Insider Buys)
The stock market's "smart money": when a company's own executives/directors buy
their stock on the **open market** (SEC Form 4, transaction code **P**), it's a
genuine bullish tell. Sells and grants are routine noise, so they're scored
separately. Free SEC EDGAR data (no key — SEC just wants a descriptive
User-Agent): ticker → CIK (`company_tickers.json`) → recent Form 4 filings
(submissions API) → each filing's full-submission `.txt` → the `<ownershipDocument>`
XML is parsed for owner, role, code, shares, price. Returns a transaction table
plus a summary (net insider buying, # distinct buyers). `/api/stocks/insider`.
Validated live against NVDA. Tests: `python test_insider.py`.

### Crypto — Token Safety Check (`crypto_safety.py`, Crypto tab)
Defense-first tooling for meme coins (mostly traps). Paste a token contract
address + chain (Solana default; also Ethereum/Base/BSC/Arbitrum/Polygon) and it
returns a risk report — honeypot / can't-sell, buy/sell tax, mint authority,
freeze authority (Solana), owner-reclaim, hidden owner, pausable transfers,
top-holder concentration, liquidity, age → a verdict (avoid / high / elevated /
clear) plus the red-flags list. Free, key-less data: **GoPlus Security**
(`token_security` EVM + `solana/token_security`) for contract risk and
**DexScreener** for price/liquidity/volume/age. `/api/crypto/token`. It flags
obvious traps; it does **not** endorse buys (nothing can). Tests: `python
test_crypto.py` (synthetic; live path validated against BONK/PEPE).

### Crypto — Trending Screener (`crypto_screener.py`, Crypto › Screener tab)
The offense tool that pairs with the safety check. Pulls tokens being actively
promoted (DexScreener "boosts") and batches their market data into a sortable
table: price, liquidity, 24h volume, 24h change, age — plus **free inline risk
hints** (no/low liquidity, brand new, heavy sell pressure). Filter by chain + min
liquidity; **each row has a one-click Check** that runs the full `crypto_safety`
report inline. Two DexScreener calls per scan, no key/quota. `/api/crypto/screen`.
Honest framing: trending ≠ good — most are pump-and-dumps; the screener helps you
see and vet them fast, not trust them. Tests: `python test_screener.py` (synthetic;
live path validated against DexScreener).

### Crypto — Whale Tracker (`whale_tracker.py`, Crypto › Whale Tracker tab)
Follow wallets that are early and right. Keep a watchlist of wallet addresses
(persisted in `config.json` `whale_wallets`); the tracker pulls each wallet's
recent token transfers and shows a unified, time-sorted feed of **BUY** (token in)
vs **SELL** (token out), and flags **convergence** — when ≥2 watched wallets bought
the same token within 72h (the strongest tell). Each token gets a one-click safety
**Check** inline. Free, key-based data: **Etherscan v2** (one key for EVM —
ETH/Base/BSC/Arbitrum/Polygon/Optimism, `account&action=tokentx`) and **Helius**
(Solana, parsed transactions); keys saved to `.env`. Routes: `/api/crypto/wallets`
(watchlist), `/api/crypto/whale_keys`, `/api/crypto/activity`. Honest limit: it
**follows** wallets you pick — it doesn't yet **find** smart wallets for you (that
needs historical per-wallet P&L, a future build). Tests: `python test_whale.py`.

### Crypto — Smart-Wallet Discovery (`smart_wallets.py`, Crypto › Discover tab)
Finds candidate smart wallets by the **"early buyer of winners"** method (free,
robust — true P&L ranking needs a paid price-history API). Point it at a token
that already pumped: DexScreener gives the token's pool (`pairAddress`), Etherscan
`tokentx` (ascending) surfaces the wallets that bought **from the pool early**
(an infra/router denylist filters out pools/routers/dead addresses). A persistent
cross-token tally (`smart_wallets.json`) ranks wallets by **how many analyzed
winners they were early on** — the real signal, since one token is luck. Each
wallet has a **Track** button that adds it to the Whale Tracker watchlist. Solana
is best-effort via GMGN "top traders" (P&L-ranked but unofficial/fragile). EVM
needs the free Etherscan key. Routes: `/api/crypto/discover`,
`/api/crypto/leaderboard` (+`/clear`). Honest limit: a heuristic, not per-trade
P&L. Tests: `python test_discover.py`.

### Storage: Supabase with local-JSON fallback
History & Analytics data can live in **Supabase** instead of local JSON. The
storage layer (`history_store.py`) dispatches per call:

- **Supabase configured & reachable** → rows go to the `odds_history`,
  `bets_log`, and `matchup_history` tables via the PostgREST REST API
  (`supabase_store.py`), using your project URL + anon key.
- **Otherwise** → the original local JSON files, so everything keeps working
  offline. A failed Supabase call also drops to JSON for the rest of the session.

**Setup (one time):** the anon key can only read/write rows — it can't create
tables — so run **`supabase_schema.sql`** once in your Supabase project's SQL
editor (Dashboard → SQL Editor → paste → Run). It creates the three tables with
permissive RLS policies for the `anon` role. Then open the **History Storage**
card in the app, paste your **project URL** and **anon key** (saved to `.env`
next to the Odds API key), and click *Save & connect* — the app probes the
connection and the badge flips to **Supabase**. The table schemas mirror the JSON
shapes 1:1 (`odds_history` also carries optional `public_a`/`public_b` so the
sharp-money indicator keeps working; drop those columns for the strict minimal
schema).

### Weight presets
A **Presets** dropdown above the sliders loads predefined weight configurations.
Selecting one instantly resets every weight to 1.0 and applies the preset's
values (a preset is a complete config, so results are reproducible). Six built-in
**defaults** (`presets.py`, `is_default=true`) ship and cannot be deleted:

| Sport | Presets |
|---|---|
| MMA | Grappling Matters · Strikers Edge |
| Basketball | Sharp Money · Fatigue Finder |
| Tennis | Surface Specialist |
| Soccer | Value Hunter |

The preset values are defined with the app's internal variable keys (the spec's
human names are translated — e.g. `h2h_history`→`head_to_head`,
`takedown_defense`→`mma_td_def`, `public_vs_sharp`→`line_movement`,
`surface_win_pct`→`tennis_surface`). Choosing a sport in the matchup form
**auto-selects that sport's first default**. **Save…** names the current weights
and a sport tag as a custom preset; customs appear under "My Presets" with a
delete button. Presets live in the Supabase `presets` table when connected (the
six defaults are seeded there on first connect), else in a local `presets.json`.

### Honesty about data sources
Reliably auto-resolving *arbitrary typed names* to records from free sources
isn't possible for every league. Where a stable, key-free endpoint exists
(ESPN public JSON for form & injuries) the tool uses **real data**; elsewhere it
degrades gracefully with a clear reason instead of fabricating numbers. The
scoring engine only lets *available* signals move the model off the market line,
so a low-coverage run simply reports a small/zero edge — by design. The scraper
layer (`data_scrapers.py`) is modular: add a league/source by dropping in one
function.

## How the edge is computed

```
market odds → implied prob → de-vig → fair market prob
per-variable scores (0–100) × weights → signal composite → signal prob
model prob = (1 − coverage)·market + coverage·signal      # coverage = weight of live data
edge = model prob − market prob → confidence tier + driving variables
```

Confidence tiers (Low / Medium / High / Strong) scale with both edge size and
how much live data backed it. Output shows matchup, odds, implied %, model %,
edge in points, the per-variable breakdown, and a **BET / PASS** recommendation
with the variables driving it.

## Files

| File | Role |
|---|---|
| `main.py` | Flask server: routes, browser launch (the display layer) |
| `templates/index.html` | web UI markup |
| `static/style.css`, `static/app.js` | web UI styling + logic |
| `odds_fetcher.py` | The Odds API: find event by name across the whole sport group, consensus odds |
| `bestfightodds.py` | MMA odds fallback — scrapes BestFightOdds for non-UFC promotions |
| `event_cache.py` | startup event cache (`events_cache.json`): upcoming matchups tree, 24h refresh |
| `history_store.py` | History storage dispatcher: Supabase when configured, else local JSON; calibration math |
| `supabase_store.py` | thin Supabase/PostgREST client (anon-key row CRUD) |
| `presets.py` | weight presets: built-in defaults + custom CRUD (Supabase or local presets.json) |
| `supabase_schema.sql` | one-time table + RLS migration to paste into the Supabase SQL editor |
| `static/analytics.js` | History & Analytics UI: Chart.js graphs, Kelly calc, bet log, calibration |
| `static/chart.umd.min.js` | vendored Chart.js (offline; no CDN dependency) |
| `data_scrapers.py` | per-variable scraper dispatch (core + sport-specific) |
| `mma_sources.py` | live MMA scrapers (ufcstats form/H2H/career stats, tapology, ActionNetwork, Google News) |
| `bball_sources.py` | NBA advanced stats (basketball-reference pace, ESPN days rest) |
| `soccer_sources.py` | Soccer advanced stats (fbref xG; graceful fallback when gated) |
| `tennis_sources.py` | Tennis advanced stats (Jeff Sackmann `tennis_atp` CSVs) |
| `scoring_engine.py` | implied prob, weighting, edge, confidence *(unchanged)* |
| `config_manager.py` | `config.json` weights + `.env` key, variable registry *(unchanged)* |
| `display.py` | legacy `rich` terminal renderer (used only by `selftest.py`) |

## Notes
- Python is auto-preferred; this build is Python 3.10+.
- `.env` (Odds API key + optional `SUPABASE_URL` / `SUPABASE_ANON_KEY`) and
  `config.json` are git-ignored, as are the local history JSON files.
- Each matchup search consumes a few Odds API requests (one per active league
  in that sport); remaining quota is shown after each search.
