"""Shared scoring metrics for betting evaluation.

Pure, dependency-free functions used by both the backtester (`backtest_engine`)
and the live calibration dashboard (`history_store`). Keeping them here means the
"how good are these probabilities / this betting record?" math has exactly one
implementation.

Glossary (plain English):
  - Brier score : average squared error of probabilities. 0 = perfect, 0.25 = a
                  coin flip, lower is better. The honest test of "are the
                  predicted percentages any good?"
  - Log loss    : like Brier but punishes confident-and-wrong far harder. Lower
                  is better.
  - Calibration : when the model says 70%, does that group actually win ~70%?
  - ROI         : profit divided by total amount staked. +0.05 = +5% on turnover.
  - Kelly       : the mathematically growth-optimal stake fraction for an edge.
"""
import math

# Probability buckets for calibration (shared with the live dashboard).
BUCKETS = [(0.50, 0.60, "50-60%"), (0.60, 0.70, "60-70%"),
           (0.70, 0.80, "70-80%"), (0.80, 1.0001, "80%+")]


def american_to_decimal_profit(odds):
    """Profit per 1 unit staked if the bet wins (the 'b' in Kelly).

    +150 -> 1.5 ; -200 -> 0.5.
    """
    odds = float(odds)
    return odds / 100.0 if odds > 0 else 100.0 / (-odds)


def kelly_fraction(prob, odds):
    """Growth-optimal stake as a fraction of bankroll. Clamped to >= 0."""
    b = american_to_decimal_profit(odds)
    if b <= 0:
        return 0.0
    return max(0.0, (b * prob - (1.0 - prob)) / b)


def brier(pairs):
    """Mean squared error of (probability, outcome) pairs. None if empty."""
    pairs = [(p, y) for p, y in pairs if p is not None]
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def log_loss(pairs, eps=1e-15):
    """Mean log loss of (probability, outcome) pairs. None if empty."""
    pairs = [(p, y) for p, y in pairs if p is not None]
    if not pairs:
        return None
    total = 0.0
    for p, y in pairs:
        p = min(1 - eps, max(eps, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(pairs)


def calibration_buckets(items):
    """Bucket items by predicted probability and compare predicted vs actual.

    `items`: iterable of {"prob": float, "settled": bool, "won": bool}.
      - predicted = mean predicted prob over ALL items in the bucket
      - actual    = wins / settled within the bucket (None if none settled)
    Returns a list of {label, n, settled, wins, predicted, actual}, one per bucket.
    """
    items = [it for it in items if isinstance(it.get("prob"), (int, float))]
    out = []
    for lo, hi, label in BUCKETS:
        sel = [it for it in items if lo <= it["prob"] < hi]
        settled = [it for it in sel if it.get("settled")]
        wins = sum(1 for it in settled if it.get("won"))
        predicted = (sum(it["prob"] for it in sel) / len(sel)) if sel else None
        actual = (wins / len(settled)) if settled else None
        out.append({
            "label": label, "n": len(sel), "settled": len(settled), "wins": wins,
            "predicted": round(predicted, 4) if predicted is not None else None,
            "actual": round(actual, 4) if actual is not None else None,
        })
    return out


def american_to_implied(odds):
    """Vig-inclusive implied probability from American odds."""
    odds = float(odds)
    return (-odds) / ((-odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def clv_metrics(bet_odds, bet_side_close, other_side_close=None):
    """Closing-line value of a bet.

    bet_odds         : the American odds you actually got
    bet_side_close   : closing American odds for the side you bet (required)
    other_side_close : closing American odds for the other side (optional — lets
                       us de-vig to a fair probability for the EV-vs-close metric)

    Returns {clv_pct, beat, close_odds, [close_prob, ev_vs_close]}.
      - clv_pct    : how much better your price was than the close (decimal basis).
                     +0.05 = you got 5% better odds than it closed. >0 = you "beat
                     the close", the gold-standard sign you're betting sharp.
      - ev_vs_close: expected value of your bet judged by the closing fair prob.
    """
    dec_bet = 1.0 + american_to_decimal_profit(bet_odds)
    dec_close = 1.0 + american_to_decimal_profit(bet_side_close)
    clv_pct = dec_bet / dec_close - 1.0
    out = {"clv_pct": round(clv_pct, 4), "beat": clv_pct > 0,
           "close_odds": round(float(bet_side_close), 1)}
    if other_side_close is not None:
        ia = american_to_implied(bet_side_close)
        ib = american_to_implied(other_side_close)
        total = ia + ib
        if total > 0:
            close_prob = ia / total
            out["close_prob"] = round(close_prob, 4)
            out["ev_vs_close"] = round(close_prob * dec_bet - 1.0, 4)
    return out


def clv_summary(items):
    """Aggregate captured CLV across bets.

    items: iterable of bet dicts carrying 'clv_pct' (and optional 'ev_vs_close').
    Returns {n, beat, beat_rate, avg_clv, avg_ev}.
    """
    cap = [b for b in items if isinstance(b.get("clv_pct"), (int, float))]
    n = len(cap)
    if n == 0:
        return {"n": 0, "beat": 0, "beat_rate": None, "avg_clv": None, "avg_ev": None}
    beat = sum(1 for b in cap if b["clv_pct"] > 0)
    avg_clv = sum(b["clv_pct"] for b in cap) / n
    evs = [b["ev_vs_close"] for b in cap if isinstance(b.get("ev_vs_close"), (int, float))]
    return {
        "n": n, "beat": beat, "beat_rate": round(beat / n, 4),
        "avg_clv": round(avg_clv, 4),
        "avg_ev": round(sum(evs) / len(evs), 4) if evs else None,
    }


def summarize_bets(bets):
    """Aggregate a list of settled simulated bets into headline numbers.

    Each bet: {"stake": float, "profit": float, "won": bool}.
    Returns {n, wins, win_rate, staked, profit, roi}.
    """
    n = len(bets)
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": None, "staked": 0.0,
                "profit": 0.0, "roi": None}
    wins = sum(1 for b in bets if b["won"])
    staked = sum(b["stake"] for b in bets)
    profit = sum(b["profit"] for b in bets)
    return {
        "n": n, "wins": wins, "win_rate": round(wins / n, 4),
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi": round(profit / staked, 4) if staked > 0 else None,
    }
