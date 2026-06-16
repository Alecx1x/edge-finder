"""History & Analytics storage with a Supabase primary + local-JSON fallback.

Public API (record_analysis / odds_history / matchup_history / list_bets /
add_bet / set_bet_result / calibration) returns the SAME shapes regardless of
backend, so main.py and the frontend never change:

  * When Supabase is configured AND reachable (tables present) -> rows live in
    Supabase via supabase_store (PostgREST). Column names map to the app's shapes.
  * Otherwise -> the original local JSON files (odds_history.json /
    matchup_history.json / bets_log.json), so everything keeps working offline.

A failed Supabase op drops the session to JSON (mark_down) rather than erroring.
"""
import datetime
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

from mma_sources import fold

import metrics
import supabase_store

APP_DIR = Path(__file__).resolve().parent
ODDS_PATH = APP_DIR / "odds_history.json"
MATCHUP_PATH = APP_DIR / "matchup_history.json"
BETS_PATH = APP_DIR / "bets_log.json"

_lock = threading.Lock()

MIN_BETS_FOR_CALIBRATION = 10  # calibration bucket edges live in metrics.BUCKETS


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def matchup_key(sport, a, b):
    names = sorted([fold(a or "").lower().strip(), fold(b or "").lower().strip()])
    return f"{sport}|{names[0]}|{names[1]}"


def _tickets_pct(detail):
    m = re.search(r"tickets\s+(\d+(?:\.\d+)?)\s*%", detail or "", re.I)
    return float(m.group(1)) if m else None


def _public_pcts(report):
    for row in report.get("rows", []):
        if row.get("key") == "line_movement" and row.get("available"):
            return _tickets_pct(row.get("detail_a", "")), _tickets_pct(row.get("detail_b", ""))
    return None, None


def _which():
    """Return the active backend module-name: 'supabase' or 'json'."""
    try:
        return "supabase" if supabase_store.is_active() else "json"
    except Exception:
        return "json"


# =========================================================================== #
# Supabase backend
# =========================================================================== #
def _sb_snap(r):
    return {"ts": r.get("timestamp"), "odds_a": r.get("odds_a"), "odds_b": r.get("odds_b"),
            "implied_a": r.get("implied_prob_a"), "implied_b": r.get("implied_prob_b"),
            "public_a": r.get("public_a"), "public_b": r.get("public_b")}


def _sb_point(r):
    return {"ts": r.get("timestamp"), "edge": r.get("edge"),
            "edge_a": r.get("edge_a"), "side": r.get("side")}


def _sb_bet(r):
    return {"id": r.get("id"), "sport": r.get("sport"),
            "name_a": r.get("fighter_a"), "name_b": r.get("fighter_b"),
            "bet_side": r.get("bet_side"), "bet_name": r.get("bet_name"),
            "bet_odds": r.get("bet_odds"), "odds_a": r.get("odds_a"), "odds_b": r.get("odds_b"),
            "edge": r.get("edge"), "model_prob": r.get("model_prob"), "stake": r.get("stake"),
            "result": r.get("result"), "logged_at": r.get("timestamp"),
            "settled_at": r.get("settled_at"),
            "close_odds": r.get("close_odds"), "other_close_odds": r.get("other_close_odds"),
            "close_prob": r.get("close_prob"), "clv_pct": r.get("clv_pct"),
            "ev_vs_close": r.get("ev_vs_close"), "beat": r.get("beat"),
            "captured_at": r.get("captured_at")}


def _match_query(sport, a, b, order="timestamp.asc"):
    """PostgREST filter for this matchup, order-independent & case-insensitive."""
    def q(s):
        return quote(s or "", safe="")
    orc = (f"or=(and(fighter_a.ilike.{q(a)},fighter_b.ilike.{q(b)}),"
           f"and(fighter_a.ilike.{q(b)},fighter_b.ilike.{q(a)}))")
    return f"sport=eq.{q(sport)}&{orc}&order={order}"


def _sb_odds_history(sport, a, b):
    rows = supabase_store.select("odds_history", _match_query(sport, a, b))
    if not rows:
        return None
    return {"sport": sport, "a": a, "b": b, "snapshots": [_sb_snap(r) for r in rows]}


def _sb_matchup_history(sport, a, b):
    rows = supabase_store.select("matchup_history", _match_query(sport, a, b))
    if not rows:
        return None
    return {"sport": sport, "a": a, "b": b, "points": [_sb_point(r) for r in rows]}


