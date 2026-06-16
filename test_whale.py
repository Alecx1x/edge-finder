"""Tests for the whale tracker. Run: python test_whale.py

Synthetic — mocks the network, ZERO real calls / keys.
"""
import whale_tracker as wt

WALLET = "0xWhale"

# Etherscan tokentx rows (value is integer string scaled by tokenDecimal)
EVM_ROWS = [
    {"hash": "0xaa", "timeStamp": "1700000200", "to": "0xwhale", "from": "0xpool",
     "value": "1500000000000000000000", "tokenDecimal": "18", "tokenSymbol": "PEPE",
     "contractAddress": "0xpepe"},  # BUY 1500 PEPE
    {"hash": "0xbb", "timeStamp": "1700000100", "to": "0xpool", "from": "0xwhale",
     "value": "500000000", "tokenDecimal": "6", "tokenSymbol": "USDC",
     "contractAddress": "0xusdc"},  # SELL/spend 500 USDC
]

# Helius parsed txs
SOL_TXS = [
    {"signature": "sig1", "timestamp": 1700000300, "tokenTransfers": [
        {"toUserAccount": "SolWhale", "fromUserAccount": "Ray", "mint": "BonkMint",
         "symbol": "BONK", "tokenAmount": 1000000}]},  # BUY BONK
    {"signature": "sig2", "timestamp": 1700000050, "tokenTransfers": [
        {"toUserAccount": "Other", "fromUserAccount": "SolWhale", "mint": "WifMint",
         "symbol": "WIF", "tokenAmount": 25}]},  # SELL WIF
]


def test_parse_evm():
    ev = wt.parse_evm_transfers(EVM_ROWS, WALLET, "ethereum")
    assert len(ev) == 2
    buy = ev[0]
    assert buy["direction"] == "in" and buy["token_symbol"] == "PEPE"
    assert abs(buy["amount"] - 1500.0) < 1e-6                  # 1e21 / 1e18
    assert ev[1]["direction"] == "out" and abs(ev[1]["amount"] - 500.0) < 1e-6  # 5e8 / 1e6
    assert ev[0]["url"].endswith("0xaa")
    print(f"ok  EVM parse (BUY 1500 PEPE / SELL 500 USDC, decimals handled)")


def test_parse_solana():
    ev = wt.parse_solana_transfers(SOL_TXS, "SolWhale")
    assert len(ev) == 2
    assert ev[0]["direction"] == "in" and ev[0]["token_symbol"] == "BONK"
    assert ev[1]["direction"] == "out" and ev[1]["token_symbol"] == "WIF"
    assert ev[0]["chain"] == "solana" and ev[0]["url"].endswith("sig1")
    print("ok  Solana parse (BONK in / WIF out)")


def test_convergence():
    base = 1700000000
    events = [
        {"direction": "in", "ts": base, "token_address": "0xT", "token_symbol": "T", "wallet": "W1", "chain": "ethereum"},
        {"direction": "in", "ts": base - 3600, "token_address": "0xT", "token_symbol": "T", "wallet": "W2", "chain": "ethereum"},
        {"direction": "in", "ts": base, "token_address": "0xU", "token_symbol": "U", "wallet": "W1", "chain": "ethereum"},
        {"direction": "out", "ts": base, "token_address": "0xT", "token_symbol": "T", "wallet": "W3", "chain": "ethereum"},
    ]
    conv = wt.detect_convergence(events)
    assert "0xt" in conv and conv["0xt"]["count"] == 2          # W1 + W2 bought T
    assert "0xu" not in conv                                    # only one wallet bought U
    print(f"ok  convergence: 2 wallets bought T (the real signal)")


def test_activity_merges_and_sorts():
    orig = wt.fetch_wallet
    feeds = {"0xWhale": (wt.parse_evm_transfers(EVM_ROWS, "0xWhale", "ethereum"), None),
             "SolWhale": (wt.parse_solana_transfers(SOL_TXS, "SolWhale"), None)}
    wt.fetch_wallet = lambda w, *a, **k: feeds[w["address"]]
    try:
        res = wt.wallet_activity([{"address": "0xWhale", "chain": "ethereum", "label": "A"},
                                  {"address": "SolWhale", "chain": "solana", "label": "B"}])
    finally:
        wt.fetch_wallet = orig
    ts = [e["ts"] for e in res["feed"]]
    assert ts == sorted(ts, reverse=True)                      # newest first
    assert any(e["wallet_label"] == "A" for e in res["feed"])  # labels attached
    print(f"ok  activity merges {len(res['feed'])} events, time-sorted, labelled")


def test_missing_key_message():
    ev, err = wt.fetch_wallet({"address": "0xX", "chain": "ethereum"}, etherscan_key="")
    assert ev == [] and "Etherscan" in err
    ev2, err2 = wt.fetch_wallet({"address": "X", "chain": "solana"}, helius_key="")
    assert ev2 == [] and "Helius" in err2
    print("ok  graceful 'add your free key' messages")


def test_routes_mocked():
    import main, config_manager as cfgmod
    # patch config accessors so the test never reads/writes the real config.json
    o_act = main.whale_tracker.wallet_activity
    o_get = cfgmod.get_whale_wallets
    o_set = cfgmod.set_whale_wallets
    saved = {}
    cfgmod.get_whale_wallets = lambda cfg: [{"address": "W", "chain": "ethereum", "label": "L"}]
    cfgmod.set_whale_wallets = lambda cfg, wl: (saved.update({"wl": wl}), cfg.__setitem__("whale_wallets", wl), True)[-1]
    main.whale_tracker.wallet_activity = lambda *a, **k: {"feed": [{"direction": "in",
        "token_symbol": "T", "wallet": "W", "wallet_label": "L", "chain": "ethereum",
        "amount": 1.0, "ts": 1, "url": "x", "token_address": "0xt"}],
        "convergence": {}, "errors": [], "n_wallets": 1}
    try:
        c = main.app.test_client()
        r = c.post("/api/crypto/activity", json={})
        assert r.status_code == 200 and r.get_json()["feed"][0]["token_symbol"] == "T"
        s = c.post("/api/crypto/wallets", json={"wallets": [{"address": "0xabc", "chain": "base", "label": "t"}]})
        assert s.status_code == 200 and saved["wl"][0]["address"] == "0xabc"
    finally:
        main.whale_tracker.wallet_activity = o_act
        cfgmod.get_whale_wallets, cfgmod.set_whale_wallets = o_get, o_set
    print("ok  /api/crypto/activity + /api/crypto/wallets routes")


if __name__ == "__main__":
    test_parse_evm()
    test_parse_solana()
    test_convergence()
    test_activity_merges_and_sorts()
    test_missing_key_message()
    test_routes_mocked()
    print("\nALL PASSED")
