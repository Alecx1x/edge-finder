"""Prediction-markets intelligence (Polymarket + Kalshi).

Surfaces the two signals that actually help you profit on prediction markets:
  * heavy price moves that are backed by real volume (something changed), and
  * where the big money is going (smart-money / whale trades).

Everything here uses free public APIs — no key, no quota:
  * Polymarket Gamma API  https://gamma-api.polymarket.com  (markets, prices, 24h move)
  * Polymarket Data API   https://data-api.polymarket.com   (individual trades = whales)
  * Kalshi public API     https://api.elections.kalshi.com  (single-market lookup)

Polymarket is the analytical engine: it exposes per-trade wallet data, so we can
rank the biggest buyers and flag one-sided accumulation. Kalshi's public API has
no volume-ranked discovery (its hot markets aren't queryable without their internal
feed), so there we offer an honest single-market lookup by ticker plus a browse link.
"""
import json
import os
import threading
import time

import requests

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "Mozilla/5.0 (Money Lab Edge Finder)"}
TIMEOUT = 20

_WATCH_FILE = os.path.join(os.path.dirname(__file__), "pm_watchlist.json")
_LOCK = threading.Lock()


class MarketError(Exception):
    pass


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise MarketError(str(e))


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _jsonish(raw):
    """Gamma returns some list fields as JSON-encoded strings."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []
    return []


# --------------------------------------------------------------------------- #
# Polymarket — markets (trending / movers)
# --------------------------------------------------------------------------- #
def _clean_market(m):
    """Normalise a Gamma market into a flat, frontend-ready shape."""
    outs = _jsonish(m.get("outcomes"))
    prices = [_f(x) for x in _jsonish(m.get("outcomePrices"))]
    yes_price, lead_label = None, None
    if outs and prices and len(outs) == len(prices):
        # binary Yes/No -> show Yes; multi-outcome -> show the leading outcome
        if len(outs) == 2 and outs[0].strip().lower() == "yes":
            yes_price, lead_label = prices[0], "Yes"
        else:
            i = max(range(len(prices)), key=lambda k: prices[k])
            yes_price, lead_label = prices[i], outs[i]
    slug = m.get("slug") or ""
    event_slug = ""
    events = m.get("events")
    if isinstance(events, list) and events:
        event_slug = events[0].get("slug") or ""
    url = "https://polymarket.com/event/" + (event_slug or slug) if (event_slug or slug) else "https://polymarket.com"
    return {
        "id": m.get("conditionId"),
        "slug": slug,
        "question": m.get("question") or m.get("title") or slug,
        "yes_price": yes_price,
        "lead_label": lead_label,
        "change24": _f(m.get("oneDayPriceChange")),
        "volume24": _f(m.get("volume24hr")),
        "liquidity": _f(m.get("liquidity")),
        "url": url,
        "source": "Polymarket",
    }


def _market_pool(limit=300):
    """A pool of the most-traded open markets, sorted by 24h volume."""
    raw = _get(GAMMA + "/markets", {
        "closed": "false", "active": "true",
        "order": "volume24hr", "ascending": "false", "limit": limit,
    })
    if not isinstance(raw, list):
        return []
    return [_clean_market(m) for m in raw if m.get("conditionId")]


def trending(limit=40, min_vol=0.0):
    """Most-traded open Polymarket markets right now (by 24h volume)."""
    pool = _market_pool(limit=max(limit, 60))
    out = [m for m in pool if m["volume24"] >= min_vol]
    return {"markets": out[:limit], "source": "Polymarket",
            "note": "Sorted by 24-hour traded volume. High volume = the market the crowd is most active on."}


def movers(limit=40, min_vol=25000.0):
    """Biggest 24h price swings — but only on markets with real volume.

    A price move on a thin market is noise; a move backed by volume is a signal
    that something changed (news, a sharp taking a side). We require min_vol so
    the list is moves you can actually trust and trade.
    """
    pool = _market_pool(limit=300)
    liquid = [m for m in pool if m["volume24"] >= min_vol and m["change24"] is not None]
    liquid.sort(key=lambda m: abs(m["change24"]), reverse=True)
    return {"markets": liquid[:limit], "source": "Polymarket", "min_vol": min_vol,
            "note": ("Largest 24-hour price moves on markets with >= "
                     f"${int(min_vol):,} of volume — moves big money actually backed.")}


# --------------------------------------------------------------------------- #
# Polymarket — trades (smart money / whales)
# --------------------------------------------------------------------------- #
def _clean_trade(t):
    size, price = _f(t.get("size")), _f(t.get("price"))
    return {
        "usd": round(size * price, 2),
        "side": (t.get("side") or "").upper(),         # BUY / SELL
        "outcome": t.get("outcome"),
        "price": price,
        "size": size,
        "trader": t.get("name") or t.get("pseudonym") or "anon",
        "wallet": t.get("proxyWallet") or "",
        "title": t.get("title"),
        "slug": t.get("slug"),
        "ts": int(_f(t.get("timestamp"))),
    }


def market_trades(condition_id, limit=80, min_usd=0.0):
    """Recent trades on one market, biggest first, with a smart-money lean.

    The 'lean' is which outcome attracted the most *net buying* money recently —
    where the size is going. One trader stacking one side is flagged as a whale.
    """
    if not condition_id:
        raise MarketError("No market id.")
    raw = _get(DATA + "/trades", {"market": condition_id, "limit": 500})
    trades = [_clean_trade(t) for t in raw if isinstance(t, dict)]
    trades = [t for t in trades if t["usd"] >= min_usd]
    trades.sort(key=lambda t: t["usd"], reverse=True)

    # net buying pressure per outcome (BUY adds, SELL removes)
    net = {}
    for t in trades:
        sign = 1 if t["side"] == "BUY" else -1
        net[t["outcome"]] = net.get(t["outcome"], 0.0) + sign * t["usd"]
    lean, lean_usd = None, 0.0
    for outcome, amt in net.items():
        if amt > lean_usd:
            lean, lean_usd = outcome, amt

    # whale flag: a single wallet with big one-sided buying
    bywallet = {}
    for t in trades:
        if t["side"] != "BUY":
            continue
        k = (t["wallet"], t["outcome"])
        bywallet[k] = bywallet.get(k, 0.0) + t["usd"]
    whale = None
    if bywallet:
        (w, oc), amt = max(bywallet.items(), key=lambda kv: kv[1])
        if amt >= 5000:
            tr = next((t for t in trades if t["wallet"] == w), None)
            whale = {"wallet": w, "outcome": oc, "usd": round(amt, 2),
                     "trader": tr["trader"] if tr else "anon"}

    return {
        "trades": trades[:limit],
        "n": len(trades),
        "lean": lean,
        "lean_usd": round(lean_usd, 2),
        "net": {k: round(v, 2) for k, v in net.items()},
        "whale": whale,
    }


def big_trades(limit=60, min_usd=1000.0):
    """The biggest individual trades hitting Polymarket right now (any market)."""
    raw = _get(DATA + "/trades", {"limit": 500})
    trades = [_clean_trade(t) for t in raw if isinstance(t, dict)]
    trades = [t for t in trades if t["usd"] >= min_usd]
    trades.sort(key=lambda t: t["usd"], reverse=True)
    return {"trades": trades[:limit],
            "note": "Largest single trades across all of Polymarket in the recent window. Follow the size."}


def leaderboard(min_usd=500.0, top=25):
    """Wallets moving the most money recently — your smart-money watchlist seed.

    Aggregated from the recent trade stream. A wallet that keeps showing up with
    size is worth following; one big trade could just be luck.
    """
    raw = _get(DATA + "/trades", {"limit": 1000})
    agg = {}
    for t in raw:
        if not isinstance(t, dict):
            continue
        ct = _clean_trade(t)
        if ct["usd"] < min_usd or not ct["wallet"]:
            continue
        a = agg.setdefault(ct["wallet"], {
            "wallet": ct["wallet"], "trader": ct["trader"],
            "total_usd": 0.0, "n": 0, "last_title": ct["title"]})
        a["total_usd"] += ct["usd"]
        a["n"] += 1
    rows = sorted(agg.values(), key=lambda r: r["total_usd"], reverse=True)
    for r in rows:
        r["total_usd"] = round(r["total_usd"], 2)
    return {"wallets": rows[:top],
            "note": "Wallets ranked by money traded in the recent window. Repeat big players are the ones to watch."}


# --------------------------------------------------------------------------- #
# Kalshi — single-market lookup (no volume-ranked discovery on the public API)
# --------------------------------------------------------------------------- #
def kalshi_market(ticker):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise MarketError("Enter a Kalshi market ticker (e.g. from a market's URL).")
    try:
        data = _get(f"{KALSHI}/markets/{ticker}")
    except MarketError:
        raise MarketError(f"No Kalshi market found for ticker '{ticker}'.")
    m = data.get("market") or {}
    if not m:
        raise MarketError(f"No Kalshi market found for ticker '{ticker}'.")
    yb, ya = m.get("yes_bid"), m.get("yes_ask")
    mid = None
    if yb is not None and ya is not None:
        mid = round((yb + ya) / 200.0, 4)        # cents -> probability
    return {
        "ticker": m.get("ticker"),
        "title": m.get("title"),
        "subtitle": m.get("subtitle") or m.get("yes_sub_title"),
        "yes_bid": yb, "yes_ask": ya,
        "yes_prob": mid,
        "last_price": m.get("last_price"),
        "volume": m.get("volume"),
        "volume_24h": m.get("volume_24h"),
        "open_interest": m.get("open_interest"),
        "status": m.get("status"),
        "close_time": m.get("close_time"),
        "url": f"https://kalshi.com/markets/{m.get('event_ticker','')}",
        "source": "Kalshi",
    }


# --------------------------------------------------------------------------- #
# Watchlist + price-over-time snapshots (local JSON)
# --------------------------------------------------------------------------- #
def _load():
    if not os.path.exists(_WATCH_FILE):
        return {"watch": [], "snapshots": {}}
    try:
        with open(_WATCH_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("watch", [])
        d.setdefault("snapshots", {})
        return d
    except (ValueError, OSError):
        return {"watch": [], "snapshots": {}}


def _save(d):
    tmp = _WATCH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, _WATCH_FILE)


def _snapshot_point(market_id, yes_price, now=None):
    return {"ts": int(now if now is not None else time.time()),
            "yes_price": round(yes_price, 4) if yes_price is not None else None}


def watch_add(market):
    """Add a market to the watchlist and take a first price snapshot."""
    mid = market.get("id")
    if not mid:
        raise MarketError("Market is missing an id.")
    with _LOCK:
        d = _load()
        if not any(w["id"] == mid for w in d["watch"]):
            d["watch"].append({
                "id": mid,
                "slug": market.get("slug"),
                "question": market.get("question"),
                "url": market.get("url"),
                "source": market.get("source", "Polymarket"),
                "added_ts": int(time.time()),
            })
        snaps = d["snapshots"].setdefault(mid, [])
        if market.get("yes_price") is not None:
            snaps.append(_snapshot_point(mid, market.get("yes_price")))
        _save(d)
    return watch_view()


def watch_remove(market_id):
    with _LOCK:
        d = _load()
        d["watch"] = [w for w in d["watch"] if w["id"] != market_id]
        d["snapshots"].pop(market_id, None)
        _save(d)
    return watch_view()


def watch_snapshot():
    """Re-fetch the current price of every tracked market and append a snapshot.

    This is what builds the price-over-time history. Run it from the refresh
    button (or periodically) to watch how each market drifts.
    """
    with _LOCK:
        d = _load()
        watch = list(d["watch"])
    errors = []
    for w in watch:
        if w.get("source") != "Polymarket":
            continue
        try:
            raw = _get(GAMMA + "/markets", {"condition_ids": w["id"]})
            if isinstance(raw, list) and raw:
                cm = _clean_market(raw[0])
                with _LOCK:
                    d = _load()
                    snaps = d["snapshots"].setdefault(w["id"], [])
                    if cm["yes_price"] is not None:
                        snaps.append(_snapshot_point(w["id"], cm["yes_price"]))
                    # also refresh the cached question/url
                    for ww in d["watch"]:
                        if ww["id"] == w["id"]:
                            ww["question"] = cm["question"] or ww.get("question")
                    _save(d)
        except MarketError as e:
            errors.append({"id": w["id"], "error": str(e)})
    view = watch_view()
    view["errors"] = errors
    return view


def watch_view():
    """Watchlist with each market's snapshot series and computed drift."""
    d = _load()
    items = []
    for w in d["watch"]:
        snaps = d["snapshots"].get(w["id"], [])
        first = next((s["yes_price"] for s in snaps if s["yes_price"] is not None), None)
        last = next((s["yes_price"] for s in reversed(snaps) if s["yes_price"] is not None), None)
        prev = None
        priced = [s for s in snaps if s["yes_price"] is not None]
        if len(priced) >= 2:
            prev = priced[-2]["yes_price"]
        items.append({
            **w,
            "snapshots": snaps,
            "first_price": first,
            "last_price": last,
            "change_total": (round(last - first, 4) if (first is not None and last is not None) else None),
            "change_since_prev": (round(last - prev, 4) if (last is not None and prev is not None) else None),
            "n_snapshots": len(snaps),
        })
    # biggest movers since first snapshot float to the top
    items.sort(key=lambda x: abs(x["change_total"]) if x["change_total"] is not None else 0, reverse=True)
    return {"watch": items, "count": len(items)}
