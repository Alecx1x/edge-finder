"""Tests for the arbitrage scanner. Run: python test_arb.py

Synthetic — mocks the network, spends ZERO Odds API quota.
"""
import arb_scanner as arb


def approx(a, b, tol=1e-2):
    return abs(a - b) <= tol


# Two books that disagree: each offers +120 on a different side -> guaranteed arb.
ARB_EVENT = {
    "home_team": "Fighter A", "away_team": "Fighter B", "commence_time": None,
    "bookmakers": [
        {"key": "draftkings", "title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Fighter A", "price": 120},
                                        {"name": "Fighter B", "price": -110}]}]},
        {"key": "fanduel", "title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Fighter A", "price": -110},
                                        {"name": "Fighter B", "price": 120}]}]},
    ],
}

# A normal vig'd event: no arb.
NOARB_EVENT = {
    "home_team": "X", "away_team": "Y", "commence_time": None,
    "bookmakers": [
        {"key": "draftkings", "title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "X", "price": -110}, {"name": "Y", "price": -110}]}]},
        {"key": "fanduel", "title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "X", "price": -115}, {"name": "Y", "price": -105}]}]},
    ],
}


def test_detects_arb_and_splits_stakes():
    a = arb.event_arb(ARB_EVENT, min_profit=0.0, total_stake=100.0, sport="MMA", league="UFC")
    assert a is not None, "should detect the arb"
    # best on each side is +120 (dec 2.2); 1/2.2 + 1/2.2 = 0.909 -> ~10% profit
    assert approx(a["profit_pct"], 0.10), a["profit_pct"]
    assert approx(a["guaranteed_return"], 110.0, tol=0.2), a["guaranteed_return"]
    # two legs, ~$50 each, on opposite books
    assert len(a["legs"]) == 2
    for leg in a["legs"]:
        assert approx(leg["stake"], 50.0, tol=0.5), leg
    assert {l["book_key"] for l in a["legs"]} == {"draftkings", "fanduel"}
    # every leg returns ~the same (that's the point of an arb)
    for leg in a["legs"]:
        ret = leg["stake"] * arb.vs.american_to_decimal(leg["odds"])
        assert approx(ret, a["guaranteed_return"], tol=0.5), (leg, ret)
    print(f"ok  detects arb ({a['profit_pct']*100:.1f}%), splits ${a['legs'][0]['stake']}/${a['legs'][1]['stake']}, equal returns")


def test_my_books_filter_arb():
    # the arb needs BOTH draftkings and fanduel; restrict to one -> no arb
    assert arb.event_arb(ARB_EVENT, 0.0, 100.0, "MMA", "UFC", my_books={"draftkings"}) is None
    # both selected -> arb still found
    a = arb.event_arb(ARB_EVENT, 0.0, 100.0, "MMA", "UFC", my_books={"draftkings", "fanduel"})
    assert a is not None and approx(a["profit_pct"], 0.10)
    print("ok  arb my_books filter (legs must be placeable at your books)")


def test_rejects_normal_vig():
    assert arb.event_arb(NOARB_EVENT, 0.0, 100.0, "MMA", "UFC") is None
    print("ok  rejects a normal vig'd market (no false arb)")


def test_min_profit_filter():
    # require 20% — our 10% arb should be filtered out
    assert arb.event_arb(ARB_EVENT, min_profit=0.20, total_stake=100.0, sport="MMA", league="UFC") is None
    print("ok  min-profit filter works")


def test_scan_offline():
    calls = {"n": 0}
    orig_list, orig_get = arb.of.list_active_sports, arb.of._get
    arb.of.list_active_sports = lambda k, g: [{"key": "mma", "title": "UFC"}]
    def fake_get(url, params):
        calls["n"] += 1
        return [ARB_EVENT, NOARB_EVENT], {"x-requests-remaining": "490", "x-requests-used": "10"}
    arb.of._get = fake_get
    try:
        res = arb.scan("FAKE", "MMA", regions="us,eu", min_profit=0.0, total_stake=100.0)
    finally:
        arb.of.list_active_sports, arb.of._get = orig_list, orig_get
    assert calls["n"] == 1 and len(res["arbs"]) == 1
    assert res["quota"]["remaining"] == "490"
    print(f"ok  scan() offline - {len(res['arbs'])} arb, quota {res['quota']['remaining']}")


def test_api_arb_route_mocked():
    import main
    import config_manager as cfgmod
    orig_scan, orig_key = main.arb_scanner.scan, cfgmod.get_api_key
    main.arb_scanner.scan = lambda *a, **k: {"arbs": [{"event": "A vs B", "profit_pct": 0.05,
        "legs": [], "total_stake": 100, "guaranteed_return": 105, "profit": 5, "league": "UFC"}],
        "quota": {"remaining": "488"}, "leagues": ["UFC"]}
    cfgmod.get_api_key = lambda: "FAKE"
    try:
        c = main.app.test_client()
        r = c.post("/api/arb", json={"sport": "MMA", "total_stake": 100})
        assert r.status_code == 200 and r.get_json()["arbs"][0]["profit_pct"] == 0.05
        assert c.post("/api/arb", json={"sport": "Cricket"}).status_code == 400
    finally:
        main.arb_scanner.scan, cfgmod.get_api_key = orig_scan, orig_key
    print("ok  /api/arb route (mocked - zero quota)")


if __name__ == "__main__":
    test_detects_arb_and_splits_stakes()
    test_my_books_filter_arb()
    test_rejects_normal_vig()
    test_min_profit_filter()
    test_scan_offline()
    test_api_arb_route_mocked()
    print("\nALL PASSED")
