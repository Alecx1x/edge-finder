"""Walk-forward weight optimization — the auto-tuner that replaces the sliders.

Instead of the user guessing weights, this searches for the weights that would
have performed best on PAST fights — but it does so honestly, using a
**walk-forward split**: it tunes only on an earlier "train" slice of history, then
reports performance on a later "test" slice the tuner never saw. The test number
is the one you trust; a big train→test drop is **overfitting**, the single most
common way people fool themselves into thinking they have an edge.

Only the two signals that are actually available in a backtest (`elo`,
`recent_form`) are tuned; raising a signal's weight makes the model lean on it
more (and on the market less). Everything else in the config is left untouched.
"""
import copy

import scoring_engine
import metrics
import backtest_data
import backtest_engine

TUNE_KEYS = ("elo", "recent_form")
MIN_BETS_TRAIN = 30      # ignore weight combos that bet too rarely to judge by ROI


def grid_values(step=0.5):
    """Weight values 0.0 .. 2.0 inclusive at the given step."""
    n = int(round(2.0 / step))
    return [round(i * step, 3) for i in range(n + 1)]


def _cfg_with(base_cfg, overrides):
    cfg = copy.deepcopy(base_cfg)
    cfg["weights"].update(overrides)
    return cfg


def _lean_eval(fights, cfg, edge_threshold):
    """Fast objective-only evaluation (no equity curve / baselines)."""
    model_pairs, bets = [], []
    for f in fights:
        rep = scoring_engine.build_report(f["sport"], f, f["data"], cfg)
        model_pairs.append((rep["model"]["a"], 1 if f["winner"] == "a" else 0))
        rec = rep["recommendation"]
        if rec["edge"] >= edge_threshold:
            side = rec["side"]
            won = f["winner"] == side
            profit = metrics.american_to_decimal_profit(f[side]["odds"]) if won else -1.0
            bets.append({"stake": 1.0, "profit": profit, "won": won})
    summ = metrics.summarize_bets(bets)
    return {"roi": summ["roi"], "n_bets": summ["n"], "win_rate": summ["win_rate"],
            "brier": metrics.brier(model_pairs), "log_loss": metrics.log_loss(model_pairs)}


def _score(ev, objective):
    """Higher is better. Disqualify thin-sample ROI combos with -inf."""
    if objective == "roi":
        if ev["roi"] is None or ev["n_bets"] < MIN_BETS_TRAIN:
            return float("-inf")
        return ev["roi"]
    # default: prediction quality — maximize by minimizing log loss
    return -ev["log_loss"] if ev["log_loss"] is not None else float("-inf")


def optimize(train, base_cfg, edge_threshold, objective, step=0.5):
    """Grid-search (elo, recent_form) weights on the train slice."""
    best, grid = None, []
    for ew in grid_values(step):
        for fw in grid_values(step):
            cfg = _cfg_with(base_cfg, {"elo": ew, "recent_form": fw})
            ev = _lean_eval(train, cfg, edge_threshold)
            sc = _score(ev, objective)
            grid.append({"elo": ew, "form": fw, "score": None if sc == float("-inf") else round(sc, 4),
                         "roi": ev["roi"],
                         "brier": round(ev["brier"], 4) if ev["brier"] is not None else None,
                         "n_bets": ev["n_bets"]})
            if best is None or sc > best["score"]:
                best = {"score": sc, "elo": ew, "form": fw, "eval": ev}
    # If ROI disqualified every combo (too few bets anywhere), fall back to log loss.
    if best is None or best["score"] == float("-inf"):
        return optimize(train, base_cfg, edge_threshold, "log_loss", step)
    return best, grid


def _digest(card):
    """Pull headline numbers out of a full backtest scorecard."""
    bm = card["betting"]["model"]
    pred = card["prediction"]
    return {
        "n_bets": bm["n"], "win_rate": bm["win_rate"],
        "roi_flat": bm["roi"], "roi_kelly": bm["roi_kelly"],
        "final_bankroll": bm["final_bankroll"],
        "brier": pred["model"]["brier"], "market_brier": pred["market"]["brier"],
        "beats_market": pred["beats_market"],
    }


