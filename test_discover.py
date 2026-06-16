"""Tests for smart-wallet discovery. Run: python test_discover.py

Synthetic — mocks network, redirects the tally to a temp file. ZERO real calls.
"""
from pathlib import Path

import smart_wallets as sw

POOL = "0xPool"
CONTRACT = "0xToken"


def _tx(frm, to, ts):
    return {"from": frm, "to": to, "timeStamp": str(ts), "contractAddress": CONTRACT}


def test_extract_early_buyers():
    rows = [
        _tx("0xPool", "0xAAA", 100),                # buy 1
        _tx("0xPool", "0x7a250d5630b4cf539739df2c5dacb4c659f2488d", 101),  # router -> skip
        _tx("0xAAA", "0xBBB", 102),                 # wallet->wallet (not from pool) -> skip
        _tx("0xPool", "0xCCC", 103),                # buy 2
        _tx("0xPool", "0xAAA", 104),                # dup AAA -> skip
        _tx("0xPool", "0xPool", 105),               # pool self -> skip
    ]
    buyers = sw.extract_early_buyers(rows, POOL, CONTRACT)
    addrs = [b["wallet"] for b in buyers]
    assert addrs == ["0xAAA", "0xCCC"], addrs          # ordered, infra/dups/non-pool filtered
    assert buyers[0]["ts"] == 100
    print(f"ok  early buyers extracted in order, infra/dupes/non-pool filtered ({addrs})")


def test_gmgn_parse():
    data = {"data": {"list": [{"address": "Sol1", "realized_profit": 1200.5},
                              {"wallet_address": "Sol2", "profit": -50}]}}
    out = sw.parse_gmgn_top_traders(data)
    assert out[0]["wallet"] == "Sol1" and out[0]["pnl"] == 1200.5
    assert out[1]["wallet"] == "Sol2" and out[1]["pnl"] == -50
    print("ok  GMGN top-traders parse (both schema shapes)")


def test_tally_ranks_by_appearances():
    tally = {}
    # WIN1: A, B early.  WIN2: A, C early.  WIN3: A early.
    sw.record([{"wallet": "A"}, {"wallet": "B"}], "WIN1", "ethereum", tally)
    sw.record([{"wallet": "A"}, {"wallet": "C"}], "WIN2", "ethereum", tally)
    sw.record([{"wallet": "A"}], "WIN3", "ethereum", tally)
    lb = sw.leaderboard(tally=tally)
    assert lb[0]["wallet"] == "A" and lb[0]["count"] == 3      # A early on all 3 winners
    assert set(lb[0]["tokens"]) == {"WIN1", "WIN2", "WIN3"}
    assert [r["wallet"] for r in lb][:1] == ["A"]
    # re-recording the same token doesn't double count
    sw.record([{"wallet": "A"}], "WIN3", "ethereum", tally)
    assert next(r for r in sw.leaderboard(tally=tally) if r["wallet"] == "A")["count"] == 3
    print(f"ok  leaderboard ranks A #1 (early on 3 winners), no double-count")


def test_pnl_accumulates():
    tally = {}
    sw.record([{"wallet": "S", "pnl": 1000}], "T1", "solana", tally)
    sw.record([{"wallet": "S", "pnl": 500}], "T2", "solana", tally)
    assert tally["S"]["pnl"] == 1500
    print("ok  Solana PnL accumulates across tokens")


def _with_temp_tally(fn):
    orig = sw.TALLY_PATH
    sw.TALLY_PATH = Path(sw.APP_DIR) / "_test_tally.json"
    try:
        if sw.TALLY_PATH.exists():
            sw.TALLY_PATH.unlink()
        fn()
    finally:
        if sw.TALLY_PATH.exists():
            sw.TALLY_PATH.unlink()
        sw.TALLY_PATH = orig


def test_routes_mocked():
    def body():
        import main
        o_disc = main.smart_wallets.discover
        main.smart_wallets.discover = lambda token, chain, *a, **k: (
            {"symbol": "WIN", "chain": chain, "wallets": [{"wallet": "A", "ts": 1}],
             "leaderboard": [{"wallet": "A", "chain": chain, "count": 1, "tokens": ["WIN"], "pnl": None, "url": "x"}]}, None)
        try:
            c = main.app.test_client()
            r = c.post("/api/crypto/discover", json={"address": "0xToken", "chain": "ethereum"})
            assert r.status_code == 200 and r.get_json()["wallets"][0]["wallet"] == "A"
            assert c.get("/api/crypto/leaderboard").status_code == 200
            assert c.post("/api/crypto/leaderboard/clear").get_json()["ok"] is True
        finally:
            main.smart_wallets.discover = o_disc
        print("ok  /api/crypto/discover + /leaderboard (+clear) routes")
    _with_temp_tally(body)


if __name__ == "__main__":
    test_extract_early_buyers()
    test_gmgn_parse()
    test_tally_ranks_by_appearances()
    test_pnl_accumulates()
    test_routes_mocked()
    print("\nALL PASSED")
