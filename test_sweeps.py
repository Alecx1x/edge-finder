"""Tests for the sweeps tools. Run: python test_sweeps.py (pure math)."""
import sweeps_calc as sw


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_manual_ev_plus_and_minus():
    # your +150, sharp says +120/-140 -> sharp fair on your side ~43.8%; +150 pays 2.5
    r = sw.manual_ev(150, 120, -140)
    assert r["plus_ev"] is True and r["ev_pct"] > 0, r
    # your -150 on the same fair ~43.8% is clearly -EV
    r2 = sw.manual_ev(-150, 120, -140)
    assert r2["plus_ev"] is False and r2["ev_pct"] < 0, r2
    print(f"ok  manual EV (+150 -> {r['ev_pct']*100:+.1f}%, -150 -> {r2['ev_pct']*100:+.1f}%)")


def test_manual_ev_matches_fair():
    # if your odds EQUAL the de-vigged fair line, EV ~ 0
    # fair from -110/-110 is 50% -> fair american is +100 (decimal 2.0)
    r = sw.manual_ev(100, -110, -110)
    assert approx(r["fair_prob"], 0.5) and approx(r["ev_pct"], 0.0, tol=0.005)
    print("ok  manual EV ~0 when your price equals the fair line")


def test_bonus_value():
    r = sw.bonus_value(50, 1.0, 0.045)
    assert approx(r["value"], 50 * (1 - 0.045)) and approx(r["retention"], 0.955)
    # higher playthrough -> less value
    assert sw.bonus_value(50, 5.0)["value"] < sw.bonus_value(50, 1.0)["value"]
    print(f"ok  bonus value (50 SC @1x -> ${r['value']}, {r['retention']*100:.1f}%)")


def test_validation():
    assert sw.manual_ev(50, 120, -140) is None     # 50 isn't valid American odds
    assert sw.bonus_value(-5) is None
    print("ok  rejects invalid inputs")


def test_api_routes():
    import main
    c = main.app.test_client()
    r1 = c.post("/api/sweeps_ev", json={"your_odds": 150, "ref_side_odds": 120, "ref_other_odds": -140})
    assert r1.status_code == 200 and r1.get_json()["plus_ev"] is True
    r2 = c.post("/api/sweeps_bonus", json={"sc": 50, "playthrough": 1})
    assert r2.status_code == 200 and approx(r2.get_json()["retention"], 0.955)
    assert c.post("/api/sweeps_ev", json={"your_odds": 5}).status_code == 400
    print("ok  /api/sweeps_ev + /api/sweeps_bonus routes")


if __name__ == "__main__":
    test_manual_ev_plus_and_minus()
    test_manual_ev_matches_fair()
    test_bonus_value()
    test_validation()
    test_api_routes()
    print("\nALL PASSED")
