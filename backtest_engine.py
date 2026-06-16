"""Backtest engine: replay historical fights through the live scoring engine.

This is the heart of turning the app from a slider toy into an evidence tool. It
loads point-in-time historical fights (`backtest_data`), runs each one through the
UNCHANGED `scoring_engine.build_report` with whatever weights are in `config.json`,
and reports two separate, honest questions:

  1. PREDICTION QUALITY (over every fight): are the model's probabilities any
     good, and do they beat just trusting the closing line? (Brier / log loss /
     calibration, model vs. market.)
  2. BETTING RESULT (over fights where the edge clears a threshold): would
     actually placing those bets have made money? (ROI flat + Kelly, win rate,
     equity curve), with an "always bet the favourite" baseline for context.

There is no train/test split here because the weights are NOT fit to this data —
the evaluation is out-of-sample by construction. (That changes in phase 2, when
we auto-tune weights and a walk-forward split becomes mandatory.)
"""
import argparse

import config_manager as cfgmod
import scoring_engine
import metrics
import backtest_data

KELLY_FRACTION_MULT = 0.5   # half-Kelly: prudent, much lower variance than full
KELLY_START_BANKROLL = 100.0


def run_backtest(cfg, edge_threshold=0.02, date_from=None, date_to=None,
                 fights=None, csv_path=None):
    """Run the backtest and return a JSON-able scorecard.

    cfg            : config dict with ["weights"] (as produced by config_manager)
    edge_threshold : minimum model edge to place a simulated bet (e.g. 0.02 = 2%)
    date_from/to   : optional 'YYYY-MM-DD' bounds (inclusive)
    fights         : pre-loaded fight list (else loaded from csv_path/default)
    """
    if fights is None:
        fights = backtest_data.load_fights(csv_path)
    if date_from:
        fights = [f for f in fights if f["date"] >= date_from]
    if date_to:
        fights = [f for f in fights if f["date"] <= date_to]

    # Prediction-quality accumulators (over EVERY fight).
    model_pairs, market_pairs = [], []   # (prob_side_a, outcome_a) for Brier/logloss
    cal_items = []                       # favoured-side calibration
    avail_sum = 0.0

    # Betting accumulators (only fights whose edge clears the threshold).
    model_bets, favorite_bets = [], []
    flat_profit = 0.0
    kelly_bankroll = KELLY_START_BANKROLL
    equity_curve = []

    for f in fights:
        report = scoring_engine.build_report(f["sport"], f, f["data"], cfg)
        y_a = 1 if f["winner"] == "a" else 0
        m_a = report["model"]["a"]
        i_a = report["implied"]["a"]
        avail_sum += report.get("availability", 0.0)

        # --- prediction quality (all fights) ---
        model_pairs.append((m_a, y_a))
        market_pairs.append((i_a, y_a))
        fav = "a" if m_a >= 0.5 else "b"
        cal_items.append({
            "prob": m_a if fav == "a" else (1 - m_a),
            "settled": True,
            "won": f["winner"] == fav,
        })

        # --- always-bet-favourite baseline (market favourite, flat stake) ---
        mkt_fav = "a" if i_a >= 0.5 else "b"
        favorite_bets.append(_settle(f, mkt_fav, stake=1.0))

        # --- model bet (gated by edge threshold) ---
        rec = report["recommendation"]
        if rec["edge"] >= edge_threshold:
            side = rec["side"]
            odds = f[side]["odds"]
            p = report["model"][side]
            bet = _settle(f, side, stake=1.0)
            model_bets.append(bet)
            flat_profit += bet["profit"]

            # half-Kelly, capped at 100% of bankroll; stop staking once ruined.
            if kelly_bankroll > 0:
                kf = min(1.0, metrics.kelly_fraction(p, odds) * KELLY_FRACTION_MULT)
                stake = kf * kelly_bankroll
                kelly_bankroll = max(0.0, kelly_bankroll + _settle(f, side, stake=stake)["profit"])
            equity_curve.append({
                "date": f["date"],
                "flat_profit": round(flat_profit, 3),
                "kelly_bankroll": round(kelly_bankroll, 3),
            })

    n = len(fights)
    model_summary = metrics.summarize_bets(model_bets)
    model_summary["roi_kelly"] = (round((kelly_bankroll - KELLY_START_BANKROLL)
                                        / KELLY_START_BANKROLL, 4))
    model_summary["final_bankroll"] = round(kelly_bankroll, 2)

    brier_model, brier_market = metrics.brier(model_pairs), metrics.brier(market_pairs)

    return {
        "n_fights": n,
        "date_from": fights[0]["date"] if fights else None,
        "date_to": fights[-1]["date"] if fights else None,
        "edge_threshold": edge_threshold,
        "avg_availability": round(avail_sum / n, 4) if n else None,
        "prediction": {
            "model": {"brier": _r(brier_model), "log_loss": _r(metrics.log_loss(model_pairs))},
            "market": {"brier": _r(brier_market), "log_loss": _r(metrics.log_loss(market_pairs))},
            "beats_market": (brier_model is not None and brier_market is not None
                             and brier_model < brier_market),
            "calibration": metrics.calibration_buckets(cal_items),
        },
        "betting": {
            "model": model_summary,
            "baseline_favorite": metrics.summarize_bets(favorite_bets),
        },
        "equity_curve": equity_curve,
    }


