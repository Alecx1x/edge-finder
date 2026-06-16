"""Live NBA stats for the three Basketball sport-specific variables.

  pace differential  -> basketball-reference.com season "advanced" team table
  days rest          -> ESPN public schedule (gap before the next scheduled game)
  last-10 ATS record -> needs historical closing spreads (no key-free source) ->
                        graceful, honest fallback

Each public function takes a single team name and returns the standard dict
    {"score": 0-100 | None, "available": bool, "detail": str, "source": str}
and never raises. Team names are fuzzy-matched ("Lakers" -> "Los Angeles Lakers").
"""
import threading
from datetime import datetime, timezone

import requests

from mma_sources import fuzzy, _result

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
_TIMEOUT = 20

# Current NBA season label: the season spanning autumn->spring is named by its
# end year, so Oct 2025-Jun 2026 is "2026".
_SEASONS = (2026, 2025)

_lock = threading.Lock()
_pace_cache = None          # {team_name_lower: pace_float}
_espn_teams_cache = None    # [{"id","names":[...]}]


# --------------------------------------------------------------------------- #
# basketball-reference — team pace (advanced table, often inside HTML comments)
# --------------------------------------------------------------------------- #
def _load_pace():
    global _pace_cache
    if _pace_cache is not None:
        return _pace_cache
    with _lock:
        if _pace_cache is not None:
            return _pace_cache
        from bs4 import BeautifulSoup, Comment
        table = {}
        for yr in _SEASONS:
            try:
                r = requests.get(f"https://www.basketball-reference.com/leagues/NBA_{yr}.html",
                                 headers=UA, timeout=_TIMEOUT)
                if r.status_code != 200:
                    continue
            except requests.RequestException:
                continue
            html = r.text
            soup = BeautifulSoup(html, "lxml")
            # the advanced-team table is commented out in the served HTML
            for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
                if "advanced-team" in c:
                    html += c
            soup = BeautifulSoup(html, "lxml")
            tb = soup.find("table", id="advanced-team")
            if not tb:
                continue
            for row in tb.select("tbody tr"):
                cells = {td.get("data-stat"): td.get_text(strip=True)
                         for td in row.find_all(["th", "td"])}
                name = (cells.get("team") or "").replace("*", "").strip()
                try:
                    pace = float(cells.get("pace"))
                except (TypeError, ValueError):
                    continue
                if name:
                    table[name.lower()] = pace
            if table:
                break
        _pace_cache = table
        return table


def nba_pace(name):
    try:
        table = _load_pace()
    except Exception as e:
        return _result(detail=f"basketball-reference error: {e}", source="basketball-reference")
    if not table:
        return _result(detail="basketball-reference pace table unavailable", source="basketball-reference")
    best, score = None, 0.0
    for tname, pace in table.items():
        s = fuzzy(name, tname)
        if s > score:
            best, score = (tname, pace), s
    if not best or score < 0.6:
        return _result(detail=f"Couldn't resolve '{name}' on basketball-reference", source="basketball-reference")
    tname, pace = best
    # 90 possessions/48 -> 0, 110 -> 100; higher pace = higher score (engine
    # compares the two sides, yielding the requested pace differential).
    norm = max(0.0, min(100.0, (pace - 90.0) / 20.0 * 100.0))
    return _result(round(norm, 1), True, f"{pace:.1f} pace", "basketball-reference")


# --------------------------------------------------------------------------- #
# ESPN — team resolution + days rest before the next scheduled game
# --------------------------------------------------------------------------- #
def _espn_teams():
    global _espn_teams_cache
    if _espn_teams_cache is not None:
        return _espn_teams_cache
    teams = []
    try:
        data = requests.get(f"{ESPN}/teams", headers=UA, timeout=_TIMEOUT).json()
        for t in data["sports"][0]["leagues"][0]["teams"]:
            tm = t["team"]
            teams.append({"id": tm["id"], "names": [tm.get("displayName", ""), tm.get("name", ""),
                                                    tm.get("location", ""), tm.get("abbreviation", ""),
                                                    tm.get("shortDisplayName", "")]})
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        teams = []
    _espn_teams_cache = teams
    return teams


def _resolve_team_id(name):
    best, score = None, 0.0
    for t in _espn_teams():
        for cand in t["names"]:
            if cand and fuzzy(name, cand) > score:
                best, score = t, fuzzy(name, cand)
    return best["id"] if best and score >= 0.55 else None


def _parse_date(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def nba_rest(name):
    tid = _resolve_team_id(name)
    if not tid:
        return _result(detail=f"Couldn't resolve '{name}' on ESPN", source="ESPN")
    try:
        data = requests.get(f"{ESPN}/teams/{tid}/schedule", headers=UA, timeout=_TIMEOUT).json()
    except (requests.RequestException, ValueError):
        return _result(detail="ESPN schedule unavailable", source="ESPN")

    played, upcoming = [], []
    for ev in data.get("events", []):
        dt = _parse_date(ev.get("date", ""))
        if not dt:
            continue
        comp = (ev.get("competitions") or [{}])[0]
        done = comp.get("status", {}).get("type", {}).get("completed")
        (played if done else upcoming).append(dt)
    if not played:
        return _result(detail="No completed games on ESPN schedule", source="ESPN")

    last = max(played)
    nxt = min(upcoming) if upcoming else None
    ref = nxt or datetime.now(timezone.utc)
    days = (ref - last).days
    if days < 0:
        return _result(detail="No clear rest window (schedule ambiguous)", source="ESPN")
    score = max(0.0, min(100.0, days / 4.0 * 100.0))   # 0 days = back-to-back, 4+ = fully rested
    when = "before next game" if nxt else "since last game"
    return _result(round(score, 1), True, f"{days}d rest {when}", "ESPN")


# --------------------------------------------------------------------------- #
# ATS — requires historical closing spreads; no free key-less source. Honest n/a.
# --------------------------------------------------------------------------- #
def nba_ats(name):
    return _result(
        detail="Last-10 ATS needs historical closing spreads (no free key-less feed); add a lines source to enable",
        source="—")
