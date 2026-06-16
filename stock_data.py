"""Free stock + options data, key-less.

  quote(ticker)          -> price / previous close / change   (Yahoo v8 chart)
  options_chain(ticker)  -> expirations + calls/puts with IV + greeks, volume, OI,
                            bid/ask                            (CBOE delayed quotes)

Yahoo's chart endpoint is unofficial; CBOE publishes delayed option chains as open
JSON (no auth, and it includes greeks). Both degrade gracefully and the parsers
are tested on canned JSON.
"""
import datetime

import requests

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"

_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}


def _get_json(url, params=None, timeout=12):
    try:
        r = requests.get(url, params=params, headers=_UA, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _exp_label(epoch):
    try:
        return datetime.datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(epoch)


def parse_quote(data):
    try:
        meta = data["chart"]["result"][0]["meta"]
    except (TypeError, KeyError, IndexError):
        return None
    price = _f(meta.get("regularMarketPrice"))
    prev = _f(meta.get("previousClose") or meta.get("chartPreviousClose"))
    chg = (price - prev) if (price is not None and prev is not None) else None
    return {
        "symbol": meta.get("symbol", ""),
        "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol", ""),
        "price": price, "previous_close": prev,
        "change": round(chg, 2) if chg is not None else None,
        "change_pct": round(chg / prev, 4) if (chg is not None and prev) else None,
        "currency": meta.get("currency", "USD"),
    }


def _parse_occ(sym):
    """OCC option symbol -> (expiry 'YYYY-MM-DD', 'C'|'P', strike). e.g.
    'AAPL260608C00250000' -> ('2026-06-08', 'C', 250.0)."""
    try:
        strike = int(sym[-8:]) / 1000.0
        cp = sym[-9]
        yy, mm, dd = sym[-15:-13], sym[-13:-11], sym[-11:-9]
        return f"20{yy}-{mm}-{dd}", cp, strike
    except (ValueError, IndexError):
        return None, None, None


def _cboe_contract(o, expiry, cp, strike, price):
    itm = (strike < price) if cp == "C" else (strike > price)
    return {
        "expiry": expiry, "strike": strike,
        "last": _f(o.get("last_trade_price")), "bid": _f(o.get("bid")), "ask": _f(o.get("ask")),
        "iv": _f(o.get("iv")), "delta": _f(o.get("delta")),
        "volume": o.get("volume"), "open_interest": o.get("open_interest"),
        "itm": bool(itm), "contract": o.get("option", ""),
    }


def parse_options(data, expiry=None, max_strikes=60):
    """Parse a CBOE delayed-quotes payload into expirations + a selected chain."""
    d = (data or {}).get("data") or {}
    raw = d.get("options")
    if not isinstance(raw, list) or not raw:
        return None
    price = _f(d.get("current_price") or d.get("close"))
    symbol = d.get("symbol", "")

    parsed = []
    for o in raw:
        exp, cp, strike = _parse_occ(o.get("option", ""))
        if exp and cp in ("C", "P"):
            parsed.append((exp, cp, strike, o))
    if not parsed:
        return None

    expirations = sorted({p[0] for p in parsed})
    sel = expiry if expiry in expirations else expirations[0]

    def side(cp):
        rows = [_cboe_contract(o, e, cp, k, price) for (e, c, k, o) in parsed if e == sel and c == cp]
        if price and len(rows) > max_strikes:
            rows.sort(key=lambda r: abs((r["strike"] or 0) - price))
            rows = rows[:max_strikes]
        return sorted(rows, key=lambda r: r["strike"] or 0)

    return {
        "symbol": symbol, "price": price,
        "expirations": [{"label": e, "value": e} for e in expirations],
        "selected_expiry": sel, "selected_label": sel,
        "calls": side("C"), "puts": side("P"),
    }


def quote(ticker):
    data = _get_json(CHART.format(ticker=ticker.upper()),
                     {"range": "1d", "interval": "1d"})
    q = parse_quote(data)
    return (q, None) if q else (None, "Couldn't fetch a quote (ticker wrong, or Yahoo unavailable).")


def options_chain(ticker, expiry=None):
    data = _get_json(CBOE.format(ticker=ticker.upper()))
    c = parse_options(data, expiry)
    return (c, None) if c else (None, "Couldn't fetch options (ticker may have no options listed).")


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    q, e = quote(t)
    print(q or e)
    ch, e2 = options_chain(t)
    if ch:
        print(f"{ch['symbol']} ${ch['price']} · {len(ch['expirations'])} expirations · "
              f"{len(ch['calls'])} calls / {len(ch['puts'])} puts for {ch['selected_label']}")
    else:
        print(e2)
