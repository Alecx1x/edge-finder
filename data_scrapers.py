"""Per-variable data gathering from free public sources, with graceful fallback.

Every scraper returns a `ScoreResult` for each side. A result is either:
  - available=True  with a 0-100 score (higher = better for that side), or
  - available=False with a message (the scoring engine then ignores it).

Honesty note: reliably auto-resolving arbitrary typed names to records across
every league/sport from free sources is not possible. We implement real signals
where a stable free endpoint exists (ESPN public JSON for recent form & injuries,
structural home/away for travel) and degrade gracefully everywhere else with a
clear reason, rather than fabricating numbers. The scoring engine only lets
*available* signals move the model off the market line.
"""
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Optional

import requests

import mma_sources
import bball_sources
import soccer_sources
import tennis_sources

ESPN = "https://site.api.espn.com/apis/site/v2/sports"

# Sport category -> (espn_sport, espn_league). Only stable, key-free leagues.
ESPN_LEAGUE = {
    "Basketball": ("basketball", "nba"),
    # Soccer/Tennis/MMA span many leagues / lack a stable name->id lookup on the
    # free endpoint, so they fall back gracefully below.
}

_UA = {"User-Agent": "edge-finder/1.0 (+local research tool)"}


@dataclass
class ScoreResult:
    score: Optional[float] = None
    available: bool = False
    detail: str = ""
    source: str = ""

    def dict(self):
        return asdict(self)


def _na(reason, source=""):
    return ScoreResult(available=False, detail=reason, source=source)


def _wrap(d):
    """Convert a dict returned by mma_sources into a ScoreResult."""
    return ScoreResult(d.get("score"), bool(d.get("available")),
                       d.get("detail", ""), d.get("source", ""))


def _get_json(url, params=None):
    try:
        r = requests.get(url, params=params, headers=_UA, timeout=12)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


# --------------------------------------------------------------------------- #
# ESPN helpers (Basketball / NBA)
# --------------------------------------------------------------------------- #
_espn_team_cache = {}


def _espn_teams(sport, league):
    key = (sport, league)
    if key in _espn_team_cache:
        return _espn_team_cache[key]
    data = _get_json(f"{ESPN}/{sport}/{league}/teams")
    teams = []
    try:
        for t in data["sports"][0]["leagues"][0]["teams"]:
            tm = t["team"]
            teams.append(
                {
                    "id": tm["id"],
                    "names": [
                        tm.get("displayName", ""),
                        tm.get("name", ""),
                        tm.get("location", ""),
                        tm.get("abbreviation", ""),
                        tm.get("shortDisplayName", ""),
                    ],
                }
            )
    except (TypeError, KeyError, IndexError):
        teams = []
    _espn_team_cache[key] = teams
    return teams


def _match_team(name, teams):
    best, score = None, 0.0
    nl = mma_sources.fold(name).lower().strip()
    for t in teams:
        for cand in t["names"]:
            if not cand:
                continue
            cl = mma_sources.fold(cand).lower()
            s = 0.95 if (nl in cl or cl in nl) else SequenceMatcher(None, nl, cl).ratio()
            if s > score:
                best, score = t, s
    return best if score >= 0.55 else None


def _espn_recent_form(sport, league, team_id, n=10):
    data = _get_json(f"{ESPN}/{sport}/{league}/teams/{team_id}/schedule")
    if not data:
        return None
    wins = losses = 0
    streak_char, streak = None, 0
    for ev in data.get("events", []):
        try:
            comp = ev["competitions"][0]
            done = comp.get("status", {}).get("type", {}).get("completed")
            if not done:
                continue
            for c in comp["competitors"]:
                if c["id"] == str(team_id):
                    res = c.get("winner")
                    if res is True:
                        wins += 1
                        ch = "W"
                    elif res is False:
                        losses += 1
                        ch = "L"
                    else:
                        ch = None
                    if ch:
                        if streak_char == ch:
                            streak += 1
                        else:
                            streak_char, streak = ch, 1
        except (KeyError, IndexError, TypeError):
            continue
        if wins + losses >= n:
            break
    if wins + losses == 0:
        return None
    return wins, losses, streak_char, streak


