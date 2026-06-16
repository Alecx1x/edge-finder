"""Config + secrets management.

Owns config.json (per-variable weights + odds settings) and .env (Odds API key).
Also the single source of truth for the variable registry and supported sports,
so every other module agrees on keys/labels.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv, set_key

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
ENV_PATH = APP_DIR / ".env"

# Variable registry. `sports=None` -> applies to every sport, otherwise a set.
# `core=True` are the shared cross-sport variables; `core=False` are sport-specific
# advanced stats shown in a collapsible per-sport panel in the UI. Every variable
# (core or not) gets its own 0.0-2.0 multiplier and feeds the same scoring engine.
VARIABLES = [
    # --- core (all sports) --------------------------------------------------
    {"key": "recent_form",      "label": "Recent Form & Streaks",     "sports": None, "core": True},
    {"key": "injuries",         "label": "Injury & Health",           "sports": None, "core": True},
    {"key": "head_to_head",     "label": "Head-to-Head History",      "sports": None, "core": True},
    {"key": "travel_fatigue",   "label": "Travel / Schedule Fatigue", "sports": None, "core": True},
    {"key": "weather",          "label": "Weather Conditions",        "sports": {"Soccer", "Tennis"}, "core": True},
    {"key": "line_movement",    "label": "Public % vs Sharp Money",   "sports": None, "core": True},
    {"key": "social_sentiment", "label": "Social Sentiment / Hype",   "sports": None, "core": True},

    # --- MMA advanced (ufcstats.com career stats) ---------------------------
    # Elo is a point-in-time strength rating computed by replaying past results
    # in date order (lookahead-safe). Populated by the backtester today; the live
    # path leaves it unavailable until a live rating source is wired.
    {"key": "elo",              "label": "Elo Rating (point-in-time)", "sports": {"MMA"}, "core": False},
    {"key": "mma_sig_strikes",  "label": "Sig. Strikes Landed / min",  "sports": {"MMA"}, "core": False},
    {"key": "mma_strike_acc",   "label": "Strike Accuracy %",          "sports": {"MMA"}, "core": False},
    {"key": "mma_td_attempts",  "label": "Takedown Attempts / fight",  "sports": {"MMA"}, "core": False},
    {"key": "mma_td_acc",       "label": "Takedown Accuracy %",        "sports": {"MMA"}, "core": False},
    {"key": "mma_td_def",       "label": "Takedown Defense %",         "sports": {"MMA"}, "core": False},
    {"key": "mma_sub_attempts", "label": "Submission Attempts / fight","sports": {"MMA"}, "core": False},

    # --- Basketball advanced (basketball-reference.com) ---------------------
    {"key": "nba_ats",          "label": "Last 10 ATS Record",         "sports": {"Basketball"}, "core": False},
    {"key": "nba_rest",         "label": "Days Rest Since Last Game",   "sports": {"Basketball"}, "core": False},
    {"key": "nba_pace",         "label": "Pace Differential vs Opp.",   "sports": {"Basketball"}, "core": False},

    # --- Soccer advanced (fbref.com) ----------------------------------------
    {"key": "soccer_xg",        "label": "xG For/Against (last 5)",     "sports": {"Soccer"}, "core": False},
    {"key": "soccer_press",     "label": "Press Intensity Differential","sports": {"Soccer"}, "core": False},

    # --- Tennis advanced (Jeff Sackmann tennis_atp CSVs) --------------------
    {"key": "tennis_surface",   "label": "Surface Win % (this surface)","sports": {"Tennis"}, "core": False},
    {"key": "tennis_aces",      "label": "Aces / Match Avg",            "sports": {"Tennis"}, "core": False},
    {"key": "tennis_bp",        "label": "Break Point Conversion %",    "sports": {"Tennis"}, "core": False},
]

SPORTS = ["MMA", "Basketball", "Soccer", "Tennis"]

WEIGHT_MIN, WEIGHT_MAX = 0.0, 2.0

DEFAULT_CONFIG = {
    "weights": {v["key"]: 1.0 for v in VARIABLES},
    "odds": {"regions": "us", "markets": "h2h", "odds_format": "american"},
    "bankroll": 1000.0,   # used by the Kelly Criterion calculator
    "my_books": [],       # Odds API bookmaker keys the user actually bets at ([] = all)
    "whale_wallets": [],  # [{address, chain, label}] watched for the whale tracker
}


def variables_for_sport(sport):
    """Variables that apply to a given sport, in registry order."""
    return [v for v in VARIABLES if v["sports"] is None or sport in v["sports"]]


def load_config():
    """Load config.json, merging in any missing defaults, and persist the result."""
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy of defaults
    if isinstance(data.get("odds"), dict):
        cfg["odds"].update(data["odds"])
    if isinstance(data.get("weights"), dict):
        for v in VARIABLES:
            if v["key"] in data["weights"]:
                w = clamp_weight(data["weights"][v["key"]])
                if w is not None:
                    cfg["weights"][v["key"]] = w
    if "bankroll" in data:
        br = clamp_bankroll(data["bankroll"])
        if br is not None:
            cfg["bankroll"] = br
    if isinstance(data.get("my_books"), list):
        cfg["my_books"] = [str(k) for k in data["my_books"]]
    if isinstance(data.get("whale_wallets"), list):
        cfg["whale_wallets"] = [w for w in data["whale_wallets"] if isinstance(w, dict) and w.get("address")]

    save_config(cfg)
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def clamp_weight(value):
    """Coerce to a float within [WEIGHT_MIN, WEIGHT_MAX]; None if not numeric."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return max(WEIGHT_MIN, min(WEIGHT_MAX, x))


