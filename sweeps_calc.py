"""Tools for sweepstakes / social sportsbooks (Fliff, Rebet, Thrillz, etc.).

These books aren't in any odds feed, so we can't auto-scan them. But the same
edges still exist — they just have to be checked by hand:

  manual_ev   : you read a line off your sweeps book and a SHARP line off a major
                book; this de-vigs the sharp line to "fair" and tells you whether
                your sweeps price is +EV. (Same math as the Value Finder, manual.)
  bonus_value : sweeps books shower you with free Sweeps Coins (SC). SC redeems for
                cash after some play-through; this estimates the real-cash value
                after the small edge you bleed wagering it.
"""
import metrics


def manual_ev(your_odds, ref_side_odds, ref_other_odds, stake=100.0):
    """Is your sweeps-book price +EV vs the sharp line?

    your_odds       : American odds your book offers on the side you'd bet
    ref_side_odds   : a sharp book's American odds on THAT SAME side
    ref_other_odds  : the sharp book's odds on the other side (to de-vig)
    Returns fair_prob, ev_pct, expected_profit (on `stake`). None if invalid.
    """
    for o in (your_odds, ref_side_odds, ref_other_odds):
        d = metrics.american_to_implied(o) if _valid(o) else None
        if d is None:
            return None
    iside = metrics.american_to_implied(ref_side_odds)
    iother = metrics.american_to_implied(ref_other_odds)
    total = iside + iother
    if total <= 0:
        return None
    fair = iside / total
    dec = 1.0 + metrics.american_to_decimal_profit(your_odds)
    ev = fair * dec - 1.0
    return {
        "fair_prob": round(fair, 4),
        "ev_pct": round(ev, 4),
        "expected_profit": round(ev * float(stake), 2),
        "your_implied": round(metrics.american_to_implied(your_odds), 4),
        "plus_ev": ev > 0,
    }


def bonus_value(sc, playthrough=1.0, edge=0.045):
    """Estimate the real-cash value of a Sweeps Coins bonus.

    sc          : Sweeps Coins received
    playthrough : times you must wager the SC before redeeming (1x is common)
    edge        : the average edge you bleed per wager (≈0.045 = a -110 market's vig)
    Value ≈ sc × (1 − playthrough × edge), floored at 0.
    """
    try:
        sc, playthrough, edge = float(sc), float(playthrough), float(edge)
    except (TypeError, ValueError):
        return None
    if sc < 0 or playthrough < 0 or not (0 <= edge < 1):
        return None
    value = max(0.0, sc * (1.0 - playthrough * edge))
    return {"sc": round(sc, 2), "value": round(value, 2),
            "retention": round(value / sc, 4) if sc > 0 else None,
            "playthrough": playthrough, "edge": edge}


def _valid(o):
    try:
        v = float(o)
    except (TypeError, ValueError):
        return False
    return v <= -100 or v >= 100


if __name__ == "__main__":
    print(manual_ev(150, 120, -140))     # your +150 vs sharp +120/-140
    print(bonus_value(50, 1.0))          # 50 SC at 1x playthrough
