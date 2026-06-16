"""+EV ("value") scanner — find bets priced better than the sharp line.

This is the honest, sustainable edge: we DON'T try to out-predict the market. We
let the sharpest book (Pinnacle) tell us the fair probability, then scan every
other book for a price that pays MORE than that fair probability deserves. Each
such bet is +EV — positive expected value — even though any single one can lose.

  fair prob  = de-vigged Pinnacle line   (the market's best estimate)
  EV%        = fair_prob * decimal_payout - 1   (per $1 staked)
  +EV bet    = a book offering odds where EV% > your threshold

Reuses `odds_fetcher` for the live board and keeps EACH book's price (the base
fetcher averages them, which is exactly what we must NOT do here).

Limit-avoidance is built in: stakes are suggested as conservative round numbers,
books are tagged sharp/soft, and suspiciously-large edges are flagged as likely
stale/void risk (the bets that get you limited fastest).
"""
from collections import defaultdict

import odds_fetcher as of
import scoring_engine
import metrics

PINNACLE_KEY = "pinnacle"

# Books that generally tolerate winners / post sharp lines (safer to hammer).
SHARP_BOOKS = {"pinnacle", "betonlineag", "lowvig", "circasports", "bookmaker"}
# Recreational books — softer prices but quick to limit consistent winners.
SOFT_BOOKS = {"draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers",
              "espnbet", "pointsbetus", "bovada", "mybookieag", "unibet_us",
              "betparx", "fanatics", "hardrockbet"}

# Above this EV, a line is usually stale/erroneous — books often void or limit.
SUSPICIOUS_EV = 0.08

# Selectable bookmakers for the "My books" filter (Odds API keys + display names).
# group is just for grouping the UI checklist. Pinnacle is intentionally absent —
# it's the fair-line reference, not a book you bet at.
KNOWN_BOOKS = [
    {"key": "draftkings", "title": "DraftKings", "group": "US mainstream"},
    {"key": "fanduel", "title": "FanDuel", "group": "US mainstream"},
    {"key": "betmgm", "title": "BetMGM", "group": "US mainstream"},
    {"key": "williamhill_us", "title": "Caesars", "group": "US mainstream"},
    {"key": "espnbet", "title": "ESPN BET", "group": "US mainstream"},
    {"key": "betrivers", "title": "BetRivers", "group": "US mainstream"},
    {"key": "fanatics", "title": "Fanatics", "group": "US mainstream"},
    {"key": "hardrockbet", "title": "Hard Rock Bet", "group": "US mainstream"},
    {"key": "betparx", "title": "betPARX", "group": "US mainstream"},
    {"key": "ballybet", "title": "Bally Bet", "group": "US mainstream"},
    {"key": "fliff", "title": "Fliff", "group": "US mainstream"},
    {"key": "betonlineag", "title": "BetOnline.ag", "group": "Offshore / sharp"},
    {"key": "bovada", "title": "Bovada", "group": "Offshore / sharp"},
    {"key": "mybookieag", "title": "MyBookie.ag", "group": "Offshore / sharp"},
    {"key": "lowvig", "title": "LowVig.ag", "group": "Offshore / sharp"},
    {"key": "betus", "title": "BetUS", "group": "Offshore / sharp"},
    {"key": "novig", "title": "Novig (exchange)", "group": "Exchanges"},
    {"key": "prophetx", "title": "ProphetX (exchange)", "group": "Exchanges"},
]


def american_to_decimal(odds):
    """Total decimal return per 1 staked (stake + profit)."""
    return 1.0 + metrics.american_to_decimal_profit(odds)


def devig(american_by_outcome):
    """Multiplicative de-vig: strip the book's margin so fair probs sum to 1.

    Works for 2-way (MMA/tennis) and 3-way (soccer incl. draw) markets alike.
    """
    raw = {n: scoring_engine.american_to_prob(p) for n, p in american_by_outcome.items()}
    total = sum(raw.values())
    if total <= 0:
        return None
    return {n: r / total for n, r in raw.items()}


def _book_markets(event):
    """{book_key: {"title": str, "outs": {outcome: american_price}}} for h2h."""
    books = {}
    for bk in event.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            outs = {oc["name"]: float(oc["price"]) for oc in mk.get("outcomes", [])
                    if oc.get("price") is not None and "name" in oc}
            if outs:
                books[bk["key"]] = {"title": bk.get("title", bk["key"]), "outs": outs,
                                    "last_update": bk.get("last_update")}
    return books


def _fair_line(books):
    """(fair_probs, reference_label). Pinnacle if present, else book consensus."""
    if PINNACLE_KEY in books:
        return devig(books[PINNACLE_KEY]["outs"]), "Pinnacle"
    # consensus fallback: average implied prob per outcome across all books, de-vig
    acc = defaultdict(list)
    for b in books.values():
        for name, price in b["outs"].items():
            acc[name].append(scoring_engine.american_to_prob(price))
    if not acc:
        return None, None
    avg = {n: sum(v) / len(v) for n, v in acc.items()}
    total = sum(avg.values())
    if total <= 0:
        return None, None
    return {n: a / total for n, a in avg.items()}, "market consensus"


def suggest_stake(bankroll, fair_prob, american, kelly_mult=0.25, cap_frac=0.02, round_to=5):
    """Conservative, ROUND stake (quarter-Kelly, capped at 2% of bankroll).

    Round numbers + small fractions are deliberate: exact Kelly amounts and
    max-limit bets are how books spot and limit sharp accounts.
    """
    f = metrics.kelly_fraction(fair_prob, american) * kelly_mult
    f = min(f, cap_frac)
    amt = f * bankroll
    if amt <= 0:
        return 0
    return max(round_to, int(round(amt / round_to)) * round_to)


