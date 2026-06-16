"""Meme-coin screener — surface trending tokens with risk hints baked in.

The "offense" tool that pairs with crypto_safety's "defense". It pulls the tokens
people are actively pushing (DexScreener "boosts" = paid promotion, a rough but
real attention signal), batches their market data, and shows price / liquidity /
volume / 24h change / age plus quick FREE risk hints (no/low liquidity, brand new,
heavy sell pressure). It does NOT pull the full contract security per row (that
would hammer GoPlus) — instead each row gets a one-click Check that runs the full
crypto_safety report on demand.

Two DexScreener calls per scan (boosts list + one batched token-data request), no
key, no quota. Honest framing: trending ≠ good. Most of these are pump-and-dumps;
the screener helps you see them fast and vet them, not trust them.
"""
from collections import defaultdict

from crypto_safety import _get_json, _f, CHAINS

BOOSTS_LATEST = "https://api.dexscreener.com/token-boosts/latest/v1"
BOOSTS_TOP = "https://api.dexscreener.com/token-boosts/top/v1"
TOKENS = "https://api.dexscreener.com/latest/dex/tokens/{addrs}"

MAX_TOKENS = 30   # DexScreener tokens endpoint accepts up to 30 addresses


def _best_pair(pairs):
    """Deepest-liquidity pair from a list."""
    if not pairs:
        return None
    return max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))


def build_row(address, pairs, now_ms=None):
    """Build one screener row from all DexScreener pairs for a token address."""
    best = _best_pair(pairs)
    if not best:
        return None
    liq = _f((best.get("liquidity") or {}).get("usd"))
    vol = _f((best.get("volume") or {}).get("h24"))
    chg = _f((best.get("priceChange") or {}).get("h24"))
    txns = (best.get("txns") or {}).get("h24") or {}
    buys, sells = _f(txns.get("buys")) or 0, _f(txns.get("sells")) or 0
    created = best.get("pairCreatedAt")
    base = best.get("baseToken") or {}

    hints = []
    if liq is None or liq == 0:
        hints.append({"msg": "no liquidity", "severity": "high"})
    elif liq < 10000:
        hints.append({"msg": "low liquidity", "severity": "high"})
    if created and now_ms and (now_ms - created) / 3.6e6 < 24:
        hints.append({"msg": "brand new", "severity": "medium"})
    if buys >= 10 and sells > buys * 2:
        hints.append({"msg": "heavy sell pressure", "severity": "high"})

    return {
        "address": address, "chain": best.get("chainId"),
        "name": base.get("name", ""), "symbol": base.get("symbol", ""),
        "price_usd": _f(best.get("priceUsd")), "liquidity": liq, "volume_24h": vol,
        "price_change_24h": chg, "fdv": _f(best.get("fdv")),
        "pair_created_ms": created, "buys_24h": int(buys), "sells_24h": int(sells),
        "url": best.get("url"), "hints": hints,
    }


def screen(chain=None, source="latest", min_liquidity=0.0, sort="volume_24h",
           limit=30, now_ms=None):
    """Return trending tokens as screener rows. chain=None means all chains."""
    boosts = _get_json(BOOSTS_TOP if source == "top" else BOOSTS_LATEST)
    if not isinstance(boosts, list):
        return {"rows": [], "error": "Could not reach DexScreener."}

    # candidate (chain, address) pairs, filtered by chain, de-duped, capped
    seen, candidates = set(), []
    for b in boosts:
        addr = b.get("tokenAddress")
        ch = b.get("chainId")
        if not addr or addr in seen:
            continue
        if chain and chain != "all" and ch != chain:
            continue
        seen.add(addr)
        candidates.append(addr)
        if len(candidates) >= MAX_TOKENS:
            break
    if not candidates:
        return {"rows": [], "error": None}

    data = _get_json(TOKENS.format(addrs=",".join(candidates)))
    by_addr = defaultdict(list)
    for p in (data or {}).get("pairs", []) or []:
        a = (p.get("baseToken") or {}).get("address")
        if a:
            by_addr[a].append(p)

    rows = []
    for addr in candidates:
        # DexScreener may key addresses with different casing on EVM
        pairs = by_addr.get(addr) or by_addr.get(addr.lower()) or []
        row = build_row(addr, pairs, now_ms=now_ms)
        if row and (min_liquidity <= 0 or (row["liquidity"] or 0) >= min_liquidity):
            rows.append(row)

    key = sort if sort in ("volume_24h", "liquidity", "price_change_24h", "pair_created_ms") else "volume_24h"
    rows.sort(key=lambda r: (r.get(key) or 0), reverse=True)
    return {"rows": rows[:limit], "error": None}


if __name__ == "__main__":
    import time
    res = screen(now_ms=int(time.time() * 1000))
    print(f"{len(res['rows'])} tokens" + (f"  ({res['error']})" if res["error"] else ""))
    for r in res["rows"][:15]:
        h = ",".join(x["msg"] for x in r["hints"]) or "-"
        print(f"  {r['symbol']:<10} {r['chain']:<9} liq ${r['liquidity'] or 0:>12,.0f}  "
              f"vol ${r['volume_24h'] or 0:>12,.0f}  24h {r['price_change_24h'] or 0:>6.1f}%  [{h}]")
