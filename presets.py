"""Weight presets for the Variable Weights panel.

Two kinds of preset:
  * Built-in defaults (is_default=True) — defined here in code so they are always
    available and can never be deleted. They are also seeded into the Supabase
    `presets` table (idempotently) so the table reflects them, but the API always
    serves the code copy to guarantee availability + immutability.
  * Custom presets (is_default=False) — saved by the user. Stored in Supabase when
    it's the active backend, else in a local presets.json file (same fallback
    pattern as the rest of History & Analytics).

The preset values below use the app's *internal* variable keys (see
config_manager.VARIABLES), translated from the human-facing names in the spec
(e.g. h2h_history->head_to_head, takedown_defense->mma_td_def,
striking_accuracy->mma_strike_acc, injury_health->injuries,
public_vs_sharp->line_movement, rest_days->nba_rest,
surface_win_pct->tennis_surface, xg_differential->soccer_xg).
"""
import datetime
import json
from pathlib import Path

import config_manager as cfgmod
import supabase_store

PRESETS_PATH = Path(__file__).resolve().parent / "presets.json"

_VALID_KEYS = {v["key"] for v in cfgmod.VARIABLES}

# --- built-in defaults (cannot be deleted) ---------------------------------- #
DEFAULT_PRESETS = [
    {"name": "MMA — Grappling Matters", "sport": "MMA", "weights": {
        "recent_form": 1.4, "head_to_head": 1.6, "mma_td_def": 1.8,
        "mma_strike_acc": 1.5, "injuries": 1.7, "travel_fatigue": 0.8,
        "social_sentiment": 0.4}},
    {"name": "MMA — Strikers Edge", "sport": "MMA", "weights": {
        "recent_form": 1.6, "mma_strike_acc": 1.9, "mma_td_def": 1.2,
        "head_to_head": 1.4, "injuries": 1.5, "social_sentiment": 0.3}},
    {"name": "Basketball — Sharp Money", "sport": "Basketball", "weights": {
        "line_movement": 1.9, "travel_fatigue": 1.7, "recent_form": 1.4,
        "head_to_head": 0.9, "injuries": 1.6, "social_sentiment": 0.3}},
    {"name": "Basketball — Fatigue Finder", "sport": "Basketball", "weights": {
        "travel_fatigue": 2.0, "nba_rest": 1.9, "recent_form": 1.3,
        "injuries": 1.5, "line_movement": 1.2, "social_sentiment": 0.2}},
    {"name": "Tennis — Surface Specialist", "sport": "Tennis", "weights": {
        "tennis_surface": 2.0, "recent_form": 1.5, "head_to_head": 1.6,
        "travel_fatigue": 1.3, "injuries": 1.4, "social_sentiment": 0.3}},
    {"name": "Soccer — Value Hunter", "sport": "Soccer", "weights": {
        "soccer_xg": 1.8, "recent_form": 1.5, "head_to_head": 1.3,
        "travel_fatigue": 1.4, "line_movement": 1.7, "weather": 1.2,
        "social_sentiment": 0.3}},
]


def _clean_weights(weights):
    """Keep only known variable keys, each clamped to [0, 2]."""
    out = {}
    for k, v in (weights or {}).items():
        if k in _VALID_KEYS:
            c = cfgmod.clamp_weight(v)
            if c is not None:
                out[k] = c
    return out


def _use_sb():
    try:
        return supabase_store.is_active()
    except Exception:
        return False


def _default_payload():
    return [
        {"id": f"default:{i}", "name": p["name"], "sport": p["sport"],
         "weights": p["weights"], "is_default": True, "created_at": None}
        for i, p in enumerate(DEFAULT_PRESETS)
    ]


# --- custom store: Supabase or JSON ----------------------------------------- #
def _sb_to_api(r):
    return {"id": r.get("id"), "name": r.get("name"), "sport": r.get("sport"),
            "weights": r.get("weights_json") or {}, "is_default": bool(r.get("is_default")),
            "created_at": r.get("created_at")}


def _json_load():
    try:
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _json_save(rows):
    try:
        PRESETS_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    except OSError:
        pass


def _custom_list():
    if _use_sb():
        try:
            rows = supabase_store.select("presets", "is_default=eq.false&order=id.asc")
            return [_sb_to_api(r) for r in rows]
        except supabase_store.SupabaseError:
            supabase_store.mark_down()
    return _json_load()


def list_presets():
    """Built-in defaults first, then custom presets from the active backend."""
    return _default_payload() + _custom_list()


def add_preset(name, sport, weights):
    name = (name or "").strip()
    if not name:
        return None, "A preset name is required."
    sport = sport if sport in cfgmod.SPORTS else None
    cleaned = _clean_weights(weights)
    if not cleaned:
        return None, "No valid weights to save."

    if _use_sb():
        try:
            row = supabase_store.insert("presets", {
                "name": name, "sport": sport, "weights_json": cleaned, "is_default": False})
            return _sb_to_api(row), None
        except supabase_store.SupabaseError:
            supabase_store.mark_down()

    rows = _json_load()
    new = {"id": max((r.get("id", 0) for r in rows), default=0) + 1,
           "name": name, "sport": sport, "weights": cleaned, "is_default": False,
           "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    rows.append(new)
    _json_save(rows)
    return new, None


def delete_preset(pid):
    """Delete a custom preset by id. Defaults (default:* ids) are never deletable."""
    if isinstance(pid, str) and pid.startswith("default:"):
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False

    if _use_sb():
        try:
            supabase_store.request("DELETE", "presets",
                                   query=f"id=eq.{pid_int}&is_default=eq.false")
            return True
        except supabase_store.SupabaseError:
            supabase_store.mark_down()

    rows = _json_load()
    kept = [r for r in rows if not (r.get("id") == pid_int and not r.get("is_default"))]
    if len(kept) == len(rows):
        return False
    _json_save(kept)
    return True


def seed_defaults():
    """Idempotently insert the built-in defaults into Supabase (best-effort).

    Serving still uses the code copy; this just makes the table reflect them.
    """
    if not _use_sb():
        return
    try:
        existing = supabase_store.select("presets", "is_default=eq.true&select=name")
        names = {r.get("name") for r in existing}
        for p in DEFAULT_PRESETS:
            if p["name"] not in names:
                supabase_store.insert("presets", {
                    "name": p["name"], "sport": p["sport"],
                    "weights_json": p["weights"], "is_default": True})
    except supabase_store.SupabaseError:
        pass
