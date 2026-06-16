"""Tests for the matched-betting calculator. Run: python test_promo.py (pure math)."""
import promo_calc as pc


def approx(a, b, tol=0.02):
    return abs(a - b) <= tol


def test_qualifying_locks_equal_small_loss():
    # back 2.0, lay 2.0, 2% commission, £10 -> tiny equal loss both sides
    r = pc.matched_bet(2.0, 2.0, 0.02, 10.0, "qualifying")
    assert approx(r["lay_stake"], 10.10), r
    assert approx(r["profit_back"], r["profit_lay"]), r       # engineered to match
    assert approx(r["locked"], -0.10), r                      # ~10p qualifying loss
    print(f"ok  qualifying bet: lay £{r['lay_stake']}, locked £{r['locked']} (both sides equal)")


def test_free_snr_extracts_value():
    # £10 free bet (stake not returned) at back 5.0, lay 5.2, 2% -> keep ~75%
    r = pc.matched_bet(5.0, 5.2, 0.02, 10.0, "free_snr")
    assert approx(r["profit_back"], r["profit_lay"]), r
    assert r["locked"] > 7.0 and r["locked"] < 8.0, r
    assert approx(r["retention"], r["locked"] / 10.0), r
    print(f"ok  free bet (SNR): locked £{r['locked']} = {r['retention']*100:.1f}% of a £10 free bet")


def test_higher_back_odds_better_for_free_bets():
    # the classic rule: use HIGHER odds for free bets -> higher retention
    lo_odds = pc.matched_bet(2.0, 2.1, 0.02, 10.0, "free_snr")["locked"]
    hi_odds = pc.matched_bet(6.0, 6.2, 0.02, 10.0, "free_snr")["locked"]
    assert hi_odds > lo_odds, (lo_odds, hi_odds)
    print(f"ok  free-bet rule holds: high odds keep £{hi_odds} vs low odds £{lo_odds}")


def test_validation():
    assert pc.matched_bet(1.0, 2.0, 0.02, 10.0) is None      # back odds must be >1
    assert pc.matched_bet(2.0, 2.0, 0.02, 0) is None         # stake must be >0
    assert pc.matched_bet("x", 2.0, 0.02, 10.0) is None      # non-numeric
    print("ok  rejects invalid inputs")


def test_american_helper():
    assert approx(pc.american_to_decimal(100), 2.0)
    assert approx(pc.american_to_decimal(-200), 1.5)
    print("ok  american->decimal helper")


def test_api_promo_route():
    import main
    c = main.app.test_client()
    r = c.post("/api/promo", json={"bet_type": "free_snr", "back_odds": 5.0,
                                   "lay_odds": 5.2, "back_stake": 10, "commission": 0.02})
    assert r.status_code == 200, r.status_code
    d = r.get_json()
    assert "locked" in d and "retention" in d and d["locked"] > 7
    # invalid inputs -> 400
    assert c.post("/api/promo", json={"back_odds": 1.0, "lay_odds": 2.0, "back_stake": 10}).status_code == 400
    print(f"ok  /api/promo route (locked ${d['locked']}, no quota)")


if __name__ == "__main__":
    test_qualifying_locks_equal_small_loss()
    test_free_snr_extracts_value()
    test_higher_back_odds_better_for_free_bets()
    test_validation()
    test_american_helper()
    test_api_promo_route()
    print("\nALL PASSED")
