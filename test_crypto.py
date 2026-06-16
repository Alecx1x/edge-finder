"""Tests for the crypto token safety checker. Run: python test_crypto.py

Synthetic — feeds canned GoPlus / DexScreener shapes to the parsers and mocks the
network for the route. ZERO real API calls.
"""
import crypto_safety as cs


# --- synthetic GoPlus EVM responses --------------------------------------- #
EVM_HONEYPOT = {"code": 1, "result": {"0xabc": {
    "token_name": "ScamCoin", "token_symbol": "SCAM",
    "is_honeypot": "1", "cannot_sell_all": "1", "buy_tax": "0", "sell_tax": "0.99",
    "is_mintable": "1", "can_take_back_ownership": "1", "hidden_owner": "1",
    "is_open_source": "0", "transfer_pausable": "1",
    "holders": [{"percent": "0.55"}, {"percent": "0.10"}], "holder_count": "12"}}}

EVM_CLEAN = {"code": 1, "result": {"0xdef": {
    "token_name": "OkToken", "token_symbol": "OK",
    "is_honeypot": "0", "cannot_sell_all": "0", "buy_tax": "0.02", "sell_tax": "0.02",
    "is_mintable": "0", "can_take_back_ownership": "0", "hidden_owner": "0",
    "is_open_source": "1", "transfer_pausable": "0",
    "holders": [{"percent": "0.08"}, {"percent": "0.05"}], "holder_count": "8400"}}}

SOL_MINT_FREEZE = {"code": 1, "result": {"So111": {
    "metadata": {"name": "SolMeme", "symbol": "SMEME"},
    "mintable": {"status": "1"}, "freezable": {"status": "1"},
    "non_transferable": "0", "balance_mutable_authority": {"status": "0"},
    "holders": [{"percent": "0.20"}]}}}

DEX_OK = {"pairs": [
    {"dexId": "uniswap", "chainId": "ethereum", "priceUsd": "0.0123",
     "liquidity": {"usd": 250000}, "volume": {"h24": 80000}, "fdv": 1200000,
     "pairCreatedAt": 1_700_000_000_000, "baseToken": {"name": "OkToken", "symbol": "OK"}},
    {"dexId": "sushiswap", "chainId": "ethereum", "priceUsd": "0.0124",
     "liquidity": {"usd": 9000}, "volume": {"h24": 2000}}]}
DEX_THIN = {"pairs": [{"dexId": "ray", "chainId": "solana", "priceUsd": "0.0001",
     "liquidity": {"usd": 3500}, "volume": {"h24": 500}, "baseToken": {"symbol": "SMEME"}}]}


def test_evm_honeypot_is_avoid():
    flags = cs.parse_security_evm(EVM_HONEYPOT["result"]["0xabc"])
    assert flags["honeypot"] and flags["cannot_sell"] and flags["mintable"]
    rep = cs.score_report(flags, {})
    assert rep["level"] == "avoid"
    msgs = " ".join(f["msg"] for f in rep["red_flags"])
    assert "CANNOT SELL" in msgs and any(f["severity"] == "critical" for f in rep["red_flags"])
    print(f"ok  EVM honeypot -> AVOID ({len(rep['red_flags'])} flags)")


def test_evm_clean_is_clear():
    flags = cs.parse_security_evm(EVM_CLEAN["result"]["0xdef"])
    rep = cs.score_report(flags, cs.parse_market(DEX_OK))
    assert rep["level"] == "clear" and not rep["red_flags"], rep
    print("ok  EVM clean token -> no major red flags")


def test_deep_liquidity_pair_chosen():
    m = cs.parse_market(DEX_OK)
    assert m["liquidity"] == 250000 and m["dex"] == "uniswap"   # not the 9k sushi pair
    print(f"ok  market picks deepest pair (${m['liquidity']:,.0f})")


def test_solana_mint_and_freeze_flagged():
    flags = cs.parse_security_solana(SOL_MINT_FREEZE["result"]["So111"])
    assert flags["mintable"] and flags["freezable"] and flags["symbol"] == "SMEME"
    rep = cs.score_report(flags, cs.parse_market(DEX_THIN))
    msgs = " ".join(f["msg"] for f in rep["red_flags"])
    assert "Freeze authority" in msgs and "Mint authority" in msgs and "liquidity" in msgs
    assert rep["level"] in ("high", "elevated")
    print(f"ok  Solana mint+freeze+thin-liq -> {rep['level'].upper()} ({len(rep['red_flags'])} flags)")


def test_low_liquidity_flag():
    rep = cs.score_report({}, {"liquidity": 3500})
    assert any("liquidity" in f["msg"] for f in rep["red_flags"])
    print("ok  low-liquidity flag fires")


def test_new_token_note():
    rep = cs.score_report({}, {"pair_created_ms": 1000, "liquidity": 50000},
                          now_ms=1000 + 6 * 3_600_000)  # 6h old
    assert any("Brand new" in n for n in rep["notes"])
    print("ok  brand-new-token note fires")


def test_route_mocked():
    import main
    orig = main.crypto_safety.assess
    main.crypto_safety.assess = lambda addr, chain, now_ms=None: (
        {"address": addr, "chain": chain, "verdict": "AVOID — looks like a trap",
         "level": "avoid", "red_flags": [{"msg": "Honeypot", "severity": "critical"}],
         "notes": [], "flags": {}, "market": {}}, None)
    try:
        c = main.app.test_client()
        r = c.post("/api/crypto/token", json={"address": "0xabc", "chain": "ethereum"})
        assert r.status_code == 200 and r.get_json()["level"] == "avoid"
        assert c.post("/api/crypto/token", json={"address": ""}).status_code in (200, 400)
    finally:
        main.crypto_safety.assess = orig
    print("ok  /api/crypto/token route (mocked - no network)")


if __name__ == "__main__":
    test_evm_honeypot_is_avoid()
    test_evm_clean_is_clear()
    test_deep_liquidity_pair_chosen()
    test_solana_mint_and_freeze_flagged()
    test_low_liquidity_flag()
    test_new_token_note()
    test_route_mocked()
    print("\nALL PASSED")
