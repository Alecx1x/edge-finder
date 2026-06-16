"""Tests for the meme-coin screener. Run: python test_screener.py

Synthetic — mocks DexScreener, ZERO real calls.
"""
import crypto_screener as scr


def _pair(addr, sym, chain, liq, vol, chg=0, buys=20, sells=20, created=None):
    return {"chainId": chain, "url": f"https://dexscreener.com/{chain}/{addr}",
            "priceUsd": "0.001", "liquidity": {"usd": liq}, "volume": {"h24": vol},
            "priceChange": {"h24": chg}, "txns": {"h24": {"buys": buys, "sells": sells}},
            "pairCreatedAt": created, "fdv": 1_000_000,
            "baseToken": {"address": addr, "name": sym, "symbol": sym}}


def test_build_row_hints():
    now = 1_000_000_000_000
    # thin liquidity + brand new + sell pressure
    row = scr.build_row("A", [_pair("A", "AAA", "solana", 3000, 5000, -20,
                                     buys=10, sells=40, created=now - 5 * 3_600_000)], now_ms=now)
    msgs = {h["msg"] for h in row["hints"]}
    assert "low liquidity" in msgs and "brand new" in msgs and "heavy sell pressure" in msgs, row["hints"]
    # deep-liquidity established token -> no hints
    clean = scr.build_row("B", [_pair("B", "BBB", "base", 500000, 200000, 12,
                                       buys=300, sells=250, created=now - 200 * 3_600_000)], now_ms=now)
    assert clean["hints"] == [], clean["hints"]
    print(f"ok  row hints (risky -> {sorted(msgs)}, clean -> none)")


def test_build_row_picks_deepest():
    row = scr.build_row("A", [_pair("A", "AAA", "solana", 5000, 1000),
                              _pair("A", "AAA", "solana", 90000, 40000)], now_ms=None)
    assert row["liquidity"] == 90000 and row["volume_24h"] == 40000
    print("ok  row uses deepest-liquidity pair")


def test_screen_filters_sorts(monkeypatch=None):
    boosts = [{"chainId": "solana", "tokenAddress": "A"},
              {"chainId": "ethereum", "tokenAddress": "B"},
              {"chainId": "solana", "tokenAddress": "C"},
              {"chainId": "solana", "tokenAddress": "A"}]  # dup A
    tokens = {"pairs": [
        _pair("A", "AAA", "solana", 50000, 90000),
        _pair("B", "BBB", "ethereum", 500000, 10000),
        _pair("C", "CCC", "solana", 4000, 1000)]}
    seq = [boosts, tokens]
    orig = scr._get_json
    scr._get_json = lambda url, *a, **k: seq.pop(0) if seq else None
    try:
        # all chains, sorted by volume -> A (90k vol) first
        res = scr.screen(sort="volume_24h")
        assert res["error"] is None
        assert [r["symbol"] for r in res["rows"]][0] == "AAA"
        # solana only -> excludes B
        scr._get_json = lambda url, *a, **k: {"pairs": tokens["pairs"]} if "tokens" in url else boosts
        sol = scr.screen(chain="solana")
        assert all(r["chain"] == "solana" for r in sol["rows"]) and len(sol["rows"]) == 2  # A, C (dedup)
        # min liquidity filters out C (4k)
        scr._get_json = lambda url, *a, **k: {"pairs": tokens["pairs"]} if "tokens" in url else boosts
        rich = scr.screen(chain="solana", min_liquidity=10000)
        assert [r["symbol"] for r in rich["rows"]] == ["AAA"]
    finally:
        scr._get_json = orig
    print("ok  screen() chain filter + min-liq + sort + dedup")


def test_route_mocked():
    import main
    orig = main.crypto_screener.screen
    main.crypto_screener.screen = lambda **k: {"rows": [
        {"symbol": "AAA", "chain": "solana", "address": "A", "liquidity": 50000,
         "volume_24h": 90000, "price_change_24h": 12, "hints": [], "url": "x"}], "error": None}
    try:
        c = main.app.test_client()
        r = c.post("/api/crypto/screen", json={"chain": "solana", "sort": "volume_24h"})
        assert r.status_code == 200 and r.get_json()["rows"][0]["symbol"] == "AAA"
    finally:
        main.crypto_screener.screen = orig
    print("ok  /api/crypto/screen route (mocked - no network)")


if __name__ == "__main__":
    test_build_row_hints()
    test_build_row_picks_deepest()
    test_screen_filters_sorts()
    test_route_mocked()
    print("\nALL PASSED")
