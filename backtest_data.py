"""Historical UFC dataset loader for backtesting.

Loads a lookahead-clean public dataset (the shortlikeafox / mdabbert "Ultimate
UFC Dataset", ``ufc-master.csv``) and emits one canonical record per past fight
in the EXACT shape ``scoring_engine.build_report()`` consumes — so historical
fights replay through the unchanged live engine with no special-casing.

Two point-in-time signals are populated; every other variable is simply left out
of the per-fight ``data`` dict, so the engine treats it as unavailable (its
normal behaviour) and no lookahead leaks in:

  - ``recent_form`` : from the dataset's *pre-fight* win/lose-streak + record
                      columns (the dataset is built so each row's stats are the
                      fighter's record going INTO that bout).
  - ``elo``         : a chronological Elo rating we compute ourselves here by
                      replaying results in date order. Each fight reads both
                      fighters' ratings BEFORE updating them, so by construction
                      it can only ever use information from earlier fights.

Side mapping: ``a`` = Red corner (``R_*`` columns), ``b`` = Blue corner (``B_*``).
"""
import csv
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = APP_DIR / "data" / "ufc-master.csv"

# Elo parameters. 1500 is the conventional starting rating; K controls how fast
# ratings move per fight (40 is a common choice for sparse, high-variance sports).
ELO_START = 1500.0
ELO_K = 40.0

REQUIRED_COLUMNS = {"R_fighter", "B_fighter", "R_odds", "B_odds", "date", "Winner"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _valid_american(o):
    """American moneylines are always <= -100 or >= +100."""
    return o is not None and (o <= -100 or o >= 100)


def _expected(elo_a, elo_b):
    """Elo win probability for side A (0..1). Sums to 1 with side B."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def _form_score(win_streak, lose_streak, wins, losses):
    """0-100 'recent form' score: career win% nudged by the current streak."""
    total = wins + losses
    base = (wins / total * 100.0) if total > 0 else 50.0
    base += min(15.0, win_streak * 4.0) - min(15.0, lose_streak * 4.0)
    return max(0.0, min(100.0, base))


def _result(score, detail, source="dataset"):
    return {"score": round(score, 1), "available": True, "detail": detail, "source": source}


def _int(v):
    n = _num(v)
    return int(n) if n is not None else 0


def load_fights(csv_path=None):
    """Return a chronologically-ordered list of canonical fight records.

    Each record:
        {
          "date": "YYYY-MM-DD", "sport": "MMA", "league": <weight class>,
          "a": {"name": str, "odds": float}, "b": {"name": str, "odds": float},
          "winner": "a" | "b",
          "data": { "elo": {...}, "recent_form": {...} },   # engine-shaped
        }

    Only clean, bettable rows (decisive Red/Blue winner + valid odds on both
    sides) become records. Draws / No-Contests and rows with missing odds are
    skipped from the output, but a decisive result still updates the Elo ladder
    so ratings stay accurate.
    """
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {path}. Download 'ufc-master.csv' from the "
            f"Ultimate UFC Dataset (Kaggle: mdabbert/ultimate-ufc-dataset, or the "
            f"shortlikeafox/ultimate_ufc_dataset GitHub mirror) into {path.parent}."
        )

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{path} is empty.")

    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(
            f"{path} is missing expected columns: {sorted(missing)}. "
            f"This loader targets the Ultimate UFC Dataset schema."
        )

    # The dataset ships newest-first; replay oldest-first so Elo accumulates.
    rows.sort(key=lambda x: x.get("date", ""))

    elo = {}
    out = []
    for x in rows:
        a_name = (x.get("R_fighter") or "").strip()
        b_name = (x.get("B_fighter") or "").strip()
        if not a_name or not b_name:
            continue

        ea = elo.get(a_name, ELO_START)
        eb = elo.get(b_name, ELO_START)
        exp_a = _expected(ea, eb)              # point-in-time: read BEFORE update

        winner = x.get("Winner")
        oa, ob = _num(x.get("R_odds")), _num(x.get("B_odds"))

        if winner in ("Red", "Blue") and _valid_american(oa) and _valid_american(ob):
            form_a = _form_score(_int(x.get("R_current_win_streak")),
                                 _int(x.get("R_current_lose_streak")),
                                 _int(x.get("R_wins")), _int(x.get("R_losses")))
            form_b = _form_score(_int(x.get("B_current_win_streak")),
                                 _int(x.get("B_current_lose_streak")),
                                 _int(x.get("B_wins")), _int(x.get("B_losses")))
            out.append({
                "date": x.get("date"),
                "sport": "MMA",
                "league": x.get("weight_class", "") or "MMA",
                "a": {"name": a_name, "odds": round(oa, 1)},
                "b": {"name": b_name, "odds": round(ob, 1)},
                "winner": "a" if winner == "Red" else "b",
                "home_team": None,
                "away_team": None,
                "data": {
                    "elo": {
                        "a": _result(exp_a * 100.0, f"Elo {ea:.0f} (exp {exp_a*100:.0f}%)"),
                        "b": _result((1 - exp_a) * 100.0, f"Elo {eb:.0f} (exp {(1-exp_a)*100:.0f}%)"),
                    },
                    "recent_form": {
                        "a": _result(form_a, f"W{_int(x.get('R_current_win_streak'))}/"
                                             f"L{_int(x.get('R_current_lose_streak'))}, "
                                             f"{_int(x.get('R_wins'))}-{_int(x.get('R_losses'))}"),
                        "b": _result(form_b, f"W{_int(x.get('B_current_win_streak'))}/"
                                             f"L{_int(x.get('B_current_lose_streak'))}, "
                                             f"{_int(x.get('B_wins'))}-{_int(x.get('B_losses'))}"),
                    },
                },
            })

        # Update the Elo ladder for any decisive/drawn result (incl. rows we
        # didn't emit, e.g. missing odds) so ratings reflect full fight history.
        s_a = {"Red": 1.0, "Blue": 0.0, "Draw": 0.5}.get(winner)
        if s_a is not None:
            elo[a_name] = ea + ELO_K * (s_a - exp_a)
            elo[b_name] = eb + ELO_K * (exp_a - s_a)   # mirror of A's update

    return out


if __name__ == "__main__":
    fights = load_fights()
    print(f"Loaded {len(fights)} clean fights")
    print(f"Date range: {fights[0]['date']} -> {fights[-1]['date']}")
    print("First emitted fight:")
    import json
    print(json.dumps(fights[0], indent=2))