def event_opportunities(event, min_ev, bankroll, sport, league, my_books=None):
    """List +EV opportunities in one event vs its fair (sharp) line.

    my_books: optional set/list of bookmaker keys. When given, only bets at those
    books are surfaced (the Pinnacle/consensus reference is unaffected — it's the
    benchmark, not a book you bet at).
    """
    books = _book_markets(event)
    if len(books) < 2:
        return []
    fair, ref_label = _fair_line(books)
    if not fair:
        return []
    ref_key = PINNACLE_KEY if ref_label == "Pinnacle" else None
    only = set(my_books) if my_books else None

    opps = []
    for bkey, b in books.items():
        if bkey == ref_key:
            continue  # never bet the reference book against itself
        if only and bkey not in only:
            continue  # not one of the user's books
        for name, price in b["outs"].items():
            fp = fair.get(name)
            if fp is None:
                continue
            ev_pct = fp * american_to_decimal(price) - 1.0
            if ev_pct < min_ev:
                continue
            # the other side (for clean one-click logging + later CLV)
            opponent = next((n for n in b["outs"] if n != name), None)
            opps.append({
                "sport": sport, "league": league,
                "commence_time": event.get("commence_time"),
                "event": f"{event.get('home_team') or ''} vs {event.get('away_team') or ''}".strip(" vs"),
                "selection": name,
                "opponent": opponent,
                "opponent_price": round(b["outs"][opponent], 1) if opponent else None,
                "book": b["title"], "book_key": bkey,
                "price": round(price, 1),
                "fair_prob": round(fp, 4),
                "ev_pct": round(ev_pct, 4),
                "reference": ref_label,
                "suggested_stake": suggest_stake(bankroll, fp, price),
                "book_type": "sharp" if bkey in SHARP_BOOKS else ("soft" if bkey in SOFT_BOOKS else "other"),
                "limit_risk": ev_pct >= SUSPICIOUS_EV,
            })
    return opps


def scan(api_key, sport, regions="us,eu", min_ev=0.02, bankroll=1000.0, max_keys=6,
         my_books=None):
    """Scan a sport's live board for +EV bets.

    regions: comma list passed to The Odds API. 'eu' is what carries Pinnacle, so
    the default 'us,eu' buys a real sharp reference (note: cost scales with the
    number of regions — 'us,eu' costs ~2 credits per league call).
    my_books: optional bookmaker-key filter — only surface bets at these books.
    Returns {opportunities, quota, leagues, no_pinnacle}.
    """
    group = of.GROUP_BY_SPORT[sport]
    leagues = of.list_active_sports(api_key, group)   # free endpoint (no quota cost)
    if not leagues:
        return {"opportunities": [], "quota": {}, "leagues": [], "no_pinnacle": True}

    all_opps, quota, scanned, saw_pinnacle = [], {}, [], False
    for s in leagues[:max_keys]:
        try:
            data, headers = of._get(
                f"{of.BASE}/sports/{s['key']}/odds",
                {"apiKey": api_key, "regions": regions, "markets": "h2h", "oddsFormat": "american"},
            )
        except of.OddsError:
            continue
        quota = {"remaining": headers.get("x-requests-remaining"),
                 "used": headers.get("x-requests-used")}
        scanned.append(s.get("title", s["key"]))
        for ev in data:
            books = _book_markets(ev)
            if PINNACLE_KEY in books:
                saw_pinnacle = True
            all_opps.extend(event_opportunities(ev, min_ev, bankroll, sport,
                                                s.get("title", s["key"]), my_books))

    all_opps.sort(key=lambda o: o["ev_pct"], reverse=True)
    return {"opportunities": all_opps, "quota": quota, "leagues": scanned,
            "no_pinnacle": not saw_pinnacle}


# --------------------------------------------------------------------------- #
# CLI (this one DOES spend live quota — user-triggered)
# --------------------------------------------------------------------------- #
def main():
    import argparse
    import config_manager as cfgmod
    ap = argparse.ArgumentParser(description="Scan a sport for +EV bets vs the sharp line (spends Odds API quota).")
    ap.add_argument("sport", choices=list(of.GROUP_BY_SPORT.keys()))
    ap.add_argument("--regions", default="us,eu")
    ap.add_argument("--min-ev", type=float, default=0.02)
    ap.add_argument("--max-keys", type=int, default=6)
    args = ap.parse_args()

    cfg = cfgmod.load_config()
    key = cfgmod.get_api_key()
    if not key:
        print("No Odds API key set. Add it in the app first.")
        return
    res = scan(key, args.sport, regions=args.regions, min_ev=args.min_ev,
               bankroll=cfg.get("bankroll", 1000.0), max_keys=args.max_keys,
               my_books=cfgmod.get_my_books(cfg))
    print(f"\nScanned: {', '.join(res['leagues']) or 'none'}   "
          f"quota remaining: {res['quota'].get('remaining')}")
    if res["no_pinnacle"]:
        print("(!) Pinnacle not in results — using market-consensus fair line "
              "(weaker reference). Add 'eu' to --regions for a true sharp line.")
    if not res["opportunities"]:
        print("No +EV bets at this threshold right now.")
        return
    print(f"\n{len(res['opportunities'])} +EV bets (best first):\n")
    for o in res["opportunities"][:25]:
        flag = "  [!] big edge — verify, limit risk" if o["limit_risk"] else ""
        print(f"  {o['ev_pct']*100:5.1f}% EV  {o['selection']:<22} @ {o['price']:>6} "
              f"({o['book']}, {o['book_type']})  stake ~${o['suggested_stake']}  "
              f"[{o['event']}]{flag}")
    print()


if __name__ == "__main__":
    main()
