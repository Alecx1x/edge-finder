"""Crypto token safety checker — the defense tool for meme coins.

Meme coins are mostly traps. Before you ape in, this checks the contract for the
ways you get rugged:
  - honeypot (you can buy but can't sell)
  - confiscatory buy/sell taxes
  - mintable supply / active mint authority (they print more and dump)
  - freeze authority (they freeze YOUR tokens) — Solana
  - owner can reclaim control / hidden owner / pausable transfers
  - whale-concentrated holders, and dangerously thin liquidity

Data is free and key-less: GoPlus Security (contract risk, EVM + Solana) and
DexScreener (price, liquidity, volume, age). It does NOT tell you a coin is a good
buy — nothing can. It tells you whether it's an obvious trap, so you don't lose
money you didn't have to.
"""
import requests

GOPLUS_EVM = "https://api.gopluslabs.io/api/v1/token_security/{chain}"
GOPLUS_SOL = "https://api.gopluslabs.io/api/v1/solana/token_security"
DEXSCREENER = "https://api.dexscreener.com/latest/dex/tokens/{addr}"

# friendly name -> GoPlus chain id ("solana" routes to the Solana endpoint)
CHAINS = {
    "ethereum": "1", "bsc": "56", "base": "8453", "arbitrum": "42161",
    "polygon": "137", "optimism": "10", "avalanche": "43114", "solana": "solana",
}

_UA = {"User-Agent": "money-lab/1.0 (+local research tool)"}