def _espn_injury_counts(sport, league):
    data = _get_json(f"{ESPN}/{sport}/{league}/injuries")
    if not data:
        return None
    counts = {}
    for grp in data.get("injuries", []):
        team = grp.get("displayName") or grp.get("team", {}).get("displayName", "")
        counts[team.lower()] = len(grp.get("injuries", []))
    return counts


# --------------------------------------------------------------------------- #
# Variable scrapers — each returns (ScoreResult_a, ScoreResult_b)
# --------------------------------------------------------------------------- #
def _form(sport, name_a, name_b, event):
    if sport == "MMA":
        return _wrap(mma_sources.recent_form(name_a)), _wrap(mma_sources.recent_form(name_b))
    if sport not in ESPN_LEAGUE:
        return (_na(f"No free auto-source wired for {sport} form", "—"),) * 2
    es, league = ESPN_LEAGUE[sport]
    teams = _espn_teams(es, league)
    if not teams:
        return (_na("ESPN teams endpoint unavailable", "ESPN"),) * 2

    def one(name):
        t = _match_team(name, teams)
        if not t:
            return _na(f"Couldn't resolve '{name}' on ESPN", "ESPN")
        form = _espn_recent_form(es, league, t["id"])
        if not form:
            return _na("No completed games found", "ESPN")
        w, l, sc, sl = form
        pct = w / (w + l)
        score = pct * 100
        if sc == "W":
            score = min(100, score + min(8, sl * 2))
        elif sc == "L":
            score = max(0, score - min(8, sl * 2))
        streak = f"{sl}{sc}" if sc else "—"
        return ScoreResult(round(score, 1), True, f"{w}-{l} L10, streak {streak}", "ESPN")

    return one(name_a), one(name_b)


def _injuries(sport, name_a, name_b, event):
    if sport == "MMA":
        return _wrap(mma_sources.injury_health(name_a)), _wrap(mma_sources.injury_health(name_b))
    if sport not in ESPN_LEAGUE:
        return (_na(f"No free injury feed wired for {sport}", "—"),) * 2
    es, league = ESPN_LEAGUE[sport]
    counts = _espn_injury_counts(es, league)
    if counts is None:
        return (_na("ESPN injuries endpoint unavailable", "ESPN"),) * 2
    teams = _espn_teams(es, league)

    def one(name):
        t = _match_team(name, teams)
        if not t:
            return _na(f"Couldn't resolve '{name}' on ESPN", "ESPN")
        disp = t["names"][0].lower()
        n = counts.get(disp)
        if n is None:  # fuzzy fall-through on the injuries feed's own labels
            best, bs = None, 0.0
            for k, c in counts.items():
                s = 0.95 if (disp in k or k in disp) else SequenceMatcher(None, disp, k).ratio()
                if s > bs:
                    best, bs = c, s
            n = best if bs >= 0.6 else 0  # resolved team absent from feed => 0 injuries
        score = max(30, 100 - n * 8)  # more bodies out -> lower health score
        return ScoreResult(score, True, f"{n} listed", "ESPN")

    return one(name_a), one(name_b)


def _head_to_head(sport, name_a, name_b, event):
    if sport == "MMA":
        ra, rb = mma_sources.head_to_head(name_a, name_b)
        return _wrap(ra), _wrap(rb)
    msg = "No free H2H archive auto-resolvable; supply manually to weight it"
    return _na(msg, "—"), _na(msg, "—")


def _travel_fatigue(sport, name_a, name_b, event):
    home = (event.get("home_team") or "").lower()
    away = (event.get("away_team") or "").lower()
    if not home or not away:
        return (_na("No home/away context (neutral venue)", "structural"),) * 2

    def one(name):
        nl = name.lower()
        if nl in home or home in nl:
            return ScoreResult(60.0, True, "home (rested)", "structural")
        if nl in away or away in nl:
            return ScoreResult(42.0, True, "away (travel)", "structural")
        return ScoreResult(50.0, True, "neutral", "structural")

    return one(name_a), one(name_b)


def _weather(sport, name_a, name_b, event):
    # Open-Meteo is free/no-key, but we have no reliable venue geocode from the
    # odds feed, so we can't fetch conditions for an arbitrary match. Degrade.
    msg = "Venue not geocodable from odds feed; weather skipped"
    return _na(msg, "Open-Meteo"), _na(msg, "Open-Meteo")


