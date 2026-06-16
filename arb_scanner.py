"""Arbitrage scanner — find bets where the books disagree enough to lock a profit.

If you take the BEST price each book offers on every outcome of a game, and those
prices imply a total probability under 100%, you can stake all sides so that you
win the same amount no matter who wins. That's an arbitrage ("arb") — guaranteed
profit, no prediction required.

  for each outcome:  best price across all books  ->  implied prob = 1 / decimal
  if sum(implied) < 1  ->  arb;  profit% = 1/sum - 1
  stake each leg proportional to 1/decimal so every outcome returns the same.

Reuses value_scanner's board helpers. Honest caveats (surfaced in the UI): arbs
are thin, vanish in seconds, need balances sitting at multiple books, and are the
single fastest way to get limited — bet them sparingly and not to max limits.
"""
import odds_fetcher as of
import value_scanner as vs


def event_arb(event, min_profit, total_stake, sport, league, my_books=None):
    """Return an arb opportunity dict for one event, or None.

    my_books: optional bookmaker-key filter. Arb legs must be placeable, so when
    given, only the user's books are considered when picking the best price.
    """
    books = vs._book_markets(event)
    if my_books:
        only = set(my_books)
        books = {k: v for k, v in books.items() if k in only}
    if len(books) < 2:
        return None

    names = set()
    for b in books.values():
        names.update(b["outs"].keys())
    if len(names) < 2:
        return None

    # best (highest-paying) price per outcome, and which book offers it
    best = {}
    for name in names:
        top = None
        for bkey, b in books.items():
            price = b["outs"].get(name)
            if price is None:
                continue
            if top is None or vs.american_to_decimal(price) > vs.american_to_decimal(top[0]):
                top = (price, b["title"], bkey)
        if top is None:
            return None          # an outcome no book prices — can't cover it
        best[name] = top

    inv = sum(1.0 / vs.american_to_decimal(t[0]) for t in best.values())
    if inv >= 1.0:               # normal vig — no free money
        return None
    profit_pct = (1.0 / inv) - 1.0
    if profit_pct < min_profit:
        return None

    legs = []
    for name, (price, btitle, bkey) in best.items():
        dec = vs.american_to_decimal(price)
        stake = total_stake * (1.0 / dec) / inv
        legs.append({
            "selection": name, "odds": round(price, 1),
            "book": btitle, "book_key": bkey,
            "stake": round(stake, 2),
            "book_type": "sharp" if bkey in vs.SHARP_BOOKS
                         else ("soft" if bkey in vs.SOFT_BOOKS else "other"),
        })
    return {
        "sport": sport, "league": league,
        "event": f"{event.get('home_team') or ''} vs {event.get('away_team') or ''}".strip(" vs"),
        "commence_time": event.get("commence_time"),
        "profit_pct": round(profit_pct, 4),
        "profit": round(total_stake * profit_pct, 2),
        "guaranteed_return": round(total_stake / inv, 2),
        "total_stake": round(total_stake, 2),
        "n_books": len(books),
        "legs": legs,
    }


def scan(api_key, sport, regions="us,eu", min_profit=0.0, total_stake=100.0, max_keys=6,
         my_books=None):
    """Scan a sport's board for arbs. Returns {arbs, quota, leagues}."""
    group = of.GROUP_BY_SPORT[sport]
    leagues = of.list_active_sports(api_key, group)     # free endpoint
    if not leagues:
        return {"arbs": [], "quota": {}, "leagues": []}

    arbs, quota, scanned = [], {}, []
    for s in leagues[:max_keys]:
        try:
            data, headers = of._get(
                f"{of.BASE}/sports/{s['key']}/odds",
                {"apiKey": api_key, "regions": regions, "markets": "h2h", "oddsFormat": "american"})
        except of.OddsError:
            continue
        quota = {"remaining": headers.get("x-requests-remaining"),
                 "used": headers.get("x-requests-used")}
        scanned.append(s.get("title", s["key"]))
        for ev in data:
            a = event_arb(ev, min_profit, total_stake, sport, s.get("title", s["key"]), my_books)
            if a:
                arbs.append(a)
    arbs.sort(key=lambda a: a["profit_pct"], reverse=True)
    return {"arbs": arbs, "quota": quota, "leagues": scanned}


def main():
    import argparse
    import config_manager as cfgmod
    ap = argparse.ArgumentParser(description="Scan a sport for arbitrage (spends Odds API quota).")
    ap.add_argument("sport", choices=list(of.GROUP_BY_SPORT.keys()))
    ap.add_argument("--regions", default="us,eu")
    ap.add_argument("--min-profit", type=float, default=0.0)
    ap.add_argument("--stake", type=float, default=100.0)
    ap.add_argument("--max-keys", type=int, default=6)
    args = ap.parse_args()

    cfg = cfgmod.load_config()
    key = cfgmod.get_api_key()
    if not key:
        print("No Odds API key set.")
        return
    res = scan(key, args.sport, regions=args.regions, min_profit=args.min_profit,
               total_stake=args.stake, max_keys=args.max_keys,
               my_books=cfgmod.get_my_books(cfg))
    print(f"\nScanned: {', '.join(res['leagues']) or 'none'}   quota: {res['quota'].get('remaining')}")
    if not res["arbs"]:
        print("No arbs right now (normal — they're rare and brief).")
        return
    for a in res["arbs"]:
        print(f"\n  {a['profit_pct']*100:.2f}% arb  [{a['event']}]  stake ${a['total_stake']} -> ${a['guaranteed_return']}")
        for leg in a["legs"]:
            print(f"     ${leg['stake']:>7} on {leg['selection']:<22} @ {leg['odds']:>6} ({leg['book']})")
    print()


if __name__ == "__main__":
    main()