def set_weight(cfg, key, value):
    val = clamp_weight(value)
    if val is None or key not in cfg["weights"]:
        return False
    cfg["weights"][key] = val
    save_config(cfg)
    return True


def clamp_bankroll(value):
    """Coerce to a non-negative float (max $1e9); None if not numeric."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1_000_000_000.0, x))


def set_bankroll(cfg, value):
    val = clamp_bankroll(value)
    if val is None:
        return False
    cfg["bankroll"] = val
    save_config(cfg)
    return True


def get_my_books(cfg):
    """List of Odds API bookmaker keys the user bets at ([] = no filter / all)."""
    books = cfg.get("my_books", [])
    return [str(k) for k in books] if isinstance(books, list) else []


def set_my_books(cfg, keys):
    """Persist the user's bookmaker selection. Returns False if not a list."""
    if not isinstance(keys, list):
        return False
    cfg["my_books"] = [str(k).strip() for k in keys if str(k).strip()]
    save_config(cfg)
    return True


def get_api_key():
    load_dotenv(ENV_PATH, override=True)
    return os.getenv("ODDS_API_KEY", "").strip()


def save_api_key(key):
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    set_key(str(ENV_PATH), "ODDS_API_KEY", key.strip())


def get_whale_wallets(cfg):
    """Watched wallets [{address, chain, label}] for the whale tracker."""
    wl = cfg.get("whale_wallets", [])
    return wl if isinstance(wl, list) else []


def set_whale_wallets(cfg, wallets):
    """Persist the whale watchlist. Each item must have an address + chain."""
    if not isinstance(wallets, list):
        return False
    clean = []
    for w in wallets:
        if isinstance(w, dict) and str(w.get("address", "")).strip():
            clean.append({"address": str(w["address"]).strip(),
                          "chain": str(w.get("chain", "ethereum")).strip(),
                          "label": str(w.get("label", "")).strip()})
    cfg["whale_wallets"] = clean
    save_config(cfg)
    return True


def get_chain_key(name):
    """Free explorer API key for whale tracking: 'etherscan' or 'helius'."""
    load_dotenv(ENV_PATH, override=True)
    env = "ETHERSCAN_API_KEY" if name == "etherscan" else "HELIUS_API_KEY"
    return os.getenv(env, "").strip()


def save_chain_key(name, key):
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    env = "ETHERSCAN_API_KEY" if name == "etherscan" else "HELIUS_API_KEY"
    set_key(str(ENV_PATH), env, (key or "").strip())


def get_supabase():
    """(url, anon_key) for the Supabase History & Analytics store; '' if unset."""
    load_dotenv(ENV_PATH, override=True)
    return (os.getenv("SUPABASE_URL", "").strip(),
            os.getenv("SUPABASE_ANON_KEY", "").strip())


def save_supabase(url, key):
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    set_key(str(ENV_PATH), "SUPABASE_URL", (url or "").strip())
    set_key(str(ENV_PATH), "SUPABASE_ANON_KEY", (key or "").strip())