def walk_forward(base_cfg, train_frac=0.7, edge_threshold=0.02, objective="roi",
                 step=0.5, fights=None, csv_path=None):
    """Tune on the earlier `train_frac` of history, evaluate on the rest."""
    if fights is None:
        fights = backtest_data.load_fights(csv_path)
    if len(fights) < 200:
        raise ValueError("Not enough fights to split into train/test.")

    train_frac = max(0.3, min(0.9, float(train_frac)))
    cut = int(len(fights) * train_frac)
    train, test = fights[:cut], fights[cut:]
    split_date = test[0]["date"]

    best, grid = optimize(train, base_cfg, edge_threshold, objective, step)
    tuned = {"elo": best["elo"], "recent_form": best["form"]}
    tuned_cfg = _cfg_with(base_cfg, tuned)

    train_card = backtest_engine.run_backtest(tuned_cfg, edge_threshold, fights=train)
    test_card = backtest_engine.run_backtest(tuned_cfg, edge_threshold, fights=test)
    base_test = backtest_engine.run_backtest(base_cfg, edge_threshold, fights=test)

    train_d, test_d, base_d = _digest(train_card), _digest(test_card), _digest(base_test)
    gap = None
    if train_d["roi_flat"] is not None and test_d["roi_flat"] is not None:
        gap = round(train_d["roi_flat"] - test_d["roi_flat"], 4)

    return {
        "objective": "roi" if objective == "roi" else "log_loss",
        "train_frac": train_frac, "split_date": split_date,
        "n_train": len(train), "n_test": len(test),
        "train_from": train[0]["date"], "train_to": train[-1]["date"],
        "test_from": test[0]["date"], "test_to": test[-1]["date"],
        "edge_threshold": edge_threshold,
        "tuned_weights": tuned,
        "train": train_d, "test": test_d, "baseline_test": base_d,
        "overfit_gap": gap,
        "grid": grid,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _fmt(x):
    return f"{x*100:6.1f}%" if isinstance(x, (int, float)) else "    n/a"


def main():
    import argparse
    import config_manager as cfgmod
    ap = argparse.ArgumentParser(description="Walk-forward auto-tune of the Edge Finder weights.")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--edge", type=float, default=0.02)
    ap.add_argument("--train", type=float, default=0.7, help="train fraction (default 0.7)")
    ap.add_argument("--objective", choices=("roi", "log_loss"), default="roi")
    ap.add_argument("--step", type=float, default=0.5, help="weight grid step (default 0.5)")
    args = ap.parse_args()

    cfg = cfgmod.load_config()
    r = walk_forward(cfg, train_frac=args.train, edge_threshold=args.edge,
                     objective=args.objective, step=args.step, csv_path=args.csv)

    print(f"\n=== Walk-forward auto-tune (objective: {r['objective']}) ===")
    print(f"Train: {r['train_from']} -> {r['train_to']}  ({r['n_train']} fights)")
    print(f"Test:  {r['test_from']} -> {r['test_to']}  ({r['n_test']} fights)  [unseen]")
    print(f"Best weights on TRAIN: elo={r['tuned_weights']['elo']}  "
          f"recent_form={r['tuned_weights']['recent_form']}\n")
    print(f"                 TRAIN      TEST   (test = the number you trust)")
    print(f"  ROI (flat)   {_fmt(r['train']['roi_flat'])}   {_fmt(r['test']['roi_flat'])}")
    print(f"  ROI (Kelly)  {_fmt(r['train']['roi_kelly'])}   {_fmt(r['test']['roi_kelly'])}")
    print(f"  Brier        {r['train']['brier']}     {r['test']['brier']}")
    print(f"  Bets         {r['train']['n_bets']:>6}    {r['test']['n_bets']:>6}")
    if r["overfit_gap"] is not None:
        print(f"\n  Overfit gap (train ROI - test ROI): {r['overfit_gap']*100:.1f} pts")
        if r["overfit_gap"] > 0.03:
            print("  -> The train result was largely a mirage. Classic overfitting.")
    print(f"\n  Baseline (default weights) on TEST: ROI {_fmt(r['baseline_test']['roi_flat'])}")
    print()


if __name__ == "__main__":
    main()