def _line_movement(sport, name_a, name_b, event):
    if sport == "MMA":
        ra, rb = mma_sources.public_sharp(name_a, name_b)
        return _wrap(ra), _wrap(rb)
    msg = "Needs historical line snapshots (free tier gives one snapshot only)"
    return _na(msg, "—"), _na(msg, "—")


def _social(sport, name_a, name_b, event):
    if sport == "MMA":
        return _wrap(mma_sources.social_sentiment(name_a)), _wrap(mma_sources.social_sentiment(name_b))
    msg = "No free sentiment API; requires paid social/odds aggregator"
    return _na(msg, "—"), _na(msg, "—")


# --------------------------------------------------------------------------- #
# Sport-specific advanced stats (collapsible per-sport panel in the UI)
# --------------------------------------------------------------------------- #
def _mma_pair(fn):
    """Wrap a single-fighter mma_sources stat fn into a (result_a, result_b) scraper."""
    def scraper(sport, name_a, name_b, event):
        return _wrap(fn(name_a)), _wrap(fn(name_b))
    return scraper


def _bball_pair(fn):
    def scraper(sport, name_a, name_b, event):
        return _wrap(fn(name_a)), _wrap(fn(name_b))
    return scraper


def _soccer_pair(fn):
    def scraper(sport, name_a, name_b, event):
        return _wrap(fn(name_a)), _wrap(fn(name_b))
    return scraper


def _tennis_surface(sport, name_a, name_b, event):
    surface = tennis_sources.surface_from_event(event)
    return (_wrap(tennis_sources.tennis_surface(name_a, surface)),
            _wrap(tennis_sources.tennis_surface(name_b, surface)))


def _tennis_pair(fn):
    def scraper(sport, name_a, name_b, event):
        return _wrap(fn(name_a)), _wrap(fn(name_b))
    return scraper


_SCRAPERS = {
    # core (all sports)
    "recent_form": _form,
    "injuries": _injuries,
    "head_to_head": _head_to_head,
    "travel_fatigue": _travel_fatigue,
    "weather": _weather,
    "line_movement": _line_movement,
    "social_sentiment": _social,

    # MMA advanced (ufcstats.com)
    "mma_sig_strikes": _mma_pair(mma_sources.mma_sig_strikes),
    "mma_strike_acc": _mma_pair(mma_sources.mma_strike_acc),
    "mma_td_attempts": _mma_pair(mma_sources.mma_td_attempts),
    "mma_td_acc": _mma_pair(mma_sources.mma_td_acc),
    "mma_td_def": _mma_pair(mma_sources.mma_td_def),
    "mma_sub_attempts": _mma_pair(mma_sources.mma_sub_attempts),

    # Basketball advanced (basketball-reference.com / ESPN schedule)
    "nba_ats": _bball_pair(bball_sources.nba_ats),
    "nba_rest": _bball_pair(bball_sources.nba_rest),
    "nba_pace": _bball_pair(bball_sources.nba_pace),

    # Soccer advanced (fbref.com)
    "soccer_xg": _soccer_pair(soccer_sources.soccer_xg),
    "soccer_press": _soccer_pair(soccer_sources.soccer_press),

    # Tennis advanced (Jeff Sackmann tennis_atp)
    "tennis_surface": _tennis_surface,
    "tennis_aces": _tennis_pair(tennis_sources.tennis_aces),
    "tennis_bp": _tennis_pair(tennis_sources.tennis_bp),
}


def gather(sport, name_a, name_b, matchup, variables):
    """Run each applicable scraper. Returns {var_key: {"a": {...}, "b": {...}}}."""
    event = matchup
    out = {}
    for v in variables:
        fn = _SCRAPERS.get(v["key"])
        if not fn:
            out[v["key"]] = {"a": _na("not implemented").dict(), "b": _na("not implemented").dict()}
            continue
        try:
            ra, rb = fn(sport, name_a, name_b, event)
        except Exception as e:  # never let a flaky source crash the run
            ra = rb = _na(f"source error: {e}")
        out[v["key"]] = {"a": ra.dict(), "b": rb.dict()}
    return out
