"""Live soccer stats for the two Soccer sport-specific variables.

  xG for/against (last 5)      -> fbref.com team match logs
  press intensity differential -> fbref.com defensive actions (PPDA-style)

fbref.com sits behind Cloudflare and frequently returns 403 to non-browser
clients, and resolving an arbitrary typed club name to its fbref team URL has no
stable key-free lookup. So both functions attempt fbref and otherwise degrade
gracefully (available=False with a clear reason) rather than fabricating numbers
— consistent with the rest of the tool's honesty policy. When fbref is reachable
and the club resolves, real xG is parsed and scored.

Each public function returns the standard dict
    {"score": 0-100 | None, "available": bool, "detail": str, "source": str}
and never raises.
"""
import threading

import requests

from mma_sources import fuzzy, _result

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
FBREF = "https://fbref.com"
_TIMEOUT = 20

_lock = threading.Lock()
_search_cache = {}   # club name (lower) -> fbref team URL | None


def _fbref_team_url(name):
    """Resolve a club name to its fbref squad page via the site search."""
    key = name.lower().strip()
    if key in _search_cache:
        return _search_cache[key]
    url = None
    try:
        from bs4 import BeautifulSoup
        r = requests.get(f"{FBREF}/en/search/search.fcgi", headers=UA, timeout=_TIMEOUT,
                         params={"search": name})
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            best, score = None, 0.0
            # search results link to /en/squads/<id>/<Club-Name>-Stats
            for a in soup.select('a[href*="/squads/"]'):
                label = a.get_text(strip=True)
                s = fuzzy(name, label.replace(" Stats", ""))
                if s > score:
                    best, score = a.get("href"), s
            if best and score >= 0.6:
                url = FBREF + best
    except requests.RequestException:
        url = None
    _search_cache[key] = url
    return url


def _team_xg(name):
    """(xg_for_avg, xg_against_avg, matches) over the most recent matches, or None."""
    url = _fbref_team_url(name)
    if not url:
        return None
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=UA, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        # the "Scores & Fixtures" table carries per-match xG / xGA columns
        rows = []
        tb = soup.find("table", id=lambda x: x and x.startswith("matchlogs"))
        if not tb:
            return None
        for tr in tb.select("tbody tr"):
            xg = tr.find("td", {"data-stat": "xg_for"}) or tr.find("td", {"data-stat": "xg"})
            xga = tr.find("td", {"data-stat": "xg_against"}) or tr.find("td", {"data-stat": "xga"})
            if not xg or not xga:
                continue
            try:
                rows.append((float(xg.get_text(strip=True)), float(xga.get_text(strip=True))))
            except ValueError:
                continue
        last5 = rows[-5:]
        if not last5:
            return None
        xf = sum(x for x, _ in last5) / len(last5)
        xa = sum(a for _, a in last5) / len(last5)
        return xf, xa, len(last5)
    except requests.RequestException:
        return None


def soccer_xg(name):
    try:
        res = _team_xg(name)
    except Exception as e:
        return _result(detail=f"fbref error: {e}", source="fbref")
    if not res:
        return _result(detail=f"fbref unreachable or '{name}' not resolvable (Cloudflare/club lookup)",
                       source="fbref")
    xf, xa, n = res
    diff = xf - xa                       # net expected-goal edge
    score = max(0.0, min(100.0, 50.0 + diff * 25.0))   # +2 net xG ~ elite
    return _result(round(score, 1), True,
                   f"xG {xf:.2f} for / {xa:.2f} against, last {n}", "fbref")


def soccer_press(name):
    # PPDA / pressing intensity is not exposed in a stable key-free fbref endpoint
    # for arbitrary clubs; attempting it would mean fabricating. Degrade honestly.
    return _result(
        detail="Press intensity (PPDA) needs fbref defensive-actions data, unavailable key-free for arbitrary clubs",
        source="fbref")
