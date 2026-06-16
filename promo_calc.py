"""Matched-betting calculator — turn bookmaker promos into near-guaranteed cash.

The safest money in betting: books hand out free bets, bonuses and odds boosts to
attract you. "Matched betting" neutralises the gamble — you BACK a selection at
the book and LAY the same selection on a betting exchange (Betfair etc.), so every
outcome is covered and you lock in most of the promo's value as real cash.

This module does the math (exchange lay, decimal odds, commission on exchange
winnings). Two bet types cover ~all promos:

  qualifying : a real-money bet you must place to UNLOCK a bonus. Goal is to lose
               as little as possible doing it (the "qualifying loss").
  free_snr   : a FREE bet, Stake Not Returned (the usual kind). Goal is to extract
               the most cash from it — typically ~70-80% of the free-bet value.

All odds are DECIMAL (what exchanges quote): 2.00 = even money = American +100.
"""


def american_to_decimal(odds):
    """Convenience: American -> decimal, so the UI can accept either."""
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / (-odds))


def matched_bet(back_odds, lay_odds, commission, back_stake, bet_type="qualifying"):
    """Compute the optimal lay and the locked outcome.

    back_odds/lay_odds : DECIMAL odds (>1)
    commission         : exchange commission on winnings, 0..1 (e.g. 0.02 = 2%)
    back_stake         : your back stake (for free bets, the free-bet amount)
    bet_type           : 'qualifying' or 'free_snr'

    Returns lay_stake, liability, profit if each side wins, and the locked result
    (the guaranteed amount — both sides are engineered to match). None if invalid.
    """
    try:
        bo, lo, c, s = float(back_odds), float(lay_odds), float(commission), float(back_stake)
    except (TypeError, ValueError):
        return None
    if bo <= 1 or lo <= 1 or s <= 0 or not (0 <= c < 1) or lo - c <= 0:
        return None

    if bet_type == "free_snr":
        # free-bet stake isn't returned, so only the (bo-1) winnings are at stake
        lay_stake = ((bo - 1) * s) / (lo - c)
        liability = lay_stake * (lo - 1)
        profit_back = s * (bo - 1) - liability
        profit_lay = lay_stake * (1 - c)
    else:  # qualifying (real-money bet)
        lay_stake = (bo * s) / (lo - c)
        liability = lay_stake * (lo - 1)
        profit_back = s * (bo - 1) - liability
        profit_lay = lay_stake * (1 - c) - s

    locked = min(profit_back, profit_lay)
    out = {
        "bet_type": bet_type,
        "lay_stake": round(lay_stake, 2),
        "liability": round(liability, 2),
        "profit_back": round(profit_back, 2),   # if the back (book) side wins
        "profit_lay": round(profit_lay, 2),      # if the lay (exchange) side wins
        "locked": round(locked, 2),              # guaranteed regardless of result
    }
    if bet_type == "free_snr" and s > 0:
        out["retention"] = round(locked / s, 4)  # % of the free bet kept as cash
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Matched-betting calculator (decimal odds).")
    ap.add_argument("back_odds", type=float)
    ap.add_argument("lay_odds", type=float)
    ap.add_argument("--commission", type=float, default=0.02)
    ap.add_argument("--stake", type=float, default=10.0)
    ap.add_argument("--type", choices=("qualifying", "free_snr"), default="qualifying")
    args = ap.parse_args()
    r = matched_bet(args.back_odds, args.lay_odds, args.commission, args.stake, args.type)
    if not r:
        print("Invalid inputs.")
    else:
        print(f"\nLay £{r['lay_stake']} (liability £{r['liability']})")
        print(f"  if back wins: £{r['profit_back']}")
        print(f"  if lay wins:  £{r['profit_lay']}")
        print(f"  LOCKED:       £{r['locked']}"
              + (f"  ({r['retention']*100:.1f}% of the free bet)" if "retention" in r else ""))
