"""Options strategy calculator — the popular Robinhood plays, with honest numbers.

Every strategy returns the same shape: max profit, max loss, breakeven(s), the
return on what you tie up, an annualized version of that, and (when you pass IV +
days) a rough probability of profit from a lognormal model. Income strategies
(covered calls, cash-secured puts — "the wheel") and defined-risk spreads are the
bread and butter; long calls/puts are included for directional bets.

All premiums/strikes are per share; one contract = 100 shares.
"""
import math

CONTRACT = 100


def _ann(ret, days):
    return round(ret * 365.0 / days, 4) if (days and days > 0 and ret is not None) else None


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_above(spot, target, iv, days):
    """P(price > target at expiry) under a lognormal model. None if inputs missing."""
    if not (spot and target and iv and days and spot > 0 and target > 0 and iv > 0 and days > 0):
        return None
    t = days / 365.0
    sigma = iv * math.sqrt(t)
    # drift-less (risk-neutral-ish) lognormal: ln(S_T/S) ~ N(-sigma^2/2, sigma^2)
    z = (math.log(target / spot) + 0.5 * sigma ** 2) / sigma
    return round(1 - _norm_cdf(z), 4)


def prob_below(spot, target, iv, days):
    p = prob_above(spot, target, iv, days)
    return round(1 - p, 4) if p is not None else None


def _r(x, nd=2):
    return round(x, nd) if isinstance(x, (int, float)) else None


def covered_call(stock_price, strike, premium, contracts=1, days=None, iv=None):
    """Own 100 shares/contract, sell a call. Income + capped upside."""
    sh = contracts * CONTRACT
    income = premium * sh
    if_called = (strike - stock_price) * sh + income      # profit if assigned at strike
    static_ret = premium / stock_price                    # kept premium vs stock cost
    called_ret = if_called / (stock_price * sh)
    return {
        "strategy": "Covered call",
        "premium_income": _r(income),
        "max_profit": _r(if_called), "max_profit_note": "if called away at strike",
        "max_loss_note": "stock can fall to $0 (minus premium collected)",
        "breakeven": _r(stock_price - premium),
        "downside_protection": _r(premium / stock_price, 4),
        "static_return": _r(static_ret, 4), "static_return_annualized": _ann(static_ret, days),
        "if_called_return": _r(called_ret, 4), "if_called_annualized": _ann(called_ret, days),
        "prob_keep_shares": prob_below(stock_price, strike, iv, days),  # stays below strike
        "capital": _r(stock_price * sh),
    }


def cash_secured_put(strike, premium, contracts=1, days=None, stock_price=None, iv=None):
    """Sell a put backed by cash. Income, or buy the stock cheaper if assigned."""
    sh = contracts * CONTRACT
    income = premium * sh
    collateral = strike * sh
    breakeven = strike - premium
    ret = premium / strike
    out = {
        "strategy": "Cash-secured put",
        "premium_income": _r(income),
        "max_profit": _r(income), "max_profit_note": "if it expires out of the money",
        "max_loss_note": "assigned, then stock falls to $0 (less premium)",
        "breakeven": _r(breakeven), "effective_buy_price": _r(breakeven),
        "collateral": _r(collateral),
        "return_if_otm": _r(ret, 4), "annualized": _ann(ret, days),
        "prob_keep_premium": prob_above(stock_price, strike, iv, days) if stock_price else None,
    }
    if stock_price:
        out["discount_to_current"] = _r((stock_price - breakeven) / stock_price, 4)
    return out


_VERTICALS = {
    # name: (is_credit, breakeven_fn(low, high, prem))
    "bull_call": (False, lambda lo, hi, p: lo + p),   # debit, buy lo call / sell hi call
    "bear_put":  (False, lambda lo, hi, p: hi - p),   # debit, buy hi put / sell lo put
    "bull_put":  (True,  lambda lo, hi, p: hi - p),   # credit, sell hi put / buy lo put
    "bear_call": (True,  lambda lo, hi, p: lo + p),   # credit, sell lo call / buy hi call
}


def vertical_spread(kind, strike_a, strike_b, premium, contracts=1):
    """Defined-risk two-leg spread. `premium` is the net per share (always positive:
    you pay it on debits, receive it on credits). kind in _VERTICALS."""
    if kind not in _VERTICALS:
        return None
    is_credit, be_fn = _VERTICALS[kind]
    lo, hi = sorted((float(strike_a), float(strike_b)))
    width = (hi - lo)
    p = abs(float(premium))
    if p <= 0 or width <= 0 or p >= width:
        return None
    sh = contracts * CONTRACT
    if is_credit:
        max_profit, max_loss = p * sh, (width - p) * sh
    else:
        max_loss, max_profit = p * sh, (width - p) * sh
    return {
        "strategy": kind.replace("_", " ").title() + (" (credit)" if is_credit else " (debit)"),
        "max_profit": _r(max_profit), "max_loss": _r(max_loss),
        "breakeven": _r(be_fn(lo, hi, p)),
        "risk_reward": _r(max_profit / max_loss, 2) if max_loss else None,
        "width": _r(width * sh), "is_credit": is_credit,
        "capital_at_risk": _r(max_loss),
    }


def long_option(kind, strike, premium, contracts=1, stock_price=None, days=None, iv=None):
    """Long call or put — directional, max loss = premium."""
    sh = contracts * CONTRACT
    cost = premium * sh
    if kind == "call":
        be = strike + premium
        out = {"strategy": "Long call", "max_profit_note": "unlimited (uncapped upside)",
               "max_profit": None, "breakeven": _r(be),
               "prob_profit": prob_above(stock_price, be, iv, days) if stock_price else None}
    else:
        be = strike - premium
        out = {"strategy": "Long put", "max_profit": _r((strike - premium) * sh),
               "max_profit_note": "if stock goes to $0", "breakeven": _r(be),
               "prob_profit": prob_below(stock_price, be, iv, days) if stock_price else None}
    out.update({"max_loss": _r(cost), "max_loss_note": "premium paid (if it expires worthless)",
                "cost": _r(cost), "capital_at_risk": _r(cost)})
    return out
