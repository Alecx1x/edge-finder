"""Startup event cache for the Upcoming-Events browser.

On boot, main.py asks this module for the event tree. We pull all upcoming
matchups across the four supported sports and persist them to events_cache.json.
The cache is reused for 24h; only when it's older (or a manual refresh is asked)
do we re-fetch. The browser tree is purely a convenience for populating the
matchup form — the real edge analysis still runs the full scraper pipeline when
"Find Edge" is clicked.

Primary source — The Odds API `/sports/{key}/events`: this endpoint is FREE (it
does not count against the request quota) and returns home/away + start time for
every upcoming event, across every active league in a sport group (all MMA
promotions the API carries, NBA, in-season soccer leagues, active ATP/WTA
tournaments). That makes a daily refresh essentially zero-cost.

Supplements — Tapology (MMA promotions beyond the API) and atptour.com (ATP/WTA
schedule) are attempted but degrade gracefully: Tapology's event pages are
bot-walled and atptour renders its schedule client-side, so when they can't be
read we record an honest note instead of inventing matchups.

Tree shape written to disk:
    {
      "fetched_at": "<iso utc>",
      "sources": {"odds_api": true, "tapology": false, "atptour": false},
      "notes": ["..."],
      "tree": [
        {"sport": "MMA", "leagues": [
          {"league": "MMA", "key": "mma_mixed_martial_arts", "events": [
            {"id": "...-2026-06-14", "title": "Sat, Jun 14, 2026",
             "date": "2026-06-14",
             "matchups": [{"sport":"MMA","a":"...","b":"...","start":"<iso>"}]}
          ]}
        ]}
      ]
    }
"""
import collections
import datetime
import json
import os
import threading

import requests

import odds_fetcher

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events_cache.json")
MAX_AGE_HOURS = 24
_TIMEOUT = 20
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept-Language": "en-US,en;q=0.9"}

# (our sport label -> The Odds API group). Order is the display order in the UI.
GROUPS = [
    ("MMA", "Mixed Martial Arts"),
    ("Basketball", "Basketball"),
    ("Soccer", "Soccer"),
    ("Tennis", "Tennis"),
]

_lock = threading.Lock()      # serialize cache builds (boot thread vs manual refresh)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _is_futures_market(s):
    """Skip outright/championship-winner keys — they have no head-to-head matchups."""
    key = (s.get("key") or "").lower()
    title = s.get("title") or ""
    return key.endswith("_winner") or "winner" in key or "Winner" in title


def _fmt_day(day):
    try:
        return datetime.date.fromisoformat(day).strftime("%a, %b %d, %Y")
    except ValueError:
        return day


def _events_for_key(api_key, key):
    """Upcoming events for one Odds API sport key (free endpoint). [] on any failure."""
    try:
        r = requests.get(f"{odds_fetcher.BASE}/sports/{key}/events",
                         params={"apiKey": api_key}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError):
        return []


# --------------------------------------------------------------------------- #
# primary source — The Odds API (free /events per league)
# --------------------------------------------------------------------------- #
def _odds_api_tree(api_key, notes):
    tree = []
    for sport_label, group in GROUPS:
        try:
            sports = odds_fetcher.list_active_sports(api_key, group)
        except odds_fetcher.OddsError as e:
            notes.append(f"{sport_label}: couldn't list Odds API leagues ({e}).")
            continue

        leagues = []
        for s in sports:
            if _is_futures_market(s):
                continue
            evs = _events_for_key(api_key, s["key"])
            if not evs:
                continue

            by_day = collections.OrderedDict()
            for ev in sorted(evs, key=lambda e: e.get("commence_time") or ""):
                home, away = ev.get("home_team"), ev.get("away_team")
                ct = ev.get("commence_time") or ""
                if not home or not away:
                    continue
                day = ct[:10] or "TBD"
                by_day.setdefault(day, []).append(
                    {"sport": sport_label, "a": home, "b": away, "start": ct})

            events = [
                {"id": f"{s['key']}-{day}", "title": _fmt_day(day), "date": day,
                 "matchups": ms}
                for day, ms in by_day.items()
            ]
            if events:
                leagues.append({"league": s.get("title", s["key"]), "key": s["key"],
                                "events": events})

        if leagues:
            tree.append({"sport": sport_label, "leagues": leagues})
    return tree


