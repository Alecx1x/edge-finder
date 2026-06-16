"""Tests for the insider-buying tracker. Run: python test_insider.py

Synthetic Form 4 XML; route mocked. No real SEC calls.
"""
import insider as ins


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _form4(owner, code, shares, price, ad="A", title="CEO", director="1"):
    return f"""<ownershipDocument>
      <issuer><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
      <reportingOwner>
        <reportingOwnerId><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>{title}</officerTitle><isDirector>{director}</isDirector></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionDate><value>2026-06-01</value></transactionDate>
        <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>{shares}</value></transactionShares>
          <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
          <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""


def test_parse_buy():
    p = ins.parse_form4(_form4("Doe John", "P", 1000, "50.00"))
    assert p["owner"] == "Doe John" and "CEO" in p["role"] and "Director" in p["role"]
    t = p["transactions"][0]
    assert t["is_buy"] and t["label"] == "buy" and approx(t["value"], 50000)
    print(f"ok  parse open-market BUY ({t['shares']:.0f} @ ${t['price']} = ${t['value']:,.0f}, role {p['role']})")


def test_parse_sell_and_grant():
    sell = ins.parse_form4(_form4("Sell Sara", "S", 200, "60", ad="D"))["transactions"][0]
    assert sell["is_sell"] and not sell["is_buy"] and sell["label"] == "sell"
    grant = ins.parse_form4(_form4("Grant Greg", "A", 500, "0"))["transactions"][0]
    assert grant["label"] == "grant" and not grant["is_buy"]   # awards aren't real buys
    print("ok  sells + grants classified separately (not counted as buys)")


def test_extract_from_submission_txt():
    txt = "SEC-HEADER junk...\n<DOCUMENT><TYPE>4<XML>\n" + _form4("X", "P", 1, "1") + "\n</XML></DOCUMENT> trailing"
    xml = ins.extract_ownership_xml(txt)
    assert xml and xml.startswith("<ownershipDocument>") and xml.endswith("</ownershipDocument>")
    assert ins.parse_form4(xml)["transactions"][0]["is_buy"]
    print("ok  ownershipDocument extracted from full-submission .txt")


def test_summarize():
    txns = [
        {"is_buy": True, "is_sell": False, "value": 50000, "owner": "A"},
        {"is_buy": True, "is_sell": False, "value": 30000, "owner": "B"},
        {"is_buy": False, "is_sell": True, "value": 20000, "owner": "C"},
        {"is_buy": False, "is_sell": False, "value": 9999, "owner": "D"},  # grant -> ignored
    ]
    s = ins.summarize(txns)
    assert s["buy_value"] == 80000 and s["sell_value"] == 20000 and s["net_value"] == 60000
    assert s["n_buys"] == 2 and s["n_buyers"] == 2 and s["n_sells"] == 1
    print(f"ok  summarize (net insider buying ${s['net_value']:,.0f}, {s['n_buyers']} buyers)")


def test_route_mocked():
    import main
    orig = main.insider.insider_activity
    main.insider.insider_activity = lambda t, **k: ({"ticker": t.upper(), "company": "Acme",
        "transactions": [{"date": "2026-06-01", "label": "buy", "is_buy": True, "is_sell": False,
                          "shares": 1000, "price": 50, "value": 50000, "owner": "Doe", "role": "CEO"}],
        "summary": {"buy_value": 50000, "sell_value": 0, "net_value": 50000, "n_buys": 1, "n_sells": 0, "n_buyers": 1},
        "cik": "0000000001", "filings_scanned": 1}, None)
    try:
        c = main.app.test_client()
        r = c.post("/api/stocks/insider", json={"ticker": "acme"})
        assert r.status_code == 200 and r.get_json()["summary"]["net_value"] == 50000
        assert c.post("/api/stocks/insider", json={"ticker": ""}).status_code == 400
    finally:
        main.insider.insider_activity = orig
    print("ok  /api/stocks/insider route")


if __name__ == "__main__":
    test_parse_buy()
    test_parse_sell_and_grant()
    test_extract_from_submission_txt()
    test_summarize()
    test_route_mocked()
    print("\nALL PASSED")
