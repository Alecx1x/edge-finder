"""Tests for Phase 4: closing-line-value (CLV) tracking. Run: python test_clv.py

Storage tests redirect BETS_PATH to a throwaway temp file, so the user's real
bets_log.json is never touched. Auto-capture is mocked — zero Odds API quota.
"""
import os
from pathlib import Path

import metrics
import history_store as hs


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_clv_metrics_beat_and_not():
    # Took +150 (dec 2.5), closed +120 (dec 2.2) -> beat the close by 2.5/2.2-1
    r = metrics.clv_metrics(150, 120)
    assert r["beat"] is True and approx(r["clv_pct"], 2.5 / 2.2 - 1), r
    # Took +120, closed +150 -> line moved away, did NOT beat
    r2 = metrics.clv_metrics(120, 150)
    assert r2["beat"] is False and r2["clv_pct"] < 0
    # with both close sides -> fair prob + EV vs close populated
    r3 = metrics.clv_metrics(150, 120, -140)
    assert "close_prob" in r3 and "ev_vs_close" in r3
    assert 0.0 < r3["close_prob"] < 1.0
    print(f"ok  clv_metrics (beat +13.6% / not / EV vs close {r3['ev_vs_close']})")


def test_clv_summary():
    items = [{"clv_pct": 0.05, "ev_vs_close": 0.03}, {"clv_pct": -0.02},
             {"clv_pct": 0.01, "ev_vs_close": 0.0}, {"foo": 1}]  # last has no clv -> ignored
    s = metrics.clv_summary(items)
    assert s["n"] == 3 and s["beat"] == 2
    assert approx(s["beat_rate"], 2 / 3) and approx(s["avg_clv"], (0.05 - 0.02 + 0.01) / 3)
    print(f"ok  clv_summary (n={s['n']}, beat_rate {s['beat_rate']})")


def _with_temp_bets(fn):
    orig_path, orig_which = hs.BETS_PATH, hs._which
    hs.BETS_PATH = Path(hs.APP_DIR) / "_test_clv_bets.json"
    hs._which = lambda: "json"
    try:
        if hs.BETS_PATH.exists():
            hs.BETS_PATH.unlink()
        fn()
    finally:
        if hs.BETS_PATH.exists():
            hs.BETS_PATH.unlink()
        hs.BETS_PATH, hs._which = orig_path, orig_which


def test_set_bet_close_roundtrip():
    def body():
        bet = hs.add_bet({"sport": "MMA", "name_a": "A", "name_b": "B",
                          "bet_side": "a", "bet_name": "A", "bet_odds": 150,
                          "odds_a": 150, "odds_b": -170, "edge": 0.05, "model_prob": 0.5})
        updated = hs.set_bet_close(bet["id"], 120, -140)   # closed shorter on A -> beat
        assert updated["clv_pct"] > 0 and updated["beat"] is True
        assert updated["close_odds"] == 120 and updated["ev_vs_close"] is not None
        # persisted
        reread = next(b for b in hs.list_bets() if b["id"] == bet["id"])
        assert reread["clv_pct"] == updated["clv_pct"]
        # summary picks it up
        s = hs.clv()
        assert s["n"] == 1 and s["beat"] == 1
        print(f"ok  set_bet_close round-trip (CLV {updated['clv_pct']*100:.1f}%, persisted, summary n={s['n']})")
    _with_temp_bets(body)


def test_routes_close_and_clv():
    def body():
        import main
        bet = hs.add_bet({"sport": "MMA", "name_a": "Jon Jones", "name_b": "Stipe",
                          "bet_side": "b", "bet_name": "Stipe", "bet_odds": 200,
                          "odds_a": -250, "odds_b": 200, "edge": 0.04, "model_prob": 0.4})
        client = main.app.test_client()
        # manual close entry (free)
        r = client.post(f"/api/bets/{bet['id']}/close", json={"close_side": 150, "other_close": -180})
        assert r.status_code == 200 and r.get_json()["bet"]["beat"] is True
        # invalid odds rejected
        assert client.post(f"/api/bets/{bet['id']}/close", json={"close_side": 50}).status_code == 400
        # summary route
        d = client.get("/api/clv").get_json()
        assert d["n"] == 1 and "beat_rate" in d
        # auto-capture with the network mocked (no quota)
        orig = main._resolve_close_odds
        main._resolve_close_odds = lambda b: ((130, -160), None)
        try:
            rc = client.post(f"/api/bets/{bet['id']}/capture", json={})
            assert rc.status_code == 200 and rc.get_json()["ok"] is True
        finally:
            main._resolve_close_odds = orig
        print("ok  routes /close (manual), /clv, /capture (mocked - zero quota)")
    _with_temp_bets(body)


if __name__ == "__main__":
    test_clv_metrics_beat_and_not()
    test_clv_summary()
    test_set_bet_close_roundtrip()
    test_routes_close_and_clv()
    print("\nALL PASSED")
