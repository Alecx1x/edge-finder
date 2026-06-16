"""Tests for the Yahoo stock/options parsers. Run: python test_stockdata.py

Synthetic — feeds canned Yahoo shapes to the parsers; route mocked. No real calls.
"""
import stock_data as sd


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


CHART = {"chart": {"result": [{"meta": {
    "symbol": "AAPL", "shortName": "Apple Inc.", "regularMarketPrice": 220.5,
    "previousClose": 218.0, "currency": "USD"}}]}}

def _occ(strike, cp, exp="260608"):
    return "AAPL" + exp + cp + f"{int(strike*1000):08d}"

OPTIONS = {"data": {"symbol": "AAPL", "close": 220.0, "options": [
    {"option": _occ(215, "C"), "last_trade_price": 7.5, "bid": 7.4, "ask": 7.6,
     "iv": 0.31, "delta": 0.62, "volume": 1200, "open_interest": 5400},
    {"option": _occ(215, "P"), "last_trade_price": 2.1, "bid": 2.0, "ask": 2.2,
     "iv": 0.29, "delta": -0.38, "volume": 800, "open_interest": 3000},
    {"option": _occ(225, "C", "260712"), "last_trade_price": 3.0, "bid": 2.9, "ask": 3.1,
     "iv": 0.33, "volume": 50, "open_interest": 900}]}}


def test_parse_quote():
    q = sd.parse_quote(CHART)
    assert q["symbol"] == "AAPL" and approx(q["price"], 220.5)
    assert approx(q["change"], 2.5) and approx(q["change_pct"], round(2.5 / 218.0, 4))
    assert sd.parse_quote({"bad": 1}) is None
    print(f"ok  quote parse (AAPL ${q['price']}, +{q['change']})")


def test_parse_occ():
    exp, cp, strike = sd._parse_occ("AAPL260608C00250000")
    assert exp == "2026-06-08" and cp == "C" and approx(strike, 250.0)
    print(f"ok  OCC symbol parse (-> {exp} {cp} {strike})")


def test_parse_options():
    c = sd.parse_options(OPTIONS)
    assert c["symbol"] == "AAPL" and len(c["expirations"]) == 2     # 2 distinct expiries
    assert c["selected_label"] == "2026-06-08"                      # earliest first
    call = c["calls"][0]
    assert approx(call["strike"], 215) and approx(call["iv"], 0.31) and approx(call["delta"], 0.62)
    assert call["itm"] is True and call["open_interest"] == 5400    # 215 call, price 220 -> ITM
    assert c["puts"][0]["itm"] is False                             # 215 put, price 220 -> OTM
    # selecting the later expiry returns its single call
    c2 = sd.parse_options(OPTIONS, expiry="2026-07-12")
    assert len(c2["calls"]) == 1 and approx(c2["calls"][0]["strike"], 225)
    print(f"ok  options parse (IV+delta+ITM, expiry switch works)")


def test_near_the_money_trim():
    rows = [{"option": _occ(s, "C"), "last_trade_price": 1} for s in range(50, 200)]
    many = {"data": {"symbol": "X", "close": 100, "options": rows}}
    c = sd.parse_options(many, max_strikes=60)
    assert len(c["calls"]) == 60
    strikes = [r["strike"] for r in c["calls"]]
    assert strikes == sorted(strikes)
    print(f"ok  near-the-money trim (150 -> {len(c['calls'])}, sorted)")


def test_routes_mocked():
    import main
    o_q, o_o = main.stock_data.quote, main.stock_data.options_chain
    main.stock_data.quote = lambda t: ({"symbol": t.upper(), "price": 220.5, "change": 2.5}, None)
    main.stock_data.options_chain = lambda t, expiry=None: ({"symbol": t.upper(), "price": 220.0,
        "expirations": [{"epoch": 1, "label": "2023-11-14"}], "calls": [], "puts": []}, None)
    try:
        c = main.app.test_client()
        assert c.post("/api/stocks/quote", json={"ticker": "aapl"}).get_json()["price"] == 220.5
        assert c.post("/api/stocks/options", json={"ticker": "aapl"}).get_json()["symbol"] == "AAPL"
        assert c.post("/api/stocks/quote", json={"ticker": ""}).status_code == 400
    finally:
        main.stock_data.quote, main.stock_data.options_chain = o_q, o_o
    print("ok  /api/stocks/quote + /api/stocks/options routes")


if __name__ == "__main__":
    test_parse_quote()
    test_parse_occ()
    test_parse_options()
    test_near_the_money_trim()
    test_routes_mocked()
    print("\nALL PASSED")
