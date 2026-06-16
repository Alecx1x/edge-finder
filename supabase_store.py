"""Thin Supabase (PostgREST) client used as the primary History & Analytics store.

We talk to Supabase's auto-generated REST API with the project URL + anon key:
  GET    /rest/v1/<table>?<query>     -> select rows
  POST   /rest/v1/<table>             -> insert (Prefer: return=representation)
  PATCH  /rest/v1/<table>?<query>     -> update matching rows

The anon key can only do row CRUD (subject to RLS) — table creation is a one-time
SQL step the user runs from supabase_schema.sql. history_store.py layers the app's
data shapes on top of these generic calls and falls back to local JSON when this
store isn't configured or is unreachable.
"""
import config_manager as cfgmod

import requests

_TIMEOUT = 12

# Cached reachability: None = unknown (probe on next use), True/False = last result.
_active = None


class SupabaseError(Exception):
    pass


def _creds():
    return cfgmod.get_supabase()  # (url, anon_key), each "" if unset


def is_configured():
    url, key = _creds()
    return bool(url and key)


def reset_active():
    """Force the next is_active() call to re-probe (call after creds change)."""
    global _active
    _active = None


def _base(url):
    return url.rstrip("/") + "/rest/v1"


def _headers(key, prefer=None):
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def request(method, table, *, query="", body=None, prefer="return=representation"):
    """Low-level REST call. Returns parsed JSON (list/dict) or [] for empty bodies."""
    url, key = _creds()
    if not (url and key):
        raise SupabaseError("Supabase not configured.")
    full = f"{_base(url)}/{table}"
    if query:
        full = f"{full}?{query}"
    try:
        r = requests.request(method, full, headers=_headers(key, prefer),
                             json=body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise SupabaseError(f"Network error reaching Supabase: {e}")
    if r.status_code == 401 or r.status_code == 403:
        raise SupabaseError("Supabase rejected the anon key (check key / RLS policies).")
    if r.status_code == 404:
        raise SupabaseError(f"Table '{table}' not found — run supabase_schema.sql first.")
    if not r.ok:
        raise SupabaseError(f"Supabase {r.status_code}: {r.text[:200]}")
    if not r.text:
        return []
    try:
        return r.json()
    except ValueError:
        return []


def select(table, query="order=id.asc"):
    return request("GET", table, query=query, prefer=None)


def insert(table, row):
    rows = request("POST", table, body=row)
    return rows[0] if isinstance(rows, list) and rows else rows


def update(table, query, patch):
    return request("PATCH", table, query=query, body=patch)


def test_connection():
    """Probe each expected table. Returns (ok, message). Used on key save."""
    if not is_configured():
        return False, "Enter both a Supabase URL and anon key."
    missing = []
    for t in ("odds_history", "bets_log", "matchup_history"):
        try:
            request("GET", t, query="limit=1", prefer=None)
        except SupabaseError as e:
            msg = str(e)
            if "not found" in msg:
                missing.append(t)
            else:
                return False, msg
    if missing:
        return False, ("Connected, but missing table(s): " + ", ".join(missing) +
                       ". Run supabase_schema.sql in the SQL editor.")
    return True, "Connected to Supabase — all tables present."


def is_active():
    """True when configured AND reachable with tables present (cached)."""
    global _active
    if not is_configured():
        _active = False
        return False
    if _active is None:
        ok, _ = test_connection()
        _active = ok
    return _active


def mark_down():
    """Drop to fallback for the rest of the session after a failed op."""
    global _active
    _active = False