def _get_json(url, params=None, timeout=12):
    try:
        r = requests.get(url, params=params, headers=_UA, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _f(v):
    """Lenient float ('' / None / '0.05' -> float|None)."""
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _truthy(v):
    return str(v) == "1" or v is True


# --------------------------------------------------------------------------- #
# Parsers — take the inner token dict, return normalized flags
# --------------------------------------------------------------------------- #
def parse_security_evm(t):
    holders = t.get("holders") or []
    top = max((_f(h.get("percent")) or 0.0 for h in holders), default=None)
    return {
        "name": t.get("token_name", ""), "symbol": t.get("token_symbol", ""),
        "honeypot": _truthy(t.get("is_honeypot")),
        "cannot_sell": _truthy(t.get("cannot_sell_all")),
        "buy_tax": _f(t.get("buy_tax")), "sell_tax": _f(t.get("sell_tax")),
        "mintable": _truthy(t.get("is_mintable")),
        "freezable": False,
        "owner_reclaim": _truthy(t.get("can_take_back_ownership")),
        "hidden_owner": _truthy(t.get("hidden_owner")),
        "transfer_pausable": _truthy(t.get("transfer_pausable")),
        "open_source": (None if t.get("is_open_source") in (None, "")
                        else _truthy(t.get("is_open_source"))),
        "top_holder_pct": top,
        "holder_count": t.get("holder_count"),
    }


def parse_security_solana(t):
    def auth_active(node):
        # Solana fields are nested like {"status": "1", "authority": [...]}
        if isinstance(node, dict):
            return _truthy(node.get("status"))
        return _truthy(node)

    meta = t.get("metadata") or {}
    holders = t.get("holders") or []
    top = max((_f(h.get("percent")) or 0.0 for h in holders), default=None)
    transfer_fee = t.get("transfer_fee")
    sell_tax = None
    if isinstance(transfer_fee, dict):
        sell_tax = _f(transfer_fee.get("current_fee_rate"))
    return {
        "name": meta.get("name", ""), "symbol": meta.get("symbol", ""),
        "honeypot": _truthy(t.get("non_transferable")),
        "cannot_sell": _truthy(t.get("non_transferable")),
        "buy_tax": None, "sell_tax": sell_tax,
        "mintable": auth_active(t.get("mintable")),
        "freezable": auth_active(t.get("freezable")),
        "owner_reclaim": auth_active(t.get("balance_mutable_authority")),
        "hidden_owner": False,
        "transfer_pausable": _truthy(t.get("default_account_state_upgradable")),
        "open_source": None,
        "top_holder_pct": top,
        "holder_count": t.get("holder_count"),
    }


def parse_market(dex_json):
    """Pick the deepest-liquidity pair from a DexScreener token response."""
    pairs = (dex_json or {}).get("pairs") or []
    if not pairs:
        return {}
    best = max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
    liq = (best.get("liquidity") or {}).get("usd")
    created = best.get("pairCreatedAt")  # ms epoch
    return {
        "price_usd": _f(best.get("priceUsd")),
        "liquidity": _f(liq),
        "volume_24h": _f((best.get("volume") or {}).get("h24")),
        "fdv": _f(best.get("fdv")),
        "dex": best.get("dexId"), "chain": best.get("chainId"),
        "pair_created_ms": created,
        "name": (best.get("baseToken") or {}).get("name", ""),
        "symbol": (best.get("baseToken") or {}).get("symbol", ""),
    }


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_report(flags, market, now_ms=None):
    """Build the red-flags list + an overall verdict from parsed flags/market."""
    red = []   # (message, severity) severity in critical|high|medium

    if flags.get("honeypot") or flags.get("cannot_sell"):
        red.append(("Honeypot — you can buy but likely CANNOT SELL", "critical"))
    st, bt = flags.get("sell_tax"), flags.get("buy_tax")
    if st is not None and st >= 0.10:
        red.append((f"High sell tax ~{st*100:.0f}%", "high"))
    if bt is not None and bt >= 0.10:
        red.append((f"High buy tax ~{bt*100:.0f}%", "high"))
    if flags.get("freezable"):
        red.append(("Freeze authority active — your tokens can be frozen", "high"))
    if flags.get("mintable"):
        red.append(("Mint authority active — supply can be inflated & dumped", "high"))
    if flags.get("owner_reclaim"):
        red.append(("Owner can reclaim control of the contract", "high"))
    if flags.get("hidden_owner"):
        red.append(("Hidden owner", "high"))
    if flags.get("transfer_pausable"):
        red.append(("Transfers can be paused by the owner", "high"))
    if flags.get("open_source") is False:
        red.append(("Contract is not verified / open-source", "medium"))
    th = flags.get("top_holder_pct")
    if th is not None and th >= 0.30:
        red.append((f"Top holder owns {th*100:.0f}% — single-wallet dump risk", "high"))
    liq = market.get("liquidity")
    if liq is not None and liq < 10000:
        red.append((f"Very low liquidity (${liq:,.0f}) — easy to rug or move", "high"))

    notes = []
    created = market.get("pair_created_ms")
    if created and now_ms:
        age_h = (now_ms - created) / 3_600_000.0
        if age_h < 24:
            notes.append(f"Brand new (~{age_h:.0f}h old) — the highest-rug window.")

    has_critical = any(s == "critical" for _, s in red)
    high_count = sum(1 for _, s in red if s in ("critical", "high"))
    if has_critical:
        verdict, level = "AVOID — looks like a trap", "avoid"
    elif high_count >= 3:
        verdict, level = "HIGH RISK", "high"
    elif high_count >= 1:
        verdict, level = "ELEVATED RISK", "elevated"
    else:
        verdict, level = "No major red flags found (still a gamble)", "clear"

    return {"verdict": verdict, "level": level,
            "red_flags": [{"msg": m, "severity": s} for m, s in red],
            "notes": notes}


# --------------------------------------------------------------------------- #
# Orchestration (live — makes network calls)
# --------------------------------------------------------------------------- #
def fetch_security(address, chain):
    chain_id = CHAINS.get(chain)
    if chain_id is None:
        return None, f"Unsupported chain '{chain}'."
    if chain == "solana":
        data = _get_json(GOPLUS_SOL, {"contract_addresses": address})
        parser = parse_security_solana
    else:
        data = _get_json(GOPLUS_EVM.format(chain=chain_id), {"contract_addresses": address})
        parser = parse_security_evm
    if not data or str(data.get("code")) not in ("1", "0") and data.get("result") is None:
        # GoPlus returns code 1 on success; tolerate either but require a result
        pass
    result = (data or {}).get("result") or {}
    if not result:
        return None, "No security data returned (unknown or too-new token)."
    # result is keyed by address; take the matching or first entry
    token = result.get(address) or result.get(address.lower()) or next(iter(result.values()))
    return parser(token), None


def assess(address, chain, now_ms=None):
    """Full report: fetch security + market, parse, score. Returns (report, error)."""
    address = (address or "").strip()
    if not address:
        return None, "Enter a token contract address."
    flags, err = fetch_security(address, chain)
    if err:
        return None, err
    market = parse_market(_get_json(DEXSCREENER.format(addr=address)))
    assessment = score_report(flags, market, now_ms=now_ms)
    return {"address": address, "chain": chain, "flags": flags,
            "market": market, **assessment}, None
