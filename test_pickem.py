"""Tests for the pick'em +EV math. Run: python test_pickem.py (pure math)."""
import pickem_calc as pk


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_leg_prob_devig():
    # symmetric -110/-110 -> 50% each side
    assert approx(pk.leg_prob("over", -110, -110), 0.5)
    # juiced over -150 / under +120 -> over is the favourite
    p_over = pk.leg_prob("over", -150, 120)
    p_under = pk.leg_prob("under", -150, 120)
    assert p_over > 0.5 and approx(p_over + p_under, 1.0)
    print(f"ok  leg de-vig (over -150 -> {p_over*100:.1f}% hit)")


def test_entry_ev_power_play():
    # two 57% legs on a 3x two-pick: win = .57^2 = .3249; EV = .3249*3 - 1 = -0.025
    e = pk.entry_ev([0.57, 0.57], 3.0)
    assert approx(e["win_prob"], 0.3249) and approx(e["ev"], -0.0253, tol=1e-3), e
    # same legs but a 3.2x app pays +EV
    assert pk.entry_ev([0.57, 0.57], 3.2)["ev"] > 0
    # breakeven multiplier = 1/winprob
    assert approx(e["breakeven_multiplier"], 1 / 0.3249, tol=0.01)
    print(f"ok  power-play EV (.57x.57 @3x -> {e['ev']*100:.1f}%, breakeven x{e['breakeven_multiplier']})")


def test_evaluate_end_to_end():
    r = pk.evaluate([
        {"side": "over", "over_odds": -120, "under_odds": 100},
        {"side": "under", "over_odds": 100, "under_odds": -120},
    ], 3.0)
    assert all(lg["prob"] is not None for lg in r["legs"])
    assert r["entry"]["n_legs"] == 2 and "ev" in r["entry"]
    print(f"ok  evaluate end-to-end (entry EV {r['entry']['ev']*100:+.1f}%)")


def test_higher_hit_rate_better_ev():
    low = pk.entry_ev([0.5, 0.5], 3.0)["ev"]
    high = pk.entry_ev([0.62, 0.62], 3.0)["ev"]
    assert high > low
    print(f"ok  fatter legs -> better EV ({high*100:+.1f}% vs {low*100:+.1f}%)")


def test_api_pickem_route():
    import main
    c = main.app.test_client()
    r = c.post("/api/pickem", json={"multiplier": 3.0, "legs": [
        {"side": "over", "over_odds": -110, "under_odds": -110},
        {"side": "over", "over_odds": -110, "under_odds": -110}]})
    assert r.status_code == 200, r.status_code
    d = r.get_json()
    assert d["entry"]["n_legs"] == 2 and approx(d["entry"]["win_prob"], 0.25)
    print(f"ok  /api/pickem route (2x50% @3x -> EV {d['entry']['ev']*100:+.0f}%)")


if __name__ == "__main__":
    test_leg_prob_devig()
    test_entry_ev_power_play()
    test_evaluate_end_to_end()
    test_higher_hit_rate_better_ev()
    test_api_pickem_route()
    print("\nALL PASSED")
