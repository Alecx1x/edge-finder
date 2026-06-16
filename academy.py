#!/usr/bin/env python3
"""
Money Lab Academy — a curated, vetted resource library for the whole
"making money in markets" industry: sports betting, prediction markets,
stocks/options, crypto, quant modeling, discipline, and the legal/tax side.

This is the SINGLE SOURCE OF TRUTH. It is consumed two ways:
  1. In-app: main.py serves CURRICULUM as JSON at /api/academy; the 🎓 Academy
     tab (static/academy.js) renders it next to the matching Money Lab tools.
  2. Portable: `python academy.py` writes one Markdown file per course into
     academy/ so the same curriculum is readable on a phone, in print, etc.

Every resource here was link-verified during research (June 2026). Resources
are chosen for SIGNAL OVER HYPE — books, official docs, neutral educators, and
real tools, with honest flags on anything that's marketing-adjacent. Nothing
here sells picks, "signal groups," or guaranteed profit.

NOT financial, legal, or tax advice. Laws and platform status (esp. prediction
markets) change fast and vary by state — verify before acting.
"""
import json
import os

# Resource helper: keep call sites readable.
def R(title, source, type_, cost, url, why):
    return {"title": title, "source": source, "type": type_, "cost": cost, "url": url, "why": why}


CURRICULUM = {
    "title": "Money Lab Academy",
    "tagline": "The best real resources for every facet of the markets — vetted, not hyped.",
    "disclaimer": (
        "Educational only — not financial, legal, or tax advice. Every link was verified, but "
        "platforms and laws (especially prediction markets) change fast and vary by state. "
        "Nothing here sells picks or guaranteed profit; be skeptical of anything that does."
    ),
    "courses": [
        # ---------------------------------------------------------------- #
        {
            "id": "foundations",
            "emoji": "🧮",
            "title": "Course 0 — Foundations",
            "blurb": "Probability, odds formats, expected value, variance, and the vig. The math under every tool in Money Lab. Start here even if you've bet for years.",
            "tools": ["Underpins everything — Value Finder, Kelly, all of it"],
            "topics": [
                {
                    "title": "Probability, odds & expected value",
                    "resources": [
                        R("Pinnacle Betting Resources (educational hub)", "Pinnacle", "site", "free",
                          "https://www.pinnacle.com/en/betting-articles/educational/introducing-betting-resources/ESD2ASZRNGRD5X9P",
                          "1,000+ articles from a low-margin sharp book with no incentive to dumb things down — the best free on-ramp to odds, implied probability, and EV."),
                        R("How to Calculate Expected Value", "Pinnacle", "doc", "free",
                          "https://www.pinnacle.com/en/esports-hub/betting-articles/educational/how-to-calculate-expected-value/mts2hbtp2f4mmfhh",
                          "A concrete worked EV example showing why a low-margin book leaves you far better off than a typical one — makes 'the vig' tangible."),
                        R("Learn More About Pinnacle's Margins", "Pinnacle", "doc", "free",
                          "https://www.pinnacle.com/betting-resources/en/betting-strategy/learn-more-about-pinnacles-margins/lah22jal3xrpkq42",
                          "Explains how the house edge is baked into a price and how to back it out — the foundational skill of reading any line."),
                        R("The Logic of Sports Betting", "Ed Miller & Matthew Davidow", "book", "paid", "",
                          "The single best on-ramp book: plain-English on how books work, vig, line shopping, and where edges come from. If you read one book, read this."),
                    ],
                },
                {
                    "title": "Going deeper on the math",
                    "resources": [
                        R("Sharp Sports Betting", "Stanford Wong", "book", "paid", "",
                          "The canonical math text — breakeven percentages, half-point values, EV. Drier than Miller, but the numbers don't expire."),
                        R("Unabated — Betting Basics", "Unabated (Jack Andrews)", "site", "free",
                          "https://unabated.com/education/betting-basics",
                          "A free, no-hype lesson series from a pro advantage player; it explicitly excludes 'hot picks' — exactly what you want."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "markets",
            "emoji": "📊",
            "title": "Course 1 — How Betting Markets Work",
            "blurb": "Line-setting, sharp vs. square money, market-making, line movement, Closing Line Value, de-vigging, and how books limit/ban winners.",
            "tools": ["Value Finder", "Beat the Close (CLV)", "Odds Movement"],
            "topics": [
                {
                    "title": "Market structure & the 'true' line",
                    "resources": [
                        R("What Is the Unabated Line", "Unabated", "doc", "free",
                          "https://unabated.com/articles/what-is-the-unabated-line",
                          "The best free explanation of market-making and price discovery — why sharp books' lines are the 'true' number you measure against."),
                        R("How to De-Vig Pinnacle's Odds (4 methods)", "Pinnacle Odds Dropper", "doc", "free",
                          "https://www.pinnacleoddsdropper.com/guides/how-to-devig-pinnacle-s-odds-for-betting-on-soft-books",
                          "Walks through Additive / Multiplicative / Power / Shin de-vig methods — turning a sharp line into a fair probability is THE core skill (it's what Value Finder does)."),
                    ],
                },
                {
                    "title": "Closing Line Value — your real scorecard",
                    "resources": [
                        R("Getting Precise About Closing Line Value", "Unabated", "doc", "free",
                          "https://unabated.com/articles/getting-precise-about-closing-line-value",
                          "The most rigorous free CLV write-up — how to measure it properly with a vig-free closing line, not just 'did my number move.' This is what the Beat the Close tab tracks."),
                        R("What Is Closing Line Value", "OddsJam", "doc", "free",
                          "https://oddsjam.com/betting-education/closing-line-value",
                          "A beginner-friendly CLV primer with worked examples and the three ways to beat the close (value, line shopping, timing)."),
                    ],
                },
                {
                    "title": "Limits, bans & the real constraint",
                    "resources": [
                        R("Interception: The Secrets of Modern Sports Betting", "Ed Miller & Matthew Davidow", "book", "paid", "",
                          "The sequel to Logic — deeper on modern market structure, limits, and how books profile and ban winners. Read after Logic."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "edges",
            "emoji": "🎯",
            "title": "Course 2 — Finding Edges",
            "blurb": "+EV value betting, arbitrage, middling, matched betting/promos, and DFS pick'em math (PrizePicks / Underdog / DK Pick6).",
            "tools": ["Value Finder", "Arbitrage", "Matched Betting", "Pick'em", "Sweeps"],
            "topics": [
                {
                    "title": "Value betting & arbitrage",
                    "resources": [
                        R("Value Betting Guide", "RebelBetting", "doc", "free",
                          "https://www.rebelbetting.com/valuebetting/value-betting-guide",
                          "Clean explanation of +EV value betting (betting odds higher than true probability). The tool is paid; this guide is free and accurate."),
                        R("Arbitrage Betting Guide", "RebelBetting", "doc", "free",
                          "https://www.rebelbetting.com/arbitrage-betting",
                          "Solid intro to arbitrage/sure-betting mechanics and its tradeoffs vs. value betting (guaranteed but lower ROI, faster account limits)."),
                        R("Ten Ways to Win at Sports Betting", "Unabated (Jack Andrews)", "doc", "free",
                          "https://unabated.com/articles/ten-ways-to-win-at-sports-betting-with-unabated",
                          "A real, honest taxonomy of edges — top-down line shopping, simulations, prop modeling, CLV — from a pro."),
                    ],
                },
                {
                    "title": "DFS pick'em (your actual books)",
                    "resources": [
                        R("The Art and Science of DFS Pick'em Strategy", "Unabated (Jason Scavone)", "doc", "free",
                          "https://unabated.com/articles/art-and-science-of-dfs-pickem-strategy",
                          "Teaches the breakeven-percentage math for PrizePicks/Underdog/Pick6 — the right way to evaluate pick'em as +EV (this is exactly what the Pick'em tab computes)."),
                        R("Correlation in DFS Pick'em Entries", "Stokastic", "doc", "free",
                          "https://www.stokastic.com/nba/nba-dfs-correlation-for-pickem-entries-strategy-for-prizepicks-underdog-more-ac11/",
                          "Explains a genuine structural edge: pick'em apps don't dock payouts for correlated legs — an exploitable inefficiency."),
                    ],
                },
                {
                    "title": "Community (signal, not picks)",
                    "resources": [
                        R("r/sportsbook", "Reddit", "community", "free",
                          "https://www.reddit.com/r/sportsbook",
                          "The least-bad large betting community; the wiki and 'limited/banned' threads are realistic about advantage play. Treat individual picks as noise."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "bankroll",
            "emoji": "💰",
            "title": "Course 3 — Bankroll & Risk",
            "blurb": "Kelly & fractional Kelly, risk of ruin, bet sizing, record-keeping, and why CLV beats short-term ROI as proof of skill.",
            "tools": ["Kelly calculator (top row)", "Bet Log", "Beat the Close"],
            "topics": [
                {
                    "title": "Sizing: the Kelly criterion",
                    "resources": [
                        R("The Kelly Criterion in Sports Betting", "betstamp", "doc", "free",
                          "https://betstamp.com/education/kelly-criterion",
                          "Clean explanation of the Kelly formula, plus the critical practical advice: use fractional Kelly (¼–½) and cap any single bet (Money Lab uses quarter-Kelly by default)."),
                        R("Kelly Criterion", "Wikipedia", "doc", "free",
                          "https://en.wikipedia.org/wiki/Kelly_criterion",
                          "The rigorous reference for the math, growth-rate optimality, and the overbetting/ruin tradeoff — read alongside the betstamp piece."),
                    ],
                },
                {
                    "title": "Measure yourself honestly",
                    "resources": [
                        R("betstamp Bet Tracker", "betstamp", "tool", "freemium",
                          "https://betstamp.com",
                          "A free bet-tracking app that records every bet and computes CLV. Record-keeping is non-negotiable for advantage play (Money Lab's Bet Log does this locally too)."),
                        R("Why CLV beats ROI", "OddsJam / Unabated", "doc", "free",
                          "https://oddsjam.com/betting-education/closing-line-value",
                          "Directly teaches why beating the closing line is a faster, lower-variance signal of skill than short-term win/loss ROI."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "prediction",
            "emoji": "🔮",
            "title": "Course 4 — Prediction Markets & Forecasting",
            "blurb": "Kalshi & Polymarket, event contracts, CFTC regulation, cross-market arbitrage, and forecasting as a trainable skill. The fastest-moving frontier.",
            "tools": ["New frontier — not yet a Money Lab tool (candidate to build next)"],
            "note": (
                "As of 2026 BOTH Kalshi and Polymarket are usable by US residents. Kalshi is a CFTC-regulated "
                "exchange (USD, all 50 states) and since Jan 2025 offers sports event contracts, protected by an "
                "April 2026 Third Circuit ruling — though state litigation continues. Polymarket (crypto/USDC, "
                "deepest global liquidity) re-entered the US via a CFTC-licensed structure. The legal picture is "
                "genuinely fast-moving — verify your state before trading sports contracts."
            ),
            "topics": [
                {
                    "title": "Prediction markets 101",
                    "resources": [
                        R("Understanding Prediction Markets & Event Contracts", "U.S. CFTC", "doc", "free",
                          "https://www.cftc.gov/LearnandProtect/PredictionMarkets",
                          "The neutral, authoritative federal primer on what an event contract legally is and why it differs from a sportsbook. Best single starting point."),
                        R("Kalshi Help Center / Kalshi 101", "Kalshi (official)", "doc", "free",
                          "https://help.kalshi.com",
                          "Official, well-organized docs explaining yes/no event contracts ($0.01–$1.00) and settlement, straight from the regulated exchange."),
                        R("What Is a Prediction Market?", "Polymarket (official)", "doc", "free",
                          "https://help.polymarket.com/en/articles/13364272-what-is-a-prediction-market",
                          "The plainest official explainer of the price-equals-probability model (a 20¢ share ≈ 20% implied chance)."),
                        R("What Is Kalshi? How It Works", "Built In", "site", "free",
                          "https://builtin.com/articles/what-is-kalshi",
                          "A non-affiliate editorial walkthrough — a neutral counterweight to the SEO/affiliate explainers that dominate search."),
                    ],
                },
                {
                    "title": "Regulation & mechanics",
                    "resources": [
                        R("Third Circuit Affirms Kalshi's Injunction (Apr 2026)", "Skadden (law firm)", "doc", "free",
                          "https://www.skadden.com/insights/publications/2026/04/third-circuit-affirms-kalshis-preliminary-injunction",
                          "Current, authoritative legal analysis of the pivotal ruling that sports event contracts on federal exchanges are CFTC-jurisdiction 'swaps' — the crux of the Kalshi-vs-states fight."),
                        R("Prediction Markets: Policy Issues for Congress", "Congressional Research Service", "doc", "free",
                          "https://www.congress.gov/crs-product/IF13187",
                          "Nonpartisan government overview of the open policy questions (sports contracts, federal-vs-state tension). Neutral and concise."),
                    ],
                },
                {
                    "title": "Trading prediction markets (high hype — be skeptical)",
                    "resources": [
                        R("How Prediction Market Arbitrage Works", "Trevor Lasn", "site", "free",
                          "https://www.trevorlasn.com/blog/how-prediction-market-polymarket-kalshi-arbitrage-works",
                          "An honest, technical explanation of the Yes+No < $1.00 arbitrage and cross-platform spreads, by an engineer rather than an affiliate."),
                        R("Prediction Market Arbitrage Using Option Chains", "Moontower (Kris Abdelmessih)", "site", "free",
                          "https://moontowermeta.com/prediction-market-arbitrage-using-option-chains-to-find-mispriced-bets/",
                          "From a former pro options market maker — high-signal on relative value and why most 'mispricings' vanish once you account for fees/slippage."),
                    ],
                },
                {
                    "title": "Forecasting as a skill (evergreen, low-hype)",
                    "resources": [
                        R("Superforecasting: The Art and Science of Prediction", "Philip Tetlock & Dan Gardner", "book", "paid", "",
                          "The foundational, evidence-based text on what makes some people consistently better forecasters (base rates, frequent updating, decomposition). The canonical starting point."),
                        R("Calibrate Your Judgment (calibration trainer)", "Open Philanthropy / Clearer Thinking", "tool", "free",
                          "https://80000hours.org/calibration-training/",
                          "The best free calibration trainer — thousands of questions that score whether your '80% confident' really means 80%. The single most practical exercise here."),
                        R("Metaculus", "Metaculus", "community", "free",
                          "https://www.metaculus.com",
                          "The leading free platform to actually practice calibrated forecasting and build a scored track record in tournaments."),
                        R("Good Judgment Open", "Good Judgment Inc", "community", "free",
                          "https://www.gjopen.com/",
                          "The public arm of Tetlock's tournament-winning project — free challenges where you can benchmark against Superforecasters."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "stocks",
            "emoji": "📈",
            "title": "Course 5 — Stocks & Options",
            "blurb": "Market foundations, the Greeks, implied volatility, probability of profit, and the strategies in your calculator — from neutral, no-sales-pitch sources.",
            "tools": ["Strategy Calculator", "Options Chain", "Insider Buys"],
            "topics": [
                {
                    "title": "Foundations (free, neutral)",
                    "resources": [
                        R("Investing Basics & Order Types", "U.S. SEC (Investor.gov)", "doc", "free",
                          "https://www.investor.gov/introduction-investing/investing-basics/how-stock-markets-work/types-orders",
                          "The regulator's own plain-English explainer of market/limit/stop orders and how markets work. Zero sales motive — the gold standard."),
                        R("Finance & Capital Markets", "Khan Academy", "video", "free",
                          "https://www.khanacademy.org/economics-finance-domain/core-finance",
                          "Builds genuine intuition from first principles — what a share is, IPOs, bonds, market mechanics. Nonprofit, no upsell."),
                        R("Bogleheads Investing Start-Up Kit", "Bogleheads", "community", "free",
                          "https://www.bogleheads.org/wiki/Bogleheads%C2%AE_investing_start-up_kit",
                          "The definitive case for low-cost index investing vs. active trading — essential grounding before you touch options."),
                    ],
                },
                {
                    "title": "Options fundamentals (the Greeks & IV)",
                    "resources": [
                        R("The Options Industry Council (OIC)", "OIC — an OCC service", "course", "free",
                          "https://www.optionseducation.org",
                          "The single best free, vendor-neutral options education. Run by the options clearinghouse, so nothing to sell you. Covers calls/puts, all the Greeks, plus free calculators. Start here."),
                        R("Cboe Options Institute", "Cboe Global Markets", "course", "free",
                          "https://www.cboe.com/optionsinstitute/",
                          "The exchange's 40-year-old education arm — structured 'Options 101' courses, authoritative on contract mechanics and clearing (Money Lab's chain data comes from Cboe)."),
                        R("What Are Option Greeks?", "Fidelity Learning Center", "video", "free",
                          "https://www.fidelity.com/learning-center/investment-products/options/options-greeks-video",
                          "One of the clearer free breakdowns of how time (theta), price (delta/gamma), and volatility (vega) move an option's value."),
                    ],
                },
                {
                    "title": "Strategies & deeper theory",
                    "resources": [
                        R("tastylive Learn Center", "tastylive", "course", "free",
                          "https://www.tastylive.com/learn",
                          "The best-known free, high-volume strategy education (spreads, premium selling, IV). FLAG: it's the media arm of a broker and leans hard 'always be selling' — great mechanics, treat the bias as one school, not gospel."),
                        R("Option Volatility and Pricing", "Sheldon Natenberg", "book", "paid", "",
                          "The book new professional options traders are handed first — teaches options through volatility and pricing rather than rote strategy lists. The conceptual backbone."),
                        R("Options as a Strategic Investment", "Lawrence G. McMillan", "book", "paid", "",
                          "Often called 'the bible of option trading' — the most comprehensive reference on listed strategies. A desk reference you return to for years."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "crypto",
            "emoji": "🪙",
            "title": "Course 6 — Crypto (Defense-First)",
            "blurb": "Tokens, DEXs, liquidity, on-chain analysis, and — most importantly — how to NOT get rugged. The single best filter: ask who profits from the 'advice.'",
            "tools": ["Safety Check", "Screener", "Whale Tracker", "Discover"],
            "note": (
                "Crypto 'education' is a minefield of paid signal groups and 100x-callers. Everything below is "
                "neutral docs, exchange academies (concepts only), or free tooling. Anything that requires you to "
                "join a paid group to 'get the play' IS the scam. These tools are for defense and verification, "
                "not for chasing pumps — and no checker can ever prove a token is safe."
            ),
            "topics": [
                {
                    "title": "Foundations (neutral sources)",
                    "resources": [
                        R("Ethereum.org Learn Hub", "Ethereum Foundation", "doc", "free",
                          "https://ethereum.org/en/learn/",
                          "The most neutral, non-commercial primer there is — wallets, gas, smart contracts, self-custody, with no token to sell you. Start here."),
                        R("What Are Liquidity Pools in DeFi?", "Binance Academy", "doc", "free",
                          "https://academy.binance.com/en/articles/what-are-liquidity-pools-in-defi",
                          "Clearest plain-English explainer of AMMs/pools/impermanent loss. Use Academy for CONCEPTS ONLY — ignore the 'trade now' buttons."),
                    ],
                },
                {
                    "title": "On-chain analysis & 'smart money'",
                    "resources": [
                        R("Etherscan", "Etherscan", "tool", "free",
                          "https://etherscan.io",
                          "The ground-truth block explorer — verify any transaction, token transfer, or wallet yourself instead of trusting a screenshot (Whale Tracker reads this data)."),
                        R("How to Read Etherscan (tutorial)", "Ambire", "doc", "free",
                          "https://blog.ambire.com/how-to-use-etherscan/",
                          "Turns the explorer from intimidating to usable — the single highest-leverage skill in crypto."),
                        R("DexScreener", "DexScreener", "tool", "freemium",
                          "https://dexscreener.com",
                          "Real-time DEX price/liquidity/volume across chains — a data feed for spotting liquidity and pair age, NOT a buy signal (powers Money Lab's Screener)."),
                    ],
                },
                {
                    "title": "Scams & safety (the real lesson)",
                    "resources": [
                        R("How to Identify & Protect From Rug Pulls", "CoinGecko Learn", "doc", "free",
                          "https://www.coingecko.com/learn/how-to-identify-and-protect-from-rug-pull-crypto-scam",
                          "Neutral, exchange-independent explainer of the red flags (unlocked liquidity, anon team, no audit, weird distribution) with real case studies."),
                        R("RugCheck", "RugCheck", "tool", "free",
                          "https://rugcheck.xyz",
                          "Solana token scanner — flags mint/freeze authority, holder concentration, and liquidity-lock status before you send funds (complements the Safety Check tab)."),
                        R("Honeypot.is", "community tool", "tool", "free",
                          "https://honeypot.is",
                          "Simulates a sell to detect honeypots — tokens you can buy but can't sell. A 30-second check that saves accounts."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "quant",
            "emoji": "🔬",
            "title": "Course 7 — Quant & Modeling",
            "blurb": "Backtesting, overfitting, calibration (Brier/log-loss), and rating systems (Elo/Glicko). How to know whether a model is real or just curve-fit.",
            "tools": ["Backtest", "Auto-Tune", "Calibration"],
            "topics": [
                {
                    "title": "Backtesting without fooling yourself",
                    "resources": [
                        R("The Deflated Sharpe Ratio", "Bailey & López de Prado", "doc", "free",
                          "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551",
                          "The canonical work on backtest overfitting — shows how testing many strategies inflates results, and how to correct for it. Essential and sobering."),
                        R("Walk-Forward Optimization: Intro", "QuantInsti", "doc", "free",
                          "https://blog.quantinsti.com/walk-forward-optimization-introduction/",
                          "Practical, code-backed explanation of rolling in-sample/out-of-sample testing — the closest a backtest gets to honest (it's what Auto-Tune does)."),
                        R("Backtesting Pitfalls", "Coriva", "doc", "free",
                          "https://coriva.eu.org/en/backtesting-pitfalls/",
                          "Catalogs the traps — lookahead bias, survivorship, data snooping — that make ~95% of backtested strategies fail live."),
                    ],
                },
                {
                    "title": "Calibration — do your probabilities mean anything?",
                    "resources": [
                        R("Brier Score", "Wikipedia", "doc", "free",
                          "https://en.wikipedia.org/wiki/Brier_score",
                          "Clean definition and worked formula for the metric that tells you whether your stated probabilities match reality (the Calibration tab uses this)."),
                        R("Probability Calibration", "scikit-learn docs", "doc", "free",
                          "https://scikit-learn.org/stable/modules/calibration.html",
                          "Authoritative reference on calibration curves and the metrics that matter — pairs directly with Brier/log-loss."),
                    ],
                },
                {
                    "title": "Rating systems (build a predictive model)",
                    "resources": [
                        R("How Our NFL/NBA Predictions Work", "FiveThirtyEight", "doc", "free",
                          "https://fivethirtyeight.com/methodology/how-our-nfl-predictions-work/",
                          "The gold-standard public write-up of a real production Elo model — margin-of-victory, home edge, rest/travel. Read before building anything (Money Lab's backtest uses point-in-time Elo)."),
                        R("fivethirtyeight/nfl-elo-game (code)", "FiveThirtyEight", "tool", "free",
                          "https://github.com/fivethirtyeight/nfl-elo-game",
                          "Working Python Elo + forecast-eval code with real data — clone it and watch a rating system update game by game."),
                        R("The Glicko Rating System", "Mark Glickman", "doc", "free",
                          "https://en.wikipedia.org/wiki/Glicko_rating_system",
                          "Elo's smarter successor — adds rating reliability and volatility, so the model knows how confident it should be."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "discipline",
            "emoji": "🧠",
            "title": "Course 8 — Psychology & Discipline",
            "blurb": "Process over outcome, tilt, and the cognitive biases that quietly wreck good bettors and traders. The least technical course and arguably the most important.",
            "tools": ["Applies to every decision you log"],
            "topics": [
                {
                    "title": "Decision quality vs. results",
                    "resources": [
                        R("Thinking in Bets", "Annie Duke", "book", "paid", "",
                          "The definitive treatment of process over outcome — separating decision quality from results ('resulting'), tilt, and the premortem. The most important item on this whole list."),
                        R("Thinking, Fast and Slow", "Daniel Kahneman", "book", "paid", "",
                          "The foundational catalog of cognitive biases (anchoring, availability, overconfidence) that silently distort betting and trading decisions."),
                        R("What Traders Can Learn from Thinking in Bets", "Trade That Swing", "doc", "free",
                          "https://tradethatswing.com/thinking-in-bets-what-traders-can-learn-from-annie-dukes-poker-decision-making-framework/",
                          "A free, practical bridge from Duke's poker framework to real trading/betting discipline if you want the ideas before buying the book."),
                    ],
                },
            ],
        },
        # ---------------------------------------------------------------- #
        {
            "id": "legal",
            "emoji": "⚖️",
            "title": "Course 9 — Legal, Tax & Responsible Play",
            "blurb": "How winnings are taxed, the standard-deduction trap, state-by-state legality, and responsible-gambling resources. Boring, until it isn't.",
            "tools": ["Protects the money the other 9 courses help you make"],
            "note": (
                "Educational only — NOT legal or tax advice; laws vary by state and change. Two live 2026 items "
                "matter: a new cap limiting the gambling-loss deduction to 90% of losses (you can owe tax even "
                "breaking even), and unresolved CFTC-vs-states litigation over prediction markets. Talk to a CPA "
                "for your own situation."
            ),
            "topics": [
                {
                    "title": "Taxes on gambling winnings (US)",
                    "resources": [
                        R("Topic No. 419 — Gambling Income and Losses", "IRS", "doc", "free",
                          "https://www.irs.gov/taxtopics/tc419",
                          "The authoritative IRS statement: all winnings are taxable, and losses are deductible only up to winnings and only if you itemize."),
                        R("Gambling Losses Under the OBBBA (90% cap)", "KPMG", "doc", "free",
                          "https://kpmg.com/us/en/articles/2025/gambling-losses-under-one-big-beautiful-bill.html",
                          "Big-Four explainer of the 2026 change capping the loss deduction at 90% of losses — meaning you can owe tax even when you break even."),
                    ],
                },
                {
                    "title": "Taxes on trading (US)",
                    "resources": [
                        R("Topic No. 409 — Capital Gains and Losses", "IRS", "doc", "free",
                          "https://www.irs.gov/taxtopics/tc409",
                          "The authoritative rule: assets held ≤1 year are short-term (ordinary rates), >1 year long-term (preferential rates)."),
                        R("Wash-Sale Rule: How It Works", "Charles Schwab", "doc", "free",
                          "https://www.schwab.com/learn/story/primer-on-wash-sales",
                          "A clear explainer of the 30-day wash-sale window and how a disallowed loss rolls into cost basis — easy to trip over when actively trading."),
                    ],
                },
                {
                    "title": "Legal landscape",
                    "resources": [
                        R("AGA State of Play / Gaming Map", "American Gaming Association", "tool", "free",
                          "https://www.americangaming.org/research/state-of-play-map/",
                          "Interactive state-by-state map of legal sports-betting and gaming status — the quickest read on where you can legally bet."),
                        R("Sports Betting States Tracker", "Legal Sports Report", "tool", "free",
                          "https://www.legalsportsreport.com/sports-betting/states/",
                          "A continuously updated tracker of legal online vs. retail betting by state and pending legislation. (Note: DFS and sweepstakes books follow different, sometimes contested, rules.)"),
                    ],
                },
                {
                    "title": "Responsible gambling (free, confidential, 24/7)",
                    "resources": [
                        R("National Problem Gambling Helpline — 1-800-MY-RESET", "NCPG", "hotline", "free",
                          "https://www.ncpgambling.org/help-treatment/about-the-national-problem-gambling-helpline/",
                          "Free, confidential, 24/7 helpline (call/text 1-800-697-3738) answered by trained specialists — the primary national resource."),
                        R("1-800-GAMBLER", "Council on Compulsive Gambling of NJ", "hotline", "free",
                          "https://800gambler.org/",
                          "The original (since 1983) free, confidential 24/7 helpline (1-800-426-2537). Warning signs: chasing losses, betting more than you can afford, hiding it, or borrowing to bet."),
                    ],
                },
            ],
        },
    ],
}


# Badges/colors are decided client-side; keep the data pure here.
def to_json():
    return CURRICULUM


# --------------------------------------------------------------------------- #
# `python academy.py` -> regenerate the portable Markdown library in academy/
# --------------------------------------------------------------------------- #
_TYPE_TAG = {
    "book": "📕 book", "site": "🌐 site", "doc": "📄 doc", "video": "▶️ video",
    "course": "🎓 course", "community": "👥 community", "tool": "🛠 tool", "hotline": "☎ hotline",
}


def _md_resource(r):
    tag = _TYPE_TAG.get(r["type"], r["type"])
    cost = r["cost"]
    head = f"**{r['title']}** — *{r['source']}*  `{tag}` · `{cost}`"
    link = f"\n  {r['url']}" if r["url"] else ""
    return f"- {head}{link}\n  - {r['why']}"


def write_markdown(out_dir="academy"):
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, out_dir)
    os.makedirs(out, exist_ok=True)

    # index / README
    lines = [f"# {CURRICULUM['title']}", "", f"_{CURRICULUM['tagline']}_", "",
             f"> {CURRICULUM['disclaimer']}", "", "## Courses", ""]
    for i, c in enumerate(CURRICULUM["courses"]):
        fname = f"{i:02d}-{c['id']}.md"
        lines.append(f"- {c['emoji']} **[{c['title']}]({fname})** — {c['blurb']}")
    index_md = "\n".join(lines) + "\n"
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(index_md)

    # one file per course
    for i, c in enumerate(CURRICULUM["courses"]):
        L = [f"# {c['emoji']} {c['title']}", "", c["blurb"], ""]
        if c.get("tools"):
            L.append(f"**Maps to in Money Lab:** {', '.join(c['tools'])}")
            L.append("")
        if c.get("note"):
            L.append(f"> {c['note']}")
            L.append("")
        for t in c["topics"]:
            L.append(f"## {t['title']}")
            L.append("")
            for r in t["resources"]:
                L.append(_md_resource(r))
            L.append("")
        with open(os.path.join(out, f"{i:02d}-{c['id']}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(L) + "\n")

    n_courses = len(CURRICULUM["courses"])
    n_res = sum(len(t["resources"]) for c in CURRICULUM["courses"] for t in c["topics"])
    print(f"Wrote {n_courses} courses + README ({n_res} resources) to {out}")


if __name__ == "__main__":
    write_markdown()