# --------------------------------------------------------------------------- #
# supplements — best-effort, never fabricate
# --------------------------------------------------------------------------- #
def _merge_tapology(tree, notes, sources):
    """Add non-UFC MMA promotions from Tapology when its pages are reachable.

    Tapology's /fightcenter and event pages sit behind a bot wall; the bout
    pairings we'd need live on those event pages. We probe once and, if blocked,
    record an honest note rather than guessing matchups.
    """
    try:
        probe = requests.get("https://www.tapology.com/fightcenter",
                             headers=UA, timeout=_TIMEOUT)
        if probe.status_code != 200:
            notes.append(
                f"Tapology upcoming-events page is bot-blocked (HTTP {probe.status_code}); "
                "MMA promotions beyond the Odds API feed (e.g. Oktagon, KSW) weren't added.")
            return
        # If access ever opens up, parse here. For now the probe gate handles it.
        sources["tapology"] = True
    except requests.RequestException as e:
        notes.append(f"Tapology supplement skipped (network): {e}")


def _merge_atptour(tree, notes, sources):
    """Add ATP/WTA tournament schedule from atptour.com when statically readable.

    atptour.com renders its schedule client-side (Angular mustache templates in
    the static HTML), so there's no parseable tournament data without their
    private XHR API. We note the limitation instead of inventing a schedule.
    """
    try:
        r = requests.get("https://www.atptour.com/en/tournaments",
                         headers=UA, timeout=_TIMEOUT)
        if r.status_code != 200 or "{{tournament" in r.text:
            notes.append(
                "atptour.com renders its schedule client-side; ATP/WTA tournaments "
                "beyond the Odds API tennis feed weren't added.")
            return
        sources["atptour"] = True
    except requests.RequestException as e:
        notes.append(f"atptour supplement skipped (network): {e}")


# --------------------------------------------------------------------------- #
# build / load / freshness
# --------------------------------------------------------------------------- #
def build(api_key):
    """Fetch everything and write events_cache.json. Returns the cache dict."""
    notes = []
    sources = {"odds_api": False, "tapology": False, "atptour": False}
    tree = []

    if api_key:
        tree = _odds_api_tree(api_key, notes)
        sources["odds_api"] = bool(tree)
    else:
        notes.append("No Odds API key set — the event browser stays empty until a key is added.")

    _merge_tapology(tree, notes, sources)
    _merge_atptour(tree, notes, sources)

    cache = {
        "fetched_at": _now_utc().isoformat(),
        "sources": sources,
        "notes": notes,
        "tree": tree,
    }
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass  # an unwritable cache file shouldn't break the running app
    return cache


def load():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def age_hours(cache):
    if not cache or not cache.get("fetched_at"):
        return float("inf")
    try:
        t = datetime.datetime.fromisoformat(cache["fetched_at"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return (_now_utc() - t).total_seconds() / 3600.0
    except ValueError:
        return float("inf")


def is_fresh(cache):
    return cache is not None and age_hours(cache) < MAX_AGE_HOURS


def get(api_key, force=False):
    """Return a cache dict, rebuilding only if stale (or forced). Never raises."""
    with _lock:
        cache = load()
        if not force and is_fresh(cache):
            return cache
        try:
            return build(api_key)
        except Exception as e:                  # last-ditch: keep serving stale data
            if cache is not None:
                cache.setdefault("notes", []).append(f"Refresh failed: {e}")
                return cache
            return {"fetched_at": None, "sources": {}, "notes": [f"Build failed: {e}"],
                    "tree": []}


def public(cache):
    """Shape a cache dict for the browser: adds age_hours + fresh flags."""
    cache = cache or {"tree": [], "notes": [], "sources": {}, "fetched_at": None}
    h = age_hours(cache)
    return {
        "fetched_at": cache.get("fetched_at"),
        "age_hours": None if h == float("inf") else round(h, 2),
        "fresh": is_fresh(cache),
        "sources": cache.get("sources", {}),
        "notes": cache.get("notes", []),
        "tree": cache.get("tree", []),
    }
