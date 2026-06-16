# 🔬 Course 7 — Quant & Modeling

Backtesting, overfitting, calibration (Brier/log-loss), and rating systems (Elo/Glicko). How to know whether a model is real or just curve-fit.

**Maps to in Money Lab:** Backtest, Auto-Tune, Calibration

## Backtesting without fooling yourself

- **The Deflated Sharpe Ratio** — *Bailey & López de Prado*  `📄 doc` · `free`
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
  - The canonical work on backtest overfitting — shows how testing many strategies inflates results, and how to correct for it. Essential and sobering.
- **Walk-Forward Optimization: Intro** — *QuantInsti*  `📄 doc` · `free`
  https://blog.quantinsti.com/walk-forward-optimization-introduction/
  - Practical, code-backed explanation of rolling in-sample/out-of-sample testing — the closest a backtest gets to honest (it's what Auto-Tune does).
- **Backtesting Pitfalls** — *Coriva*  `📄 doc` · `free`
  https://coriva.eu.org/en/backtesting-pitfalls/
  - Catalogs the traps — lookahead bias, survivorship, data snooping — that make ~95% of backtested strategies fail live.

## Calibration — do your probabilities mean anything?

- **Brier Score** — *Wikipedia*  `📄 doc` · `free`
  https://en.wikipedia.org/wiki/Brier_score
  - Clean definition and worked formula for the metric that tells you whether your stated probabilities match reality (the Calibration tab uses this).
- **Probability Calibration** — *scikit-learn docs*  `📄 doc` · `free`
  https://scikit-learn.org/stable/modules/calibration.html
  - Authoritative reference on calibration curves and the metrics that matter — pairs directly with Brier/log-loss.

## Rating systems (build a predictive model)

- **How Our NFL/NBA Predictions Work** — *FiveThirtyEight*  `📄 doc` · `free`
  https://fivethirtyeight.com/methodology/how-our-nfl-predictions-work/
  - The gold-standard public write-up of a real production Elo model — margin-of-victory, home edge, rest/travel. Read before building anything (Money Lab's backtest uses point-in-time Elo).
- **fivethirtyeight/nfl-elo-game (code)** — *FiveThirtyEight*  `🛠 tool` · `free`
  https://github.com/fivethirtyeight/nfl-elo-game
  - Working Python Elo + forecast-eval code with real data — clone it and watch a rating system update game by game.
- **The Glicko Rating System** — *Mark Glickman*  `📄 doc` · `free`
  https://en.wikipedia.org/wiki/Glicko_rating_system
  - Elo's smarter successor — adds rating reliability and volatility, so the model knows how confident it should be.

