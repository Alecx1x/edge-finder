"""Tests for the +EV value scanner. Run: python test_value.py

All synthetic — makes ZERO real Odds API calls (the live scan is mocked), so it
never touches the user's monthly quota.
"""
import value_scanner as vs


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


# A synthetic 2-way event: Pinnacle pegs it 50/50; DraftKings overpays side A.
SYNTH_EVENT = {
    "home_team": "Fighter A", "away_team": "Fighter B",
    "commence_time": "2026-07-01T02:00:00Z",
    "bookmakers": [
        {"key": "pinnacle", "title": "Pinnacle", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Fighter A", "price": -110}, {"name": "Fighter B", "price": -110}]}]},
        {"key": "draftkings", "title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Fighter A", "price": 120}, {"name": "Fighter B", "price": -140}]}]},
        {"key": "fanduel", "title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Fighter A", "price": -105}, {"name": "Fighter B", "price": -115}]}]},
        {"key": "betrivers", "title": "BetRivers", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Fighter A", "price": 125}, {"name": "Fighter B", "price": -150}]}]},
    ],
}


def test_devig_sums_to_one():
    fair = vs.devig({"A": -110, "B": -110})
    assert approx(sum(fair.values()), 1.0)
    assert approx(fair["A"], 0.5) and approx(fair["B"], 0.5)
    # 3-way (soccer) still normalizes
    three = vs.devig({"H": -120, "D": 240, "A": 280})
    assert approx(sum(three.values()), 1.0)
    print("ok  de-vig sums to 1 (2-way and 3-way)")


def test_fair_line_prefers_pinnacle():
    books = vs._book_markets(SYNTH_EVENT)
    fair, ref = vs._fair_line(books)
    assert ref == "Pinnacle"
    assert approx(fair["Fighter A"], 0.5)
    print("ok  fair line uses Pinnacle when present")


def test_detects_known_plus_ev():
    opps = vs.event_opportunities(SYNTH_EVENT, min_ev=0.02, bankroll=1000.0, sport="MMA", league="UFC")
    # DraftKings +120 on a true 50% shot = 0.5*2.2 - 1 = +10% EV
    dk = [o for o in opps if o["book_key"] == "draftkings" and o["selection"] == "Fighter A"]
    assert len(dk) == 1, opps
    assert approx(dk[0]["ev_pct"], 0.10), dk[0]["ev_pct"]
    assert dk[0]["book_type"] == "soft"
    assert dk[0]["limit_risk"] is True            # >= 8% -> flagged
    # opponent info present for one-click logging
    assert dk[0]["opponent"] == "Fighter B"
    assert dk[0]["opponent_price"] == -140
    # FanDuel -105 on a 50% shot is -EV and must NOT appear
    assert not any(o["book_key"] == "fanduel" for o in opps)
    # never bet the reference (Pinnacle) against itself
    assert not any(o["book_key"] == "pinnacle" for o in opps)
    print(f"ok  detects +EV (DK +120 -> {dk[0]['ev_pct']*100:.0f}% EV), rejects -EV, skips reference")


def test_my_books_filter():
    # only surface bets at books the user selected (DraftKings), not FanDuel etc.
    all_opps = vs.event_opportunities(SYNTH_EVENT, 0.0, 1000.0, "MMA", "UFC")
    dk_only = vs.event_opportunities(SYNTH_EVENT, 0.0, 1000.0, "MMA", "UFC", my_books={"draftkings"})
    assert all(o["book_key"] == "draftkings" for o in dk_only), dk_only
    assert any(o["book_key"] != "draftkings" for o in all_opps)  # filter actually narrowed it
    # filtering to a book with no +EV here yields nothing
    assert vs.event_opportunities(SYNTH_EVENT, 0.0, 1000.0, "MMA", "UFC", my_books={"fanduel"}) == []
    print("ok  my_books filter surfaces only selected books")


def test_consensus_fallback_without_pinnacle():
    ev = {"home_team": "A", "away_team": "B", "bookmakers": [
        b for b in SYNTH_EVENT["bookmakers"] if b["key"] != "pinnacle"]}
    books = vs._book_markets(ev)
    fair, ref = vs._fair_line(books)
    assert ref == "market consensus" and approx(sum(fair.values()), 1.0)
    print("ok  consensus fallback when Pinnacle absent")


def test_round_stake_under_radar():
    s = vs.suggest_stake(1000.0, 0.5, 120)     # quarter-Kelly capped at 2% -> $20
    assert s == 20, s
    assert vs.suggest_stake(1000.0, 0.45, -110) % 5 == 0   # always a round number
    print("ok  stake suggestion is conservative + round")


def test_scan_makes_no_real_calls(monkeypatch=None):
    """Mock the network so scan() runs fully offline."""
    calls = {"n": 0}

    def fake_list(api_key, group):
        return [{"key": "mma_mixed_martial_arts", "title": "UFC"}]

    def fake_get(url, params):
        calls["n"] += 1
        return [SYNTH_EVENT], {"x-requests-remaining": "498", "x-requests-used": "2"}

    orig_list, orig_get = vs.of.list_active_sports, vs.of._get
    vs.of.list_active_sports = fake_list
    vs.of._get = fake_get
    try:
        res = vs.scan("FAKEKEY", "MMA", regions="us,eu", min_ev=0.02, bankroll=1000.0)
    finally:
        vs.of.list_active_sports, vs.of._get = orig_list, orig_get

    assert calls["n"] == 1, "should hit one league endpoint"
    assert res["quota"]["remaining"] == "498"
    assert res["no_pinnacle"] is False
    assert res["opportunities"] and res["opportunities"][0]["ev_pct"] >= 0.02
    print(f"ok  scan() works offline (mocked) - {len(res['opportunities'])} opps, quota {res['quota']['remaining']}")


def test_api_scan_route_mocked():
    """Exercise /api/scan plumbing with scan() mocked — no network, no quota."""
    import main
    import config_manager as cfgmod
    orig_scan, orig_key = main.value_scanner.scan, cfgmod.get_api_key
    main.value_scanner.scan = lambda *a, **k: {
        "opportunities": [{"sport": "MMA", "league": "UFC", "event": "A vs B",
                           "selection": "A", "book": "DraftKings", "book_key": "draftkings",
                           "price": 120, "fair_prob": 0.5, "ev_pct": 0.10, "reference": "Pinnacle",
                           "suggested_stake": 20, "book_type": "soft", "limit_risk": True,
                           "commence_time": None}],
        "quota": {"remaining": "497", "used": "3"}, "leagues": ["UFC"], "no_pinnacle": False}
    cfgmod.get_api_key = lambda: "FAKEKEY"
    try:
        client = main.app.test_client()
        r = client.post("/api/scan", json={"sport": "MMA", "min_ev": 0.02, "regions": "us,eu"})
        assert r.status_code == 200, r.status_code
        d = r.get_json()
        assert d["opportunities"][0]["ev_pct"] == 0.10
        assert d["quota"]["remaining"] == "497"
        # unknown sport rejected
        assert client.post("/api/scan", json={"sport": "Cricket"}).status_code == 400
    finally:
        main.value_scanner.scan, cfgmod.get_api_key = orig_scan, orig_key
    print("ok  /api/scan route (mocked - zero quota spent)")


if __name__ == "__main__":
    test_devig_sums_to_one()
    test_fair_line_prefers_pinnacle()
    test_detects_known_plus_ev()
    test_my_books_filter()
    test_consensus_fallback_without_pinnacle()
    test_round_stake_under_radar()
    test_scan_makes_no_real_calls()
    test_api_scan_route_mocked()
    print("\nALL PASSED")
