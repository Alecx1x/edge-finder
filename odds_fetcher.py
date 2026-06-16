"""Market odds via The Odds API (v4, free tier).

Given a sport category and two manually-typed names, this finds the matching
event across the active league keys for that category and returns consensus
(average across bookmakers) moneyline odds for each side.
"""
from collections import defaultdict
from difflib import SequenceMatcher

import requests

from mma_sources import fold  # accent/diacritic transliteration (á->a, č->c, ř->r)

BASE = "https://api.the-odds-api.com/v4"

# Map our 4 sport categories onto The Odds API `group` values.
GROUP_BY_SPORT = {
    "MMA": "Mixed Martial Arts",
    "Basketball": "Basketball",
    "Soccer": "Soccer",
    "Tennis": "Tennis",
}


class OddsError(Exception):
    """Any user-facing failure talking to The Odds API (key/quota/network)."""


class NoMatchup(OddsError):
    """The feed was reached fine, but no event matched the two names. Distinct so
    callers can fall back (scrape another source / offer manual odds) instead of
    surfacing it as a hard error."""


def _get(url, params):
    try:
        r = requests.get(url, params=params, timeout=20)
    except requests.RequestException as e:
        raise OddsError(f"Network error reaching The Odds API: {e}")
    if r.status_code == 401:
        raise OddsError("Invalid or missing API key (401).")
    if r.status_code == 429:
        raise OddsError("Quota / rate limit exceeded (429). Free tier is 500 req/month.")
    if r.status_code != 200:
        raise OddsError(f"Odds API returned {r.status_code}: {r.text[:200]}")
    try:
        return r.json(), r.headers
    except ValueError:
        raise OddsError("Odds API returned an unparseable response.")


def validate_key(api_key):
    """Cheap call to confirm a key works. Returns remaining-quota string or raises."""
    _, headers = _get(f"{BASE}/sports", {"apiKey": api_key})
    return headers.get("x-requests-remaining")


def list_active_sports(api_key, group):
    data, _ = _get(f"{BASE}/sports", {"apiKey": api_key})
    return [s for s in data if s.get("group") == group and s.get("active")]


def _name_match(query, candidate):
    q, c = fold(query).lower().strip(), fold(candidate).lower().strip()
    if not q or not c:
        return 0.0
    if q in c or c in q:
        return 0.95
    # token overlap helps with "Lakers" vs "Los Angeles Lakers"
    qt, ct = set(q.split()), set(c.split())
    overlap = len(qt & ct) / max(1, len(qt))
    return max(SequenceMatcher(None, q, c).ratio(), 0.9 * overlap)


def _aggregate_outcomes(event):
    """Average American odds per participant across all bookmakers for the h2h market."""
    acc = defaultdict(list)
    for bk in event.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                if "name" in oc and oc.get("price") is not None:
                    acc[oc["name"]].append(float(oc["price"]))
    return {name: sum(p) / len(p) for name, p in acc.items() if p}


def find_matchup(api_key, sport, name_a, name_b, cfg, max_keys=10):
    """Search active leagues in `sport` for an event involving both names.

    Returns a structured matchup dict. Raises OddsError on no match / API failure.
    """
    group = GROUP_BY_SPORT[sport]
    sports = list_active_sports(api_key, group)
    if not sports:
        raise NoMatchup(f"No active {sport} markets on The Odds API right now.")

    odds_cfg = cfg.get("odds", {})
    best = None  # (confidence, event, sport_obj, name_a_match, name_b_match, outcomes)
    quota = {}
    searched = []

    for s in sports[:max_keys]:
        try:
            data, headers = _get(
                f"{BASE}/sports/{s['key']}/odds",
                {
                    "apiKey": api_key,
                    "regions": odds_cfg.get("regions", "us"),
                    "markets": "h2h",
                    "oddsFormat": odds_cfg.get("odds_format", "american"),
                },
            )
        except OddsError:
            continue  # a single league failing shouldn't abort the whole search
        quota = {
            "remaining": headers.get("x-requests-remaining"),
            "used": headers.get("x-requests-used"),
        }
        searched.append(s.get("title", s["key"]))

        for ev in data:
            outs = _aggregate_outcomes(ev)
            names = list(outs.keys())
            if len(names) < 2:
                continue
            ma = max(names, key=lambda n: _name_match(name_a, n))
            mb = max(names, key=lambda n: _name_match(name_b, n))
            if ma == mb:
                continue
            conf = _name_match(name_a, ma) + _name_match(name_b, mb)
            if conf < 1.2:  # require ~0.6 avg match on each side
                continue
            if best is None or conf > best[0]:
                best = (conf, ev, s, ma, mb, outs)

    if best is None:
        raise NoMatchup(
            f"No {sport} event matched '{name_a}' vs '{name_b}'.\n"
            f"Searched: {', '.join(searched) or 'none'}.\n"
            "Check spelling, or the matchup may not be listed yet."
        )

    _, ev, s, ma, mb, outs = best
    return {
        "sport": sport,
        "league": s.get("title", s["key"]),
        "sport_key": s["key"],
        "commence_time": ev.get("commence_time"),
        "home_team": ev.get("home_team"),
        "away_team": ev.get("away_team"),
        "bookmaker_count": len(ev.get("bookmakers", [])),
        "a": {"name": ma, "odds": round(outs[ma], 1)},
        "b": {"name": mb, "odds": round(outs[mb], 1)},
        "quota": quota,
        "searched": searched,
        "raw_event": ev,
    }
