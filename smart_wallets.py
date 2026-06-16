"""Smart-wallet discovery — find the wallets that are early on winners.

True P&L ranking needs a paid price-history feed. The free, robust method is
"early buyer of winners": point this at a token that already pumped, and it finds
the wallets that bought it FROM the liquidity pool early (before the run). Do that
across several winners and the wallets that keep showing up early — tracked in a
persistent leaderboard — are your real smart money. You then one-click them into
the Whale Tracker.

  EVM (Etherscan): token's pool = DexScreener pairAddress; earliest transfers
  FROM that pool TO a wallet = early buys; we exclude routers/infra and dedupe.
  Solana (best-effort): GMGN "top traders" (already P&L-ranked); may be rate-
  limited — degrades gracefully.

Honest limit: "early" ≠ "smart" on a single token (could be luck). The signal is
a wallet that's early across MANY winners — which the leaderboard surfaces.
"""
import json
from pathlib import Path

from whale_tracker import _get_json, EVM_CHAINS, EXPLORER_TX
from crypto_safety import DEXSCREENER, _f

APP_DIR = Path(__file__).resolve().parent
TALLY_PATH = APP_DIR / "smart_wallets.json"

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
GMGN_TOP = "https://gmgn.ai/defi/quotation/v1/tokens/top_traders/sol/{token}"

# Addresses that are infrastructure, not buyers (lowercased). Routers vary by
# chain; this covers the zero/dead sinks + the most common Uniswap routers.
INFRA = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap V3 router 2
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",  # Uniswap universal router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 router
}


# --------------------------------------------------------------------------- #
# Pure extraction / aggregation (testable)
# --------------------------------------------------------------------------- #
def extract_early_buyers(rows, pool_address, contract, max_buyers=25):
    """From Etherscan tokentx rows (ascending time), the first wallets that
    received the token FROM the pool — i.e. early buyers. Infra excluded, deduped."""
    pool = (pool_address or "").lower()
    contract = (contract or "").lower()
    skip = INFRA | {pool, contract}
    seen, buyers = set(), []
    for r in rows or []:
        frm = (r.get("from") or "").lower()
        to = (r.get("to") or "").lower()
        if pool and frm != pool:          # only count buys sourced from the pool
            continue
        if not to or to in skip or to in seen:
            continue
        seen.add(to)
        buyers.append({"wallet": r.get("to"), "ts": int(_f(r.get("timeStamp")) or 0)})
        if len(buyers) >= max_buyers:
            break
    return buyers


def parse_gmgn_top_traders(data, max_traders=25):
    """GMGN top-traders payload -> [{wallet, pnl}] (best-effort; schema may shift)."""
    items = (data or {}).get("data")
    if isinstance(items, dict):
        items = items.get("list") or items.get("traders")
    out = []
    for t in items or []:
        addr = t.get("address") or t.get("wallet_address")
        if not addr:
            continue
        out.append({"wallet": addr, "pnl": _f(t.get("realized_profit") or t.get("profit"))})
        if len(out) >= max_traders:
            break
    return out


# --------------------------------------------------------------------------- #
# Persistent cross-token leaderboard
# --------------------------------------------------------------------------- #
def _load_tally():
    try:
        return json.loads(TALLY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_tally(tally):
    try:
        TALLY_PATH.write_text(json.dumps(tally, indent=2), encoding="utf-8")
    except OSError:
        pass


def record(wallets, token_symbol, chain, tally=None):
    """Add a token's surfaced wallets to the tally; returns the updated tally."""
    own = tally is None
    tally = _load_tally() if own else tally
    for w in wallets:
        addr = w.get("wallet")
        if not addr:
            continue
        entry = tally.setdefault(addr, {"chain": chain, "count": 0, "tokens": [], "pnl": None})
        if token_symbol and token_symbol not in entry["tokens"]:
            entry["tokens"].append(token_symbol)
        entry["count"] = len(entry["tokens"])
        if w.get("pnl") is not None:
            entry["pnl"] = round((entry.get("pnl") or 0) + w["pnl"], 2)
    if own:
        _save_tally(tally)
    return tally


def leaderboard(min_count=1, limit=50, tally=None):
    """Wallets ranked by how many analyzed winners they were early on."""
    tally = _load_tally() if tally is None else tally
    rows = [{"wallet": a, "chain": d.get("chain"), "count": d.get("count", 0),
             "tokens": d.get("tokens", []), "pnl": d.get("pnl"),
             "url": _wallet_url(a, d.get("chain"))}
            for a, d in tally.items() if d.get("count", 0) >= min_count]
    rows.sort(key=lambda r: (r["count"], r["pnl"] or 0), reverse=True)
    return rows[:limit]


def clear_tally():
    _save_tally({})


def _wallet_url(addr, chain):
    base = EXPLORER_TX.get(chain, "")
    if not base:
        return ""
    return base.replace("/tx/", "/address/") + addr


# --------------------------------------------------------------------------- #
# Live discovery
# --------------------------------------------------------------------------- #
def _best_pair(token_address):
    """(pool_address, symbol) of the token's deepest pair from DexScreener."""
    data = _get_json(DEXSCREENER.format(addr=token_address))
    pairs = (data or {}).get("pairs") or []
    if not pairs:
        return None, ""
    best = max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
    return best.get("pairAddress"), (best.get("baseToken") or {}).get("symbol", "")


def discover(token_address, chain, etherscan_key=None, helius_key=None, max_buyers=25):
    """Surface early buyers / top traders for a token. Returns (result, error)."""
    token_address = (token_address or "").strip()
    if not token_address:
        return None, "Enter a token contract address."

    pool, symbol = _best_pair(token_address)

    if chain == "solana":
        data = _get_json(GMGN_TOP.format(token=token_address))
        traders = parse_gmgn_top_traders(data)
        if not traders:
            return None, ("Solana discovery couldn't fetch top traders (the source is "
                          "rate-limited / unofficial). Try an EVM token, or add wallets manually.")
        record(traders, symbol or token_address[:6], "solana")
        return {"symbol": symbol, "chain": "solana", "wallets": traders,
                "leaderboard": leaderboard()}, None

    if chain in EVM_CHAINS:
        if not etherscan_key:
            return None, "Add a free Etherscan key (Whale Tracker tab) to discover EVM wallets."
        if not pool:
            return None, "Couldn't find this token's liquidity pool on DexScreener."
        data = _get_json(ETHERSCAN_V2, {
            "chainid": EVM_CHAINS[chain], "module": "account", "action": "tokentx",
            "contractaddress": token_address, "page": 1, "offset": 1000, "sort": "asc",
            "apikey": etherscan_key})
        rows = (data or {}).get("result")
        if not isinstance(rows, list):
            return None, (data or {}).get("message", "Etherscan returned no transfers (rate limit / key?).")
        buyers = extract_early_buyers(rows, pool, token_address, max_buyers)
        record(buyers, symbol or token_address[:6], chain)
        return {"symbol": symbol, "chain": chain, "pool": pool, "wallets": buyers,
                "leaderboard": leaderboard()}, None

    return None, f"Unsupported chain '{chain}'."