def _sb_record(report):
    m, sport = report.get("matchup", {}), report.get("sport", "")
    a, b = m.get("a", {}), m.get("b", {})
    na, nb = a.get("name", ""), b.get("name", "")
    ts = _now()
    pub_a, pub_b = _public_pcts(report)
    rec = report.get("recommendation", {})

    supabase_store.insert("odds_history", {
        "fighter_a": na, "fighter_b": nb, "sport": sport,
        "odds_a": a.get("odds"), "odds_b": b.get("odds"),
        "implied_prob_a": round(report["implied"]["a"], 4),
        "implied_prob_b": round(report["implied"]["b"], 4),
        "public_a": pub_a, "public_b": pub_b, "timestamp": ts})
    supabase_store.insert("matchup_history", {
        "fighter_a": na, "fighter_b": nb, "sport": sport,
        "edge": round(rec.get("edge", 0.0), 4), "edge_a": round(report["edge"]["a"], 4),
        "side": rec.get("side"), "timestamp": ts})

    odds_entry = _sb_odds_history(sport, na, nb) or {"sport": sport, "a": na, "b": nb, "snapshots": []}
    edge_entry = _sb_matchup_history(sport, na, nb) or {"sport": sport, "a": na, "b": nb, "points": []}
    return matchup_key(sport, na, nb), odds_entry, edge_entry


def _sb_list_bets():
    return [_sb_bet(r) for r in supabase_store.select("bets_log", "order=id.asc")]


def _sb_add_bet(bet):
    created = supabase_store.insert("bets_log", {
        "fighter_a": bet["name_a"], "fighter_b": bet["name_b"], "sport": bet["sport"],
        "odds_a": bet.get("odds_a"), "odds_b": bet.get("odds_b"),
        "bet_side": bet["bet_side"], "bet_name": bet["bet_name"], "bet_odds": bet["bet_odds"],
        "edge": bet["edge"], "model_prob": bet["model_prob"], "stake": bet.get("stake")})
    return _sb_bet(created)


def _sb_set_result(bet_id, result):
    rows = supabase_store.update("bets_log", f"id=eq.{int(bet_id)}",
                                 {"result": result, "settled_at": _now()})
    return _sb_bet(rows[0]) if rows else None


def _sb_set_close(bet_id, fields):
    rows = supabase_store.update("bets_log", f"id=eq.{int(bet_id)}", fields)
    return _sb_bet(rows[0]) if rows else None


# =========================================================================== #
# JSON backend (original local storage)
# =========================================================================== #
def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, data):
    try:
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _json_record(report):
    m, sport = report.get("matchup", {}), report.get("sport", "")
    a, b = m.get("a", {}), m.get("b", {})
    na, nb = a.get("name", ""), b.get("name", "")
    key = matchup_key(sport, na, nb)
    ts = _now()
    pub_a, pub_b = _public_pcts(report)
    rec = report.get("recommendation", {})
    with _lock:
        oh = _load(ODDS_PATH, {})
        oe = oh.setdefault(key, {"sport": sport, "a": na, "b": nb, "snapshots": []})
        oe.update({"sport": sport, "a": na, "b": nb})
        oe["snapshots"].append({
            "ts": ts, "odds_a": a.get("odds"), "odds_b": b.get("odds"),
            "implied_a": round(report["implied"]["a"], 4),
            "implied_b": round(report["implied"]["b"], 4),
            "model_a": round(report["model"]["a"], 4),
            "public_a": pub_a, "public_b": pub_b})
        _save(ODDS_PATH, oh)

        mh = _load(MATCHUP_PATH, {})
        me = mh.setdefault(key, {"sport": sport, "a": na, "b": nb, "points": []})
        me.update({"sport": sport, "a": na, "b": nb})
        me["points"].append({"ts": ts, "edge": round(rec.get("edge", 0.0), 4),
                             "edge_a": round(report["edge"]["a"], 4), "side": rec.get("side")})
        _save(MATCHUP_PATH, mh)
    return key, oh[key], mh[key]


def _json_odds_history(sport, a, b):
    return _load(ODDS_PATH, {}).get(matchup_key(sport, a, b))


def _json_matchup_history(sport, a, b):
    return _load(MATCHUP_PATH, {}).get(matchup_key(sport, a, b))


