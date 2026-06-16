"""Live tennis stats from Jeff Sackmann's tennis_atp dataset (raw GitHub CSVs).

  https://github.com/JeffSackmann/tennis_atp  (atp_matches_YYYY.csv)

Three sport-specific variables:
  surface win %       -> wins/(wins+losses) on the current tournament surface
  aces / match        -> average aces per match
  break-point conv.   -> return break points won / return break points faced

Each public function returns the standard plain dict
    {"score": 0-100 | None, "available": bool, "detail": str, "source": str}
and never raises — unreachable data degrades to available=False with a reason.
Player names are fuzzy-matched so partial inputs ("Alcaraz", "djokovic") resolve.
"""
import csv
import io
import threading

import requests

from mma_sources import fuzzy, _result  # reuse the shared fuzzy matcher + result shape

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
_RAW = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv"
_TIMEOUT = 20
# Anchored to the app "today" (2026); pull a rolling window of recent seasons.
_YEARS = (2026, 2025, 2024)

_lock = threading.Lock()
_matches_cache = None       # list of parsed match dicts (lazy, fetched once)
_player_index = None        # lower full_name -> canonical full_name


def _to_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _load():
    """Fetch + parse the recent-season CSVs once, building a flat match list."""
    global _matches_cache, _player_index
    if _matches_cache is not None:
        return _matches_cache
    with _lock:
        if _matches_cache is not None:
            return _matches_cache
        rows, names = [], {}
        for yr in _YEARS:
            try:
                r = requests.get(_RAW.format(year=yr), headers=UA, timeout=_TIMEOUT)
                if r.status_code != 200:
                    continue
            except requests.RequestException:
                continue
            for d in csv.DictReader(io.StringIO(r.text)):
                w, l = d.get("winner_name", ""), d.get("loser_name", "")
                if not w or not l:
                    continue
                names[w.lower()] = w
                names[l.lower()] = l
                rows.append({
                    "surface": (d.get("surface") or "").strip(),
                    "w": w, "l": l,
                    "w_ace": _to_int(d.get("w_ace")), "l_ace": _to_int(d.get("l_ace")),
                    "w_bpFaced": _to_int(d.get("w_bpFaced")), "w_bpSaved": _to_int(d.get("w_bpSaved")),
                    "l_bpFaced": _to_int(d.get("l_bpFaced")), "l_bpSaved": _to_int(d.get("l_bpSaved")),
                })
        _matches_cache = rows
        _player_index = names
        return rows


def _resolve(name):
    """Best fuzzy match of a typed name to a canonical player name in the data."""
    _load()
    if not _player_index:
        return None
    best, score = None, 0.0
    for low, full in _player_index.items():
        s = fuzzy(name, full)
        if s > score:
            best, score = full, s
    return best if score >= 0.6 else None


def _player_matches(name):
    """(canonical_name, [matches involving them]) or (None, [])."""
    canon = _resolve(name)
    if not canon:
        return None, []
    mine = [m for m in _load() if m["w"] == canon or m["l"] == canon]
    return canon, mine


# Map a tournament/league string from the odds feed to a court surface.
def surface_from_event(event):
    title = " ".join(str(event.get(k, "")) for k in ("league", "sport_key", "home_team")).lower()
    if any(w in title for w in ("french", "roland", "clay", "madrid", "rome", "monte")):
        return "Clay"
    if any(w in title for w in ("wimbledon", "grass", "halle", "queen")):
        return "Grass"
    if "hard" in title or "open" in title or "atp" in title:
        return "Hard"
    return None


def tennis_surface(name, surface=None):
    try:
        canon, mine = _player_matches(name)
    except Exception as e:
        return _result(detail=f"Sackmann data error: {e}", source="Sackmann tennis_atp")
    if not canon:
        return _result(detail=f"Couldn't resolve '{name}' in ATP data", source="Sackmann tennis_atp")
    # If we couldn't infer the tournament surface, use the player's most-played one.
    if not surface:
        counts = {}
        for m in mine:
            counts[m["surface"]] = counts.get(m["surface"], 0) + 1
        surface = max(counts, key=counts.get) if counts else None
    if not surface:
        return _result(detail="No surface info available", source="Sackmann tennis_atp")
    on = [m for m in mine if m["surface"] == surface]
    wins = sum(1 for m in on if m["w"] == canon)
    n = len(on)
    if n == 0:
        return _result(detail=f"No recent {surface}-court matches", source="Sackmann tennis_atp")
    pct = wins / n * 100
    return _result(round(pct, 1), True, f"{wins}-{n - wins} on {surface} ({pct:.0f}%)", "Sackmann tennis_atp")


def tennis_aces(name):
    try:
        canon, mine = _player_matches(name)
    except Exception as e:
        return _result(detail=f"Sackmann data error: {e}", source="Sackmann tennis_atp")
    if not canon:
        return _result(detail=f"Couldn't resolve '{name}' in ATP data", source="Sackmann tennis_atp")
    vals = [(m["w_ace"] if m["w"] == canon else m["l_ace"]) for m in mine]
    vals = [v for v in vals if v is not None]
    if not vals:
        return _result(detail="No ace data on record", source="Sackmann tennis_atp")
    avg = sum(vals) / len(vals)
    score = max(0.0, min(100.0, avg / 15.0 * 100.0))   # ~15 aces/match = elite server
    return _result(round(score, 1), True, f"{avg:.1f} aces/match ({len(vals)} matches)", "Sackmann tennis_atp")


def tennis_bp(name):
    """Break-point conversion = return BPs won / return BPs faced (as the returner)."""
    try:
        canon, mine = _player_matches(name)
    except Exception as e:
        return _result(detail=f"Sackmann data error: {e}", source="Sackmann tennis_atp")
    if not canon:
        return _result(detail=f"Couldn't resolve '{name}' in ATP data", source="Sackmann tennis_atp")
    opp_faced = opp_saved = 0
    for m in mine:
        # When `canon` wins, the loser served; loser's bpFaced are canon's return chances.
        if m["w"] == canon:
            f, s = m["l_bpFaced"], m["l_bpSaved"]
        else:
            f, s = m["w_bpFaced"], m["w_bpSaved"]
        if f is not None and s is not None:
            opp_faced += f
            opp_saved += s
    if opp_faced == 0:
        return _result(detail="No break-point data on record", source="Sackmann tennis_atp")
    converted = opp_faced - opp_saved
    conv = converted / opp_faced * 100
    return _result(round(max(0.0, min(100.0, conv)), 1), True,
                   f"{conv:.0f}% break points converted ({converted}/{opp_faced})", "Sackmann tennis_atp")
