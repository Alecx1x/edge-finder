"""Live MMA data sources for the five fight-specific scoring variables.

  recent_form / head_to_head -> ufcstats.com  (solves its SHA-256 proof-of-work
                                               anti-bot wall, then parses fight
                                               history tables)
  injury / health            -> tapology.com  (layoff since last fight + injury
                                               keyword scan on the fighter page)
  public % vs sharp money     -> ActionNetwork free public JSON (tickets% vs
                                               money% per side)
  social sentiment            -> Google News RSS (pos/neg headline ratio)

Every public function returns a plain dict:
    {"score": 0-100 | None, "available": bool, "detail": str, "source": str}
and never raises — any unreachable source degrades to available=False with a
human-readable reason, so the scoring engine simply ignores it.

Fuzzy name matching is used throughout so partial inputs ("jones", "izzy")
still resolve.
"""
import hashlib
import re
import threading
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

import requests

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
UFC_BASE = "http://www.ufcstats.com"
AN_SCOREBOARD = "https://api.actionnetwork.com/web/v2/scoreboard/ufc"
GNEWS = "https://news.google.com/rss/search"

_TIMEOUT = 18


def _result(score=None, available=False, detail="", source=""):
    return {"score": score, "available": available, "detail": detail, "source": source}


def fold(text):
    """Transliterate accents/diacritics to plain ASCII so 'Procházka' == 'Prochazka'.

    NFKD splits each accented glyph into base char + combining mark; dropping the
    marks (Unicode category 'Mn') leaves the bare letter (á->a, č->c, ř->r, ł->l).
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # a few letters don't decompose (ł, ø, ð, đ) — map them explicitly
    table = {"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ð": "d", "đ": "d",
             "Đ": "D", "þ": "th", "ß": "ss", "æ": "ae", "œ": "oe"}
    return "".join(table.get(ch, ch) for ch in stripped)


def fuzzy(query, candidate):
    """0..1 similarity that rewards substring / token overlap (partial names).

    Names are accent-folded first so diacritics never block a match.
    """
    q, c = fold(query or "").lower().strip(), fold(candidate or "").lower().strip()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.93
    qt, ct = set(q.split()), set(c.split())
    overlap = len(qt & ct) / max(1, len(qt))
    return max(SequenceMatcher(None, q, c).ratio(), 0.9 * overlap)


# --------------------------------------------------------------------------- #
# UFCStats — proof-of-work session + fighter fight history (cached)
# --------------------------------------------------------------------------- #
_uf_session = requests.Session()
_uf_lock = threading.Lock()
_fighter_cache = {}   # resolved name (lower) -> fighter dict | None


def _uf_get(url, params=None, _depth=0):
    """GET a ufcstats URL, solving the JS PoW challenge once per session."""
    r = _uf_session.get(url, params=params, headers=UA, timeout=_TIMEOUT)
    if "Checking your browser" in r.text and _depth == 0:
        m_nonce = re.search(r'nonce="([0-9a-f]+)"', r.text)
        m_tlen = re.search(r"new Array\((\d+)\+1\)\.join\('0'\)", r.text)
        if not (m_nonce and m_tlen):
            return r
        nonce, tlen = m_nonce.group(1), int(m_tlen.group(1))
        target, n = "0" * tlen, 0
        while hashlib.sha256(f"{nonce}:{n}".encode()).hexdigest()[:tlen] != target:
            n += 1
            if n > 5_000_000:           # safety valve; PoW is normally ~256 tries
                return r
        _uf_session.post(f"{UFC_BASE}/__c", data={"nonce": nonce, "n": n},
                         headers=UA, timeout=_TIMEOUT)
        return _uf_get(url, params=params, _depth=1)
    return r


def _resolve_fighter(name):
    """Find the best-matching ufcstats fighter and parse their fight history."""
    key = name.lower().strip()
    if key in _fighter_cache:
        return _fighter_cache[key]

    from bs4 import BeautifulSoup
    query = name.split()[-1] if name.split() else name      # last name = best search hit
    with _uf_lock:
        r = _uf_get(f"{UFC_BASE}/statistics/fighters/search", params={"query": query})
    if "Checking your browser" in r.text or r.status_code != 200:
        _fighter_cache[key] = None
        return None

    soup = BeautifulSoup(r.text, "lxml")
    best, best_score = None, 0.0
    for row in soup.select("tr.b-statistics__table-row"):
        cells = row.select("td.b-statistics__table-col")
        if len(cells) < 3:
            continue
        link = row.select_one('a[href*="fighter-details"]')
        if not link:
            continue
        first = cells[0].get_text(strip=True)
        last = cells[1].get_text(strip=True)
        nick = cells[2].get_text(strip=True)
        full = f"{first} {last}".strip()
        s = max(fuzzy(name, full), fuzzy(name, nick))
        if s > best_score:
            best, best_score = {"name": full, "url": link["href"]}, s

    if not best or best_score < 0.5:
        _fighter_cache[key] = None
        return None

    fighter = _parse_fighter_page(best["url"], best["name"])
    _fighter_cache[key] = fighter
    return fighter


def _parse_fighter_page(url, fallback_name):
    from bs4 import BeautifulSoup
    with _uf_lock:
        r = _uf_get(url)
    if r.status_code != 200 or "Checking your browser" in r.text:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    title = soup.select_one("span.b-content__title-highlight")
    record = soup.select_one("span.b-content__title-record")
    stats = _parse_career_stats(soup)                       # SLpM / accuracy / TD / sub
    fights = []                                              # most-recent first
    for row in soup.select("tr.b-fight-details__table-row"):
        if "b-fight-details__table-row__head" in (row.get("class") or []):
            continue
        cols = row.select("td.b-fight-details__table-col")
        if len(cols) < 2:
            continue
        flag = cols[0].get_text(strip=True).lower()         # win / loss / nc / draw
        names = [a.get_text(strip=True) for a in cols[1].select("a")]
        opponent = names[1] if len(names) > 1 else ""
        if flag in ("win", "loss", "nc", "draw") and opponent:
            fights.append({"result": flag, "opponent": opponent})
    return {
        "name": title.get_text(strip=True) if title else fallback_name,
        "record": record.get_text(strip=True).replace("Record:", "").strip() if record else "",
        "fights": fights,
        "stats": stats,
        "url": url,
    }


# --------------------------------------------------------------------------- #
# UFCStats — career striking / grappling stats (parsed off the fighter page)
# --------------------------------------------------------------------------- #
# Labels as they appear on the fighter page -> our normalized keys.
_STAT_LABELS = {
    "slpm": "slpm",            # sig. strikes landed per minute
    "str. acc.": "str_acc",    # sig. strike accuracy %
    "sapm": "sapm",            # sig. strikes absorbed per minute
    "str. def": "str_def",     # sig. strike defense %
    "td avg.": "td_avg",       # takedowns landed per 15 min
    "td acc.": "td_acc",       # takedown accuracy %
    "td def.": "td_def",       # takedown defense %
    "sub. avg.": "sub_avg",    # submission attempts per 15 min
}


def _parse_career_stats(soup):
    """Pull SLpM / accuracy / takedown / submission averages off a fighter page."""
    stats = {}
    for li in soup.select("li.b-list__box-list-item"):
        txt = li.get_text(" ", strip=True)
        if ":" not in txt:
            continue
        label, _, value = txt.partition(":")
        key = _STAT_LABELS.get(label.strip().lower())
        if not key:
            continue
        m = re.search(r"-?\d+(?:\.\d+)?", value)
        if m:
            stats[key] = float(m.group(0))   # percents stored as their number (e.g. 58.0)
    return stats


def _stat_for(name):
    """Resolve a fighter and return (career-stats dict, resolved-name) or (None, None)."""
    f = _resolve_fighter(name)
    if not f:
        return None, None
    return f.get("stats") or {}, f["name"]


def _norm(value, cap):
    """Scale a positive metric to 0-100 where `cap` (or more) tops out at 100."""
    return max(0.0, min(100.0, value / cap * 100.0))


def _missing(name, what):
    return _result(detail=f"No {what} for '{name}' on ufcstats", source="ufcstats")


def mma_sig_strikes(name):
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "slpm" not in stats:
        return _missing(name, "striking volume")
    slpm = stats["slpm"]
    return _result(round(_norm(slpm, 7.0), 1), True, f"{slpm:.2f} sig. str./min", "ufcstats")


def mma_strike_acc(name):
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "str_acc" not in stats:
        return _missing(name, "strike accuracy")
    acc = stats["str_acc"]
    return _result(round(max(0.0, min(100.0, acc)), 1), True, f"{acc:.0f}% sig. strikes land", "ufcstats")


def mma_td_attempts(name):
    """ufcstats reports TD landed/15min + TD accuracy; attempts = landed / accuracy."""
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "td_avg" not in stats:
        return _missing(name, "takedown volume")
    landed = stats["td_avg"]
    acc = stats.get("td_acc", 0) / 100.0
    attempts = landed / acc if acc > 0 else landed
    return _result(round(_norm(attempts, 5.0), 1), True,
                   f"~{attempts:.1f} TD att./15min ({landed:.1f} landed)", "ufcstats")


def mma_td_acc(name):
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "td_acc" not in stats:
        return _missing(name, "takedown accuracy")
    acc = stats["td_acc"]
    return _result(round(max(0.0, min(100.0, acc)), 1), True, f"{acc:.0f}% takedowns land", "ufcstats")


def mma_td_def(name):
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "td_def" not in stats:
        return _missing(name, "takedown defense")
    d = stats["td_def"]
    return _result(round(max(0.0, min(100.0, d)), 1), True, f"{d:.0f}% takedowns stuffed", "ufcstats")


def mma_sub_attempts(name):
    try:
        stats, who = _stat_for(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if stats is None or "sub_avg" not in stats:
        return _missing(name, "submission volume")
    sub = stats["sub_avg"]
    return _result(round(_norm(sub, 2.0), 1), True, f"{sub:.1f} sub att./15min", "ufcstats")


def recent_form(name):
    try:
        f = _resolve_fighter(name)
    except Exception as e:
        return _result(detail=f"ufcstats error: {e}", source="ufcstats")
    if not f:
        return _result(detail=f"Couldn't resolve '{name}' on ufcstats", source="ufcstats")
    if not f["fights"]:
        return _result(detail="No recorded fights found", source="ufcstats")

    last5 = f["fights"][:5]
    wins = sum(1 for x in last5 if x["result"] == "win")
    losses = sum(1 for x in last5 if x["result"] == "loss")
    decided = wins + losses
    base = (wins / decided * 100) if decided else 50.0

    # current streak from the most recent decided results
    streak_kind, streak = None, 0
    for x in f["fights"]:
        if x["result"] not in ("win", "loss"):
            continue
        if streak_kind is None:
            streak_kind = x["result"]
        if x["result"] == streak_kind:
            streak += 1
        else:
            break
    if streak_kind == "win":
        base = min(100.0, base + min(10, streak * 3))
    elif streak_kind == "loss":
        base = max(0.0, base - min(10, streak * 3))

    tag = {"win": "W", "loss": "L"}.get(streak_kind, "")
    detail = f"{wins}-{losses} last {len(last5)}" + (f", {streak}{tag} streak" if tag else "")
    return _result(round(base, 1), True, detail, "ufcstats")


def head_to_head(name_a, name_b):
    try:
        fa = _resolve_fighter(name_a)
    except Exception as e:
        msg = f"ufcstats error: {e}"
        return _result(detail=msg, source="ufcstats"), _result(detail=msg, source="ufcstats")
    if not fa:
        msg = f"Couldn't resolve '{name_a}' on ufcstats"
        return _result(detail=msg, source="ufcstats"), _result(detail=msg, source="ufcstats")

    a_wins = b_wins = 0
    for fight in fa["fights"]:
        if fuzzy(name_b, fight["opponent"]) >= 0.6:
            if fight["result"] == "win":
                a_wins += 1
            elif fight["result"] == "loss":
                b_wins += 1
    total = a_wins + b_wins
    if total == 0:
        msg = "No prior meetings on record"
        return (_result(detail=msg, source="ufcstats"),
                _result(detail=msg, source="ufcstats"))

    score_a = a_wins / total * 100
    da = f"leads H2H {a_wins}-{b_wins}" if a_wins >= b_wins else f"trails H2H {a_wins}-{b_wins}"
    db = f"leads H2H {b_wins}-{a_wins}" if b_wins >= a_wins else f"trails H2H {b_wins}-{a_wins}"
    return (_result(round(score_a, 1), True, da, "ufcstats"),
            _result(round(100 - score_a, 1), True, db, "ufcstats"))


# --------------------------------------------------------------------------- #
# Tapology — injury / health via layoff + injury keyword scan
# --------------------------------------------------------------------------- #
_TAP_BASE = "https://www.tapology.com"
# Specific enough to avoid false hits like "fighting out of Phoenix".
_INJURY_WORDS = ("injury", "injured", "surgery", "torn", "withdrew", "withdraws",
                 "undergoes", "rehab", "broken", "fractured", "pulled from", "ruled out")
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _days_since(date_text):
    """Parse 'December 03, 2022' -> approx days ago (calendar-free, ~30d months)."""
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", date_text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    day, year = int(m.group(2)), int(m.group(3))
    # rough ordinal day count; absolute scale only matters relatively
    serial = year * 360 + (mon - 1) * 30 + day
    now = 2026 * 360 + (6 - 1) * 30 + 4          # anchored to app "today" 2026-06-04
    return max(0, now - serial)


def injury_health(name):
    try:
        from bs4 import BeautifulSoup
        rs = requests.get(f"{_TAP_BASE}/search", headers=UA, timeout=_TIMEOUT,
                          params={"term": name, "search": "fighters", "model": "fighters"})
        soup = BeautifulSoup(rs.text, "lxml")
        best, best_score = None, 0.0
        for a in soup.select('a[href*="/fightcenter/fighters/"]'):
            href = a.get("href", "")
            raw = a.get_text(strip=True)
            # drop the quoted nickname and collapse spaces: 'Jon "Bones" Jones' -> 'Jon Jones'
            label = re.sub(r"\s+", " ", re.sub(r'"[^"]*"', " ", raw)).strip()
            # Notable fighters get clean (non-numeric) Tapology slugs; use that to
            # break ties between several same-named fighters (e.g. many "Jon Jones").
            slug = href.rsplit("/", 1)[-1]
            clean_bonus = 0.06 if not slug[:1].isdigit() else 0.0
            s = fuzzy(name, label) + clean_bonus
            if s > best_score:
                best, best_score = href, s
        if not best or best_score < 0.5:
            return _result(detail=f"Couldn't resolve '{name}' on Tapology", source="tapology")

        rf = requests.get(_TAP_BASE + best, headers=UA, timeout=_TIMEOUT)
        page = BeautifulSoup(rf.text, "lxml").get_text(" ", strip=True)

        m = re.search(r"Last Fight[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})", page)
        days = _days_since(m.group(1)) if m else None

        # Scope the status-flag scan to the top of the page (record / last fight /
        # upcoming bout / latest news) so we read *recent* status, not career archive.
        low = page[:2600].lower()
        hits = sorted({w for w in _INJURY_WORDS if w in low})
        injury_flag = bool(hits)

        if days is None and not injury_flag:
            return _result(detail="No last-fight date or status flags found", source="tapology")

        # Health proxy: fresher = healthier; long layoff or injury words = lower.
        score = 80.0
        notes = []
        if days is not None:
            layoff_pen = max(0.0, (days - 150) / 12.0)       # penalty grows after ~5 months
            score = max(40.0, 90.0 - layoff_pen)
            notes.append(f"last fought ~{days}d ago")
        if injury_flag:
            score = max(30.0, score - 22.0)
            notes.append("injury keyword in news: " + ", ".join(hits[:2]))
        return _result(round(score, 1), True, "; ".join(notes), "tapology")
    except Exception as e:
        return _result(detail=f"tapology error: {e}", source="tapology")


# --------------------------------------------------------------------------- #
# ActionNetwork — public % (tickets) vs sharp money %
# --------------------------------------------------------------------------- #
def _an_bet_info(game):
    """competitor_id -> {'tickets': pct, 'money': pct} aggregated across books."""
    agg = {}
    for book in (game.get("markets") or {}).values():
        for outcome in (book.get("event", {}) or {}).get("moneyline", []) or []:
            cid = outcome.get("competitor_id")
            info = outcome.get("bet_info") or {}
            tk = (info.get("tickets") or {}).get("percent")
            mo = (info.get("money") or {}).get("percent")
            if cid is None or (not tk and not mo):
                continue
            d = agg.setdefault(cid, {"tk": [], "mo": []})
            if tk:
                d["tk"].append(tk)
            if mo:
                d["mo"].append(mo)
    out = {}
    for cid, d in agg.items():
        out[cid] = {
            "tickets": sum(d["tk"]) / len(d["tk"]) if d["tk"] else None,
            "money": sum(d["mo"]) / len(d["mo"]) if d["mo"] else None,
        }
    return out


def public_sharp(name_a, name_b):
    na = _result(detail="No public betting data posted", source="ActionNetwork")
    nb = _result(detail="No public betting data posted", source="ActionNetwork")
    try:
        data = requests.get(AN_SCOREBOARD, headers=UA, timeout=_TIMEOUT).json()
    except Exception as e:
        msg = f"ActionNetwork error: {e}"
        return _result(detail=msg, source="ActionNetwork"), _result(detail=msg, source="ActionNetwork")

    target = None
    for game in data.get("competitions", []):
        comps = game.get("competitors", [])
        names = [(c.get("id"), (c.get("player") or {}).get("full_name", "")) for c in comps]
        if len(names) < 2:
            continue
        ma = max(names, key=lambda x: fuzzy(name_a, x[1]))
        mb = max(names, key=lambda x: fuzzy(name_b, x[1]))
        if ma[0] == mb[0]:
            continue
        if fuzzy(name_a, ma[1]) >= 0.55 and fuzzy(name_b, mb[1]) >= 0.55:
            target = (game, ma[0], mb[0])
            break

    if not target:
        msg = "Matchup not on ActionNetwork board"
        return _result(detail=msg, source="ActionNetwork"), _result(detail=msg, source="ActionNetwork")

    game, cid_a, cid_b = target
    bet = _an_bet_info(game)
    if cid_a not in bet and cid_b not in bet:
        return na, nb

    def score_side(cid):
        d = bet.get(cid)
        if not d or (d["tickets"] is None and d["money"] is None):
            return na
        tickets = d["tickets"] or 0
        money = d["money"] or 0
        # Sharp money = money% running ahead of ticket%. Public-heavy = fade.
        signal = (money - tickets)                          # -100..100
        score = max(0.0, min(100.0, 50 + signal * 1.5))
        lean = "sharp money" if signal > 3 else "public-heavy" if signal < -3 else "balanced"
        detail = f"tickets {tickets:.0f}% / money {money:.0f}% ({lean})"
        return _result(round(score, 1), True, detail, "ActionNetwork")

    return score_side(cid_a), score_side(cid_b)


# --------------------------------------------------------------------------- #
# Google News RSS — social sentiment from headline lexicon
# --------------------------------------------------------------------------- #
_POS = ("win", "wins", "won", "victory", "dominant", "dominates", "champion", "finishes",
        "knockout", "submits", "returns", "signs", "confident", "favorite", "impressive",
        "ready", "title", "comeback", "stops", "earns", "powers")
_NEG = ("loss", "loses", "lost", "defeat", "injury", "injured", "out", "withdraws", "pulled",
        "suspended", "fails", "misses weight", "controversy", "retire", "retirement",
        "setback", "arrested", "banned", "upset", "knocked out", "submitted")


def social_sentiment(name):
    try:
        r = requests.get(GNEWS, headers=UA, timeout=_TIMEOUT,
                         params={"q": f"{name} MMA", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        root = ET.fromstring(r.content)
    except Exception as e:
        return _result(detail=f"Google News error: {e}", source="Google News")

    titles = [(it.findtext("title") or "") for it in root.findall(".//item")][:30]
    titles = [t for t in titles if fuzzy(name, t) >= 0.3 or name.split()[-1].lower() in t.lower()]
    if not titles:
        return _result(detail="No recent headlines found", source="Google News")

    pos = neg = 0
    for t in titles:
        low = t.lower()
        pos += sum(1 for w in _POS if w in low)
        neg += sum(1 for w in _NEG if w in low)
    total = pos + neg
    if total == 0:
        return _result(50.0, True, f"{len(titles)} headlines, neutral tone", "Google News")

    ratio = pos / total
    score = max(0.0, min(100.0, 50 + (ratio - 0.5) * 100))
    return _result(round(score, 1), True,
                   f"{len(titles)} headlines, {pos}+/{neg}- tone", "Google News")
