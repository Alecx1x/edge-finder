"""Pick'em / DFS +EV math (DraftKings Pick6, Betr Picks, PrizePicks-style).

These apps don't give per-bet odds — you pick player props OVER/UNDER and combine
them into an entry that pays a FIXED multiplier if they all hit (a "power play").
The edge is that their projection lines are often softer than the sharp player-prop
market. So for each leg we work out its TRUE hit probability from a sharp book's
two-way prop odds, then the whole entry is:

    win probability = product of each leg's hit probability   (all must hit)
    EV per $1       = win_prob × payout_multiplier − 1

Beats the app whenever you stack legs that are each individually +EV vs the sharp
line. (Flex/insured entries with partial payouts are a future addition.)
"""
import metrics


def leg_prob(side, over_odds, under_odds):
    """True hit probability of the chosen side, de-vigged from a sharp book's
    two-way prop odds AT THE SAME LINE as the pick'em app.

    side: 'over' or 'under'; odds are American (e.g. -115 / -105).
    """
    io = metrics.american_to_implied(over_odds)
    iu = metrics.american_to_implied(under_odds)
    total = io + iu
    if total <= 0:
        return None
    fair_over = io / total
    return fair_over if side == "over" else (1.0 - fair_over)


def entry_ev(leg_probs, multiplier):
    """Power-play entry (all legs must hit). Returns win_prob, ev, breakeven mult."""
    probs = [p for p in leg_probs if isinstance(p, (int, float))]
    if not probs or len(probs) != len(leg_probs):
        return None
    try:
        mult = float(multiplier)
    except (TypeError, ValueError):
        return None
    win_prob = 1.0
    for p in probs:
        win_prob *= p
    return {
        "n_legs": len(probs),
        "win_prob": round(win_prob, 4),
        "multiplier": mult,
        "ev": round(win_prob * mult - 1.0, 4),         # per $1 staked
        "breakeven_multiplier": round(1.0 / win_prob, 3) if win_prob > 0 else None,
    }


def evaluate(legs, multiplier):
    """legs: [{side, over_odds, under_odds, label?}]. Computes each leg's prob and
    the overall entry EV. Returns {legs:[...with prob...], entry:{...}} or None."""
    out_legs = []
    for lg in legs:
        p = leg_prob(lg.get("side", "over"), lg.get("over_odds"), lg.get("under_odds"))
        out_legs.append({**lg, "prob": round(p, 4) if p is not None else None})
    probs = [lg["prob"] for lg in out_legs]
    entry = entry_ev(probs, multiplier) if all(p is not None for p in probs) else None
    return {"legs": out_legs, "entry": entry}


if __name__ == "__main__":
    # Example: two legs each ~57% to hit on a 3x two-pick power play.
    demo = evaluate([
        {"label": "LeBron o25.5 pts", "side": "over", "over_odds": -130, "under_odds": 105},
        {"label": "Tatum u27.5 pts", "side": "under", "over_odds": 110, "under_odds": -135},
    ], multiplier=3.0)
    for lg in demo["legs"]:
        print(f"  {lg.get('label','leg'):<22} hit {lg['prob']*100:.1f}%")
    e = demo["entry"]
    print(f"  entry: win {e['win_prob']*100:.1f}%  x{e['multiplier']}  -> EV {e['ev']*100:+.1f}%  "
          f"(breakeven needs x{e['breakeven_multiplier']})")
