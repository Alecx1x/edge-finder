"""Plain-assert tests for the backtest engine. Run: python test_backtest.py

No pytest dependency — keeps the project's light footprint. Covers:
  - settlement / ROI math (the part that must never be wrong about money)
  - metric sanity (perfect vs coin-flip predictor)
  - the lookahead honesty check (excluded signals stay unavailable)
  - internal consistency of a real backtest run
"""
import backtest_engine as bt
import backtest_data
import metrics
import scoring_engine
import config_manager as cfgmod


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_settlement_math():
    f = {"winner": "a", "a": {"name": "A", "odds": 100}, "b": {"name": "B", "odds": -150}, "date": "x"}
    win = bt._settle(f, "a", stake=1.0)      # bet winner at +100
    assert win["won"] and approx(win["profit"], 1.0), win
    lose = bt._settle(f, "b", stake=1.0)     # bet loser
    assert not lose["won"] and approx(lose["profit"], -1.0), lose
    fav = bt._settle({"winner": "a", "date": "x", "a": {"odds": -200}, "b": {"odds": 170}}, "a", stake=1.0)
    assert approx(fav["profit"], 0.5), fav   # -200 wins 0.5 per unit
    print("ok  settlement math")


def test_metric_extremes():
    assert metrics.brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert metrics.brier([(0.5, 1), (0.5, 0)]) == 0.25
    assert metrics.kelly_fraction(0.4, 100) == 0.0      # no edge -> no bet
    assert approx(metrics.kelly_fraction(0.6, 100), 0.2)
    print("ok  metric extremes")


def test_no_lookahead_leak():
    """Excluded signals must never be 'available' in a backtest row."""
    fights = backtest_data.load_fights()
    cfg = cfgmod.load_config()
    rep = scoring_engine.build_report("MMA", fights[500], fights[500]["data"], cfg)
    by_key = {r["key"]: r for r in rep["rows"]}
    for leaky in ("mma_sig_strikes", "mma_td_def", "injuries", "line_movement", "social_sentiment", "head_to_head"):
        assert by_key[leaky]["available"] is False, f"{leaky} leaked into backtest!"
    for live in ("elo", "recent_form"):
        assert by_key[live]["available"] is True, f"{live} should be available"
    # first chronological fight: both fighters unrated -> Elo 50/50
    first = fights[0]["data"]["elo"]
    assert approx(first["a"]["score"], 50.0) and approx(first["b"]["score"], 50.0)
    print("ok  no lookahead leak (excluded signals stay unavailable; Elo starts neutral)")


def test_run_consistency():
    cfg = cfgmod.load_config()
    s = bt.run_backtest(cfg, edge_threshold=0.02)
    assert s["n_fights"] > 1000
    bm = s["betting"]["model"]
    # ROI must equal profit / staked
    assert approx(bm["roi"], round(bm["profit"] / bm["staked"], 4), tol=1e-3)
    # equity curve has one point per placed bet
    assert len(s["equity_curve"]) == bm["n"]
    if s["equity_curve"]:
        assert approx(s["equity_curve"][-1]["kelly_bankroll"], bm["final_bankroll"], tol=0.01)
    # favourite baseline should win clearly more than half (favourites win more often)
    assert 0.55 < s["betting"]["baseline_favorite"]["win_rate"] < 0.80
    # Brier in a sane range
    assert 0.0 < s["prediction"]["model"]["brier"] < 0.5
    print(f"ok  run consistency  (n={s['n_fights']}, model ROI {bm['roi']*100:.1f}%, "
          f"baseline win {s['betting']['baseline_favorite']['win_rate']*100:.1f}%)")


def test_api_route():
    import main
    client = main.app.test_client()
    r = client.post("/api/backtest", json={"edge_threshold": 0.03})
    assert r.status_code == 200, r.status_code
    data = r.get_json()
    for key in ("n_fights", "prediction", "betting", "equity_curve"):
        assert key in data, key
    print("ok  /api/backtest route")


def test_walk_forward_out_of_sample():
    import optimizer
    cfg = cfgmod.load_config()
    r = optimizer.walk_forward(cfg, train_frac=0.7, edge_threshold=0.02, objective="roi", step=0.5)
    # train and test must be chronological and disjoint (the whole point)
    assert r["train_to"] <= r["test_from"], "train/test overlap — not out-of-sample!"
    assert r["n_train"] + r["n_test"] == len(backtest_data.load_fights())
    # tuned weights live in the legal range
    for k in ("elo", "recent_form"):
        assert 0.0 <= r["tuned_weights"][k] <= 2.0
    # the structure the UI relies on
    for side in ("train", "test", "baseline_test"):
        assert "roi_flat" in r[side] and "brier" in r[side]
    print(f"ok  walk-forward out-of-sample  (train/test boundary {r['split_date']}, "
          f"weights elo={r['tuned_weights']['elo']} form={r['tuned_weights']['recent_form']})")


def test_tune_objectives_differ_sanely():
    import optimizer
    cfg = cfgmod.load_config()
    # optimizing pure prediction accuracy should drive signal weights toward 0
    # (trust the market) — a strong, falsifiable honesty check on the optimizer.
    r = optimizer.walk_forward(cfg, train_frac=0.7, edge_threshold=0.02, objective="log_loss", step=0.5)
    w = r["tuned_weights"]
    assert w["elo"] + w["recent_form"] <= 0.5, f"log-loss tuner should distrust weak signals, got {w}"
    print(f"ok  log-loss objective trusts the market (weights {w})")


def test_api_tune_route():
    import main
    client = main.app.test_client()
    r = client.post("/api/tune", json={"objective": "roi", "train_frac": 0.7, "edge_threshold": 0.02})
    assert r.status_code == 200, r.status_code
    data = r.get_json()
    for key in ("tuned_weights", "train", "test", "baseline_test", "split_date"):
        assert key in data, key
    print("ok  /api/tune route")


if __name__ == "__main__":
    test_settlement_math()
    test_metric_extremes()
    test_no_lookahead_leak()
    test_run_consistency()
    test_api_route()
    test_walk_forward_out_of_sample()
    test_tune_objectives_differ_sanely()
    test_api_tune_route()
    print("\nALL PASSED")
