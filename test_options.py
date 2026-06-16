"""Tests for the options strategy calculator. Run: python test_options.py (pure math)."""
import options_calc as oc


def approx(a, b, tol=0.02):
    return abs(a - b) <= tol


def test_covered_call():
    # own at $100, sell $105 call for $2, 30 days
    r = oc.covered_call(100, 105, 2, contracts=1, days=30)
    assert r["premium_income"] == 200
    assert approx(r["max_profit"], 700)               # (105-100)*100 + 200
    assert approx(r["breakeven"], 98)                 # 100 - 2
    assert approx(r["static_return"], 0.02)           # 2/100
    assert approx(r["static_return_annualized"], 0.02 * 365 / 30)
    print(f"ok  covered call (max ${r['max_profit']}, BE ${r['breakeven']}, "
          f"static {r['static_return']*100:.0f}% -> {r['static_return_annualized']*100:.0f}% ann.)")


def test_cash_secured_put():
    # sell $95 put for $2, stock at $100, 30 days
    r = oc.cash_secured_put(95, 2, contracts=1, days=30, stock_price=100)
    assert r["collateral"] == 9500 and r["max_profit"] == 200
    assert approx(r["breakeven"], 93)                 # 95 - 2
    assert approx(r["return_if_otm"], 2 / 95)
    assert approx(r["discount_to_current"], (100 - 93) / 100)
    print(f"ok  cash-secured put (BE ${r['breakeven']}, {r['return_if_otm']*100:.1f}% on collateral, "
          f"{r['discount_to_current']*100:.0f}% discount if assigned)")


def test_vertical_debit_and_credit():
    # bull call: buy 100c / sell 105c for $2 debit
    bc = oc.vertical_spread("bull_call", 100, 105, 2)
    assert approx(bc["max_loss"], 200) and approx(bc["max_profit"], 300)  # width 5 -> 500; debit 200
    assert approx(bc["breakeven"], 102) and approx(bc["risk_reward"], 1.5)
    # bull put credit spread: sell 105p / buy 100p for $2 credit
    bp = oc.vertical_spread("bull_put", 100, 105, 2)
    assert approx(bp["max_profit"], 200) and approx(bp["max_loss"], 300)
    assert approx(bp["breakeven"], 103)               # 105 - 2
    # guard: premium can't exceed width
    assert oc.vertical_spread("bull_call", 100, 105, 6) is None
    print(f"ok  verticals (bull call R:R {bc['risk_reward']}, bull put credit max ${bp['max_profit']})")


def test_long_options():
    c = oc.long_option("call", 100, 3, stock_price=100, days=30, iv=0.5)
    assert c["max_loss"] == 300 and approx(c["breakeven"], 103) and c["max_profit"] is None
    assert 0 < c["prob_profit"] < 1
    p = oc.long_option("put", 100, 3)
    assert approx(p["max_profit"], 9700) and approx(p["breakeven"], 97)  # (100-3)*100
    print(f"ok  long options (call BE $103 PoP {c['prob_profit']*100:.0f}%, put max ${p['max_profit']})")


def test_prob_above_sanity():
    # at-the-money -> ~50%; target far above -> low
    assert approx(oc.prob_above(100, 100, 0.5, 30), 0.5, tol=0.05)
    assert oc.prob_above(100, 200, 0.3, 30) < 0.1
    assert oc.prob_above(100, 100, 0.5, 30) > oc.prob_above(100, 120, 0.5, 30)
    print("ok  probability model sane (ATM~50%, far OTM low, monotonic)")


def test_api_route():
    import main
    c = main.app.test_client()
    r = c.post("/api/stocks/strategy", json={"strategy": "covered_call",
        "stock_price": 100, "strike": 105, "premium": 2, "days": 30})
    assert r.status_code == 200 and approx(r.get_json()["max_profit"], 700)
    assert c.post("/api/stocks/strategy", json={"strategy": "nope"}).status_code == 400
    print("ok  /api/stocks/strategy route")


if __name__ == "__main__":
    test_covered_call()
    test_cash_secured_put()
    test_vertical_debit_and_credit()
    test_long_options()
    test_prob_above_sanity()
    test_api_route()
    print("\nALL PASSED")
