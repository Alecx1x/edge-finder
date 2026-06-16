"""BestFightOdds.com fallback for MMA matchup odds.

The Odds API only carries a slice of the MMA calendar (mostly UFC). When a
matchup isn't on the API feed, we scrape BestFightOdds — which aggregates lines
across many promotions (UFC, Bellator/PFL, ONE, Oktagon, KSW, regional shows)
and even speculative future bouts.

Flow:
  search the fighter by name -> pick best /fighters/<slug> link
  fetch their page -> table.team-stats-table lists each bout as a `main-row`
  (the page's fighter) followed by the opponent row; the first signed-integer
  cell in each row is the opening moneyline.
  -> find the row pair whose opponent matches the other typed name.

Returns a matchup dict shaped exactly like odds_fetcher.find_matchup(), or None
when nothing resolves (the caller then offers manual odds entry). Never raises.
"""
import re

import requests

from mma_sources import fuzzy

BASE = "https://www.bestfightodds.com"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
_TIMEOUT = 20

_ML = re.compile(r"^[+-]\d{2,4}$")          # a clean American moneyline token


def _first_moneyline(row):
    """First signed-integer td = the opening line (the name sits in a <th>, and the
    movement % cell is skipped)."""
    for c in row.select("td"):
        t = c.get_text(" ", strip=True)
        if t.endswith("%"):
            continue
        if _ML.match(t):
            return int(t)
    return None


def _resolve_fighter(name):
    """Search BFO and return (page_url, displayed_name) of the best match, or None."""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(f"{BASE}/search", params={"query": name},
                         headers=UA, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    best, best_score = None, 0.0
    for a in soup.select('a[href*="/fighters/"]'):
        label = a.get_text(strip=True)
        href = a.get("href", "")
        if not label or "/fighters/" not in href:
            continue
        s = fuzzy(name, label)
        if s > best_score:
            best, best_score = (href, label), s
    if not best or best_score < 0.5:
        return None
    url = best[0] if best[0].startswith("http") else BASE + best[0]
    return url, best[1]


def _bout_pairs(soup):
    """Yield (fighter_row, opponent_row, event_label) from the team-stats table."""
    tbl = soup.select_one("table.team-stats-table")
    if not tbl:
        return
    current, event = None, ""
    for tr in tbl.select("tr"):
        cls = tr.get("class") or []
        if "event-header" in cls:
            event = tr.get_text(" ", strip=True)
            continue
        link = tr.select_one('a[href*="/fighters/"]')
        if not link:
            continue
        if "main-row" in cls:
            current = (tr, link.get_text(strip=True))
        elif current is not None:
            yield current[0], current[1], tr, link.get_text(strip=True), event
            current = None


def find_matchup(name_a, name_b):
    """Scrape BestFightOdds for name_a vs name_b. Returns a matchup dict or None."""
    try:
        from bs4 import BeautifulSoup
        resolved = _resolve_fighter(name_a)
        if not resolved:
            return None
        url, page_name = resolved
        r = requests.get(url, headers=UA, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")

        best = None  # (score, fighter_odds, opp_name, opp_odds, event)
        for frow, fname, orow, oname, event in _bout_pairs(soup):
            s = fuzzy(name_b, oname)
            if s < 0.6:
                continue
            f_odds = _first_moneyline(frow)
            o_odds = _first_moneyline(orow)
            if f_odds is None or o_odds is None:
                continue
            if best is None or s > best[0]:
                best = (s, f_odds, fname, o_odds, oname, event)

        if best is None:
            return None
        _, f_odds, fname, o_odds, oname, event = best
        return {
            "sport": "MMA",
            "league": f"BestFightOdds — {event}" if event else "BestFightOdds",
            "sport_key": "bestfightodds",
            "commence_time": None,
            "home_team": None,
            "away_team": None,
            "bookmaker_count": 1,                # opening line (single consensus number)
            "a": {"name": fname, "odds": float(f_odds)},
            "b": {"name": oname, "odds": float(o_odds)},
            "quota": {},
            "searched": ["BestFightOdds"],
            "source": "BestFightOdds",
        }
    except Exception:
        return None