def _settle(fight, side, stake):
    """Settle a flat/Kelly stake on `side` of `fight`. Returns a bet dict."""
    won = fight["winner"] == side
    odds = fight[side]["odds"]
    profit = stake * metrics.american_to_decimal_profit(odds) if won else -stake
    return {"stake": stake, "profit": profit, "won": won,
            "date": fight["date"], "side": side, "odds": odds}


def _r(x, nd=4):
    return round(x, nd) if isinstance(x, (int, float)) else None


# --------------------------------------------------------------------------- #
# CLI — prints a readable scorecard to the terminal (no UI needed)
# --------------------------------------------------------------------------- #
def _print_scorecard(s):
    def pct(x):
        return f"{x*100:5.1f}%" if isinstance(x, (int, float)) else "   n/a"

    print(f"\n=== Backtest: {s['n_fights']} fights  "
          f"({s['date_from']} -> {s['date_to']})  "
          f"edge>= {s['edge_threshold']*100:.0f}% ===")
    print(f"avg signal coverage per fight: {pct(s['avg_availability'])}  "
          f"(low = model mostly tracks the market)\n")

    pm, mk = s["prediction"]["model"], s["prediction"]["market"]
    print("PREDICTION QUALITY (lower is better; the market is the bar to beat)")
    print(f"  Brier    model {pm['brier']}   market {mk['brier']}"
          f"   -> {'MODEL beats market' if s['prediction']['beats_market'] else 'market is sharper'}")
    print(f"  LogLoss  model {pm['log_loss']}   market {mk['log_loss']}")
    print("  Calibration (model says X%, actually won Y%):")
    for b in s["prediction"]["calibration"]:
        print(f"    {b['label']:>7}: n={b['n']:>4}  predicted {pct(b['predicted'])}  "
              f"actual {pct(b['actual'])}")

    bm, bf = s["betting"]["model"], s["betting"]["baseline_favorite"]
    print("\nBETTING RESULT")
    print(f"  Model    bets={bm['n']:>4}  win {pct(bm['win_rate'])}  "
          f"ROI(flat) {pct(bm['roi'])}  ROI(half-Kelly) {pct(bm['roi_kelly'])}  "
          f"end bankroll {bm['final_bankroll']} (from {KELLY_START_BANKROLL:.0f})")
    print(f"  Always-favourite baseline: bets={bf['n']:>4}  win {pct(bf['win_rate'])}  "
          f"ROI(flat) {pct(bf['roi'])}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Backtest the Edge Finder model on historical UFC fights.")
    ap.add_argument("--csv", default=None, help="path to ufc-master.csv (default: data/ufc-master.csv)")
    ap.add_argument("--edge", type=float, default=0.02, help="min edge to bet (default 0.02)")
    ap.add_argument("--from", dest="date_from", default=None, help="start date YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", default=None, help="end date YYYY-MM-DD")
    args = ap.parse_args()

    cfg = cfgmod.load_config()
    scorecard = run_backtest(cfg, edge_threshold=args.edge, date_from=args.date_from,
                             date_to=args.date_to, csv_path=args.csv)
    _print_scorecard(scorecard)


if __name__ == "__main__":
    main()
