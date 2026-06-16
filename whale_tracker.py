"""Whale-wallet tracker — follow the wallets that are early and right.

The deepest "smart money" signal in crypto: blockchains are public, so you can
literally watch big wallets move. You keep a watchlist of wallet addresses (ones
you found from a token's top holders, a smart-money list, etc.); this pulls each
wallet's recent token transfers and shows a unified, time-sorted feed of what
they're BUYING (token in) and SELLING (token out) — and flags CONVERGENCE, when
several watched wallets bought the same token recently (the strongest tell).

Free, key-based data:
  - EVM (Ethereum / Base / BSC / Arbitrum): Etherscan v2 unified API (one free key,
    `account&action=tokentx`).
  - Solana: Helius parsed-transactions API (free key).

Honest framing: this FOLLOWS wallets you choose — it doesn't yet *find* smart
wallets for you (that needs historical P&L per wallet, a bigger build). Garbage
wallets in → garbage feed out; curate your watchlist.
"""
import requests

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HELIUS_TX = "https://api.helius.xyz/v0/addresses/{address}/transactions"

EVM_CHAINS = {"ethereum": 1, "base": 8453, "bsc": 56, "arbitrum": 42161,
              "polygon": 137, "optimism": 10}
EXPLORER_TX = {
    "ethereum": "https://etherscan.io/tx/", "base": "https://basescan.org/tx/",
    "bsc": "https://bscscan.com/tx/", "arbitrum": "https://arbiscan.io/tx/",
    "polygon": "https://polygonscan.com/tx/", "optimism": "https://optimistic.etherscan.io/tx/",
    "solana": "https://solscan.io/tx/",
}

_UA = {"User-Agent": "money-lab/1.0 (+local research tool)"}


def _get_json(url, params=None, timeout=15):
    try:
        r = requests.get(url, params=params, headers=_UA, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Parsers (testable on synthetic JSON)
# --------------------------------------------------------------------------- #
def parse_evm_transfers(rows, address, chain, limit=25):
    """Etherscan tokentx rows -> normalized transfer events."""
    me = (address or "").lower()
    out = []
    for r in rows or []:
        dec = int(_num(r.get("tokenDecimal")) or 18)
        raw = _num(r.get("value"))
        amount = (raw / (10 ** dec)) if raw is not None else None
        to = (r.get("to") or "").lower()
        ts = int(_num(r.get("timeStamp")) or 0)
        out.append({
            "wallet": address, "chain": chain,
            "direction": "in" if to == me else "out",
            "token_symbol": r.get("tokenSymbol", ""),
            "token_address": r.get("contractAddress", ""),
            "amount": amount, "ts": ts,
            "tx_hash": r.get("hash", ""),
            "url": EXPLORER_TX.get(chain, "") + r.get("hash", ""),
        })
        if len(out) >= limit:
            break
    return out


def parse_solana_transfers(txs, address, limit=25):
    """Helius parsed transactions -> normalized transfer events (token transfers)."""
    out = []
    for tx in txs or []:
        ts = int(_num(tx.get("timestamp")) or 0)
        sig = tx.get("signature", "")
        for t in tx.get("tokenTransfers", []) or []:
            to = t.get("toUserAccount", "")
            frm = t.get("fromUserAccount", "")
            if address not in (to, frm):
                continue
            out.append({
                "wallet": address, "chain": "solana",
                "direction": "in" if to == address else "out",
                "token_symbol": t.get("symbol") or (t.get("mint", "")[:4] + "…"),
                "token_address": t.get("mint", ""),
                "amount": _num(t.get("tokenAmount")), "ts": ts,
                "tx_hash": sig, "url": EXPLORER_TX["solana"] + sig,
            })
            if len(out) >= limit:
                return out
    return out


def detect_convergence(events, window_hours=72, min_wallets=2):
    """Tokens that >= min_wallets DISTINCT wallets bought (direction 'in') recently.

    Returns {token_address: {symbol, wallets:set, count}} — the strongest signal.
    """
    if not events:
        return {}
    newest = max(e["ts"] for e in events)
    cutoff = newest - window_hours * 3600
    acc = {}
    for e in events:
        if e["direction"] != "in" or e["ts"] < cutoff or not e["token_address"]:
            continue
        key = e["token_address"].lower()
        a = acc.setdefault(key, {"symbol": e["token_symbol"], "wallets": set(), "chain": e["chain"]})
        a["wallets"].add(e["wallet"])
    return {k: {"symbol": v["symbol"], "chain": v["chain"], "count": len(v["wallets"])}
            for k, v in acc.items() if len(v["wallets"]) >= min_wallets}


# --------------------------------------------------------------------------- #
# Live fetchers
# --------------------------------------------------------------------------- #
def fetch_wallet(wallet, etherscan_key=None, helius_key=None, limit=25):
    """Fetch one watched wallet's recent transfers. Returns (events, error)."""
    addr = wallet.get("address", "")
    chain = wallet.get("chain", "ethereum")
    if chain == "solana":
        if not helius_key:
            return [], "Add a free Helius key to track Solana wallets."
        data = _get_json(HELIUS_TX.format(address=addr),
                         {"api-key": helius_key, "limit": limit})
        if not isinstance(data, list):
            return [], "Helius returned no data (check the address / key)."
        return parse_solana_transfers(data, addr, limit), None
    if chain in EVM_CHAINS:
        if not etherscan_key:
            return [], "Add a free Etherscan key to track EVM wallets."
        data = _get_json(ETHERSCAN_V2, {
            "chainid": EVM_CHAINS[chain], "module": "account", "action": "tokentx",
            "address": addr, "page": 1, "offset": limit, "sort": "desc",
            "apikey": etherscan_key})
        if not data or str(data.get("status")) == "0" and not data.get("result"):
            return [], (data or {}).get("message", "No transfers found.")
        result = data.get("result")
        if not isinstance(result, list):
            return [], "Etherscan returned no transfer list (rate limit or bad key?)."
        return parse_evm_transfers(result, addr, chain, limit), None
    return [], f"Unsupported chain '{chain}'."


def wallet_activity(wallets, etherscan_key=None, helius_key=None, per_wallet=20):
    """Fetch all watched wallets, merge + time-sort, detect convergence."""
    feed, errors = [], []
    label_by_addr = {w["address"]: w.get("label", "") for w in wallets}
    for w in wallets:
        events, err = fetch_wallet(w, etherscan_key, helius_key, per_wallet)
        if err:
            errors.append({"wallet": w["address"], "label": w.get("label", ""), "error": err})
        for e in events:
            e["wallet_label"] = label_by_addr.get(e["wallet"], "")
        feed.extend(events)
    feed.sort(key=lambda e: e["ts"], reverse=True)
    convergence = detect_convergence(feed)
    return {"feed": feed, "convergence": convergence, "errors": errors,
            "n_wallets": len(wallets)}


if __name__ == "__main__":
    import config_manager as cfgmod
    cfg = cfgmod.load_config()
    res = wallet_activity(cfgmod.get_whale_wallets(cfg),
                          cfgmod.get_chain_key("etherscan"), cfgmod.get_chain_key("helius"))
    print(f"{len(res['feed'])} events from {res['n_wallets']} wallets; "
          f"{len(res['convergence'])} convergence tokens; {len(res['errors'])} errors")
    for e in res["feed"][:20]:
        arrow = "BUY " if e["direction"] == "in" else "SELL"
        print(f"  {arrow} {e['token_symbol']:<10} {e.get('wallet_label') or e['wallet'][:8]} ({e['chain']})")