def _json_list_bets():
    bets = _load(BETS_PATH, [])
    return bets if isinstance(bets, list) else []


def _json_add_bet(bet):
    with _lock:
        bets = _json_list_bets()
        bet["id"] = (max((b.get("id", 0) for b in bets), default=0) + 1)
        bet["logged_at"] = _now()
        bet["result"] = None
        bet["settled_at"] = None
        bets.append(bet)
        _save(BETS_PATH, bets)
        return bet


def _json_set_result(bet_id, result):
    with _lock:
        bets = _json_list_bets()
        for bt in bets:
            if bt.get("id") == bet_id:
                bt["result"] = result
                bt["settled_at"] = _now()
                _save(BETS_PATH, bets)
                return bt
    return None


def _json_set_close(bet_id, fields):
    with _lock:
        bets = _json_list_bets()
        for bt in bets:
            if bt.get("id") == bet_id:
                bt.update(fields)
                _save(BETS_PATH, bets)
                return bt
    return None


# =========================================================================== #
# Public API — dispatches to the active backend, degrades to JSON on error
# =========================================================================== #
def record_analysis(report):
    if _which() == "supabase":
        try:
            return _sb_record(report)
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_record(report)


def odds_history(sport, a, b):
    if _which() == "supabase":
        try:
            return _sb_odds_history(sport, a, b)
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_odds_history(sport, a, b)


def matchup_history(sport, a, b):
    if _which() == "supabase":
        try:
            return _sb_matchup_history(sport, a, b)
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_matchup_history(sport, a, b)


def list_bets():
    if _which() == "supabase":
        try:
            return _sb_list_bets()
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_list_bets()


def add_bet(bet):
    if _which() == "supabase":
        try:
            return _sb_add_bet(dict(bet))
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_add_bet(dict(bet))


def set_bet_result(bet_id, result):
    result = (result or "").lower()
    if result not in ("win", "loss", "push"):
        return None
    if _which() == "supabase":
        try:
            return _sb_set_result(bet_id, result)
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_set_result(bet_id, result)


MIN_BETS_FOR_CLV = 10  # captured bets needed before a beat-the-close verdict


def set_bet_close(bet_id, bet_side_close, other_side_close=None):
    """Record the closing line for a bet and compute its CLV.

    bet_side_close / other_side_close are American odds at close. Reads the bet's
    own odds to compute how much you beat (or lost to) the close.
    """
    bet = next((b for b in list_bets() if b.get("id") == bet_id), None)
    if not bet or bet.get("bet_odds") is None:
        return None
    cm = metrics.clv_metrics(bet["bet_odds"], bet_side_close, other_side_close)
    fields = {
        "close_odds": cm["close_odds"],
        "other_close_odds": round(float(other_side_close), 1) if other_side_close is not None else None,
        "close_prob": cm.get("close_prob"),
        "clv_pct": cm["clv_pct"],
        "ev_vs_close": cm.get("ev_vs_close"),
        "beat": cm["beat"],
        "captured_at": _now(),
    }
    if _which() == "supabase":
        try:
            return _sb_set_close(bet_id, fields)
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_set_close(bet_id, fields)


def clv():
    """Closing-line-value scorecard over all bets that have a captured close."""
    summary = metrics.clv_summary(list_bets())
    summary["min_required"] = MIN_BETS_FOR_CLV
    summary["enough"] = summary["n"] >= MIN_BETS_FOR_CLV
    return summary


def calibration():
    """Backend-agnostic: buckets whatever list_bets() returns.

    Bucketing math lives in metrics.calibration_buckets so the backtester and the
    live dashboard score calibration identically.
    """
    bets = list_bets()
    total = len(bets)
    items = [{"prob": b.get("model_prob"),
              "settled": b.get("result") in ("win", "loss"),
              "won": b.get("result") == "win"} for b in bets]
    return {"total": total, "min_required": MIN_BETS_FOR_CALIBRATION,
            "enough": total >= MIN_BETS_FOR_CALIBRATION,
            "buckets": metrics.calibration_buckets(items)}


def storage_status():
    """For the UI: which backend is in use and why."""
    configured = supabase_store.is_configured()
    active = configured and supabase_store.is_active()
    return {
        "configured": configured,
        "active": bool(active),
        "mode": "supabase" if active else "json",
    }
