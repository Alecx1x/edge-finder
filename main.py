"""Entry point: local Flask web app for the Edge Finder.

Running `python main.py` starts a local server and opens a browser tab with the
web UI. All scoring/data/odds/config logic is unchanged — this file only
replaces the old terminal display layer with HTTP endpoints + a browser UI.

  python main.py
"""
import os
import socket
import threading
import time
import webbrowser


def _open_browser(url):
    """Open `url` in Edge if it's installed, otherwise the system default."""
    for path in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if os.path.exists(path):
            webbrowser.register("edge", None, webbrowser.BackgroundBrowser(path))
            webbrowser.get("edge").open(url)
            return
    webbrowser.open(url)

from flask import Flask, jsonify, render_template, request

import config_manager as cfgmod
import odds_fetcher
import bestfightodds
import data_scrapers
import scoring_engine
import event_cache
import history_store
import supabase_store
import presets as presets_mod
import backtest_engine
import optimizer
import value_scanner
import arb_scanner
import promo_calc
import pickem_calc
import sweeps_calc
import crypto_safety
import crypto_screener
import whale_tracker
import smart_wallets
import options_calc
import stock_data
import insider
import academy

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True  # pick up index.html edits without a restart
app.jinja_env.auto_reload = True

# Loaded once; weight edits mutate this in place and persist to config.json.
CFG = cfgmod.load_config()


def _variables_payload():
    """Registry for the frontend: label, key, and which sports each applies to."""
    out = []
    for v in cfgmod.VARIABLES:
        out.append({
            "key": v["key"],
            "label": v["label"],
            "sports": sorted(v["sports"]) if v["sports"] else None,  # None = all
            "core": v.get("core", True),  # False = sport-specific advanced stat
        })
    return out


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template(
        "index.html",
        sports=cfgmod.SPORTS,
        variables=_variables_payload(),
        weights=CFG["weights"],
        bankroll=CFG.get("bankroll", 1000.0),
        has_key=bool(cfgmod.get_api_key()),
        storage=history_store.storage_status(),
    )


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.route("/api/academy")
def api_academy():
    # Curated learning library (academy.py is the single source of truth).
    return jsonify(academy.to_json())


# --------------------------------------------------------------------------- #
@app.route("/api/status")
def api_status():
    return jsonify({
        "has_key": bool(cfgmod.get_api_key()),
        "sports": cfgmod.SPORTS,
        "variables": _variables_payload(),
        "weights": CFG["weights"],
        "bankroll": CFG.get("bankroll", 1000.0),
    })


@app.route("/api/events")
def api_events():
    """Cached upcoming-events tree for the browser sidebar (built on boot)."""
    cache = event_cache.load()
    if cache is None:                       # first run before the boot thread finished
        cache = event_cache.get(cfgmod.get_api_key())
    return jsonify(event_cache.public(cache))


@app.route("/api/events/refresh", methods=["POST"])
def api_events_refresh():
    """Manual refresh button — force a rebuild regardless of cache age."""
    cache = event_cache.get(cfgmod.get_api_key(), force=True)
    return jsonify(event_cache.public(cache))


@app.route("/api/key", methods=["POST"])
def api_key():
    key = (request.get_json(silent=True) or {}).get("key", "").strip()
    if not key:
        return jsonify({"ok": False, "error": "No key provided."}), 400
    try:
        remaining = odds_fetcher.validate_key(key)
    except odds_fetcher.OddsError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    cfgmod.save_api_key(key)
    return jsonify({"ok": True, "remaining": remaining})


@app.route("/api/presets", methods=["GET"])
def api_presets_list():
    return jsonify({"presets": presets_mod.list_presets(),
                    "mode": history_store.storage_status()["mode"]})


@app.route("/api/presets", methods=["POST"])
def api_presets_add():
    body = request.get_json(silent=True) or {}
    preset, err = presets_mod.add_preset(body.get("name"), body.get("sport"),
                                         body.get("weights") or {})
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "preset": preset})


@app.route("/api/presets/<pid>", methods=["DELETE"])
def api_presets_delete(pid):
    ok = presets_mod.delete_preset(pid)
    if not ok:
        return jsonify({"ok": False, "error": "Preset not found or not deletable."}), 400
    return jsonify({"ok": True})


@app.route("/api/weights", methods=["POST"])
def api_weights():
    body = request.get_json(silent=True) or {}
    if body.get("reset"):
        for v in cfgmod.VARIABLES:
            CFG["weights"][v["key"]] = 1.0
        cfgmod.save_config(CFG)
        return jsonify({"ok": True, "weights": CFG["weights"]})

    updates = body.get("weights", body)  # accept {weights:{...}} or {key:val}
    bad = []
    for key, val in updates.items():
        if key in CFG["weights"]:
            if not cfgmod.set_weight(CFG, key, val):
                bad.append(key)
    return jsonify({"ok": not bad, "weights": CFG["weights"], "rejected": bad})


def _parse_american(raw):
    """Validate a manually-entered American moneyline. Returns float or None."""
    try:
        val = float(str(raw).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None
    if val == 0 or -100 < val < 100:        # American odds are always <=-100 or >=+100
        return None
    return val


def _manual_matchup(sport, name_a, name_b, odds_a, odds_b):
    """Build a matchup dict from user-supplied odds, shaped like find_matchup()."""
    return {
        "sport": sport,
        "league": "Manual odds entry",
        "sport_key": "manual",
        "commence_time": None,
        "home_team": None,
        "away_team": None,
        "bookmaker_count": 0,
        "a": {"name": name_a, "odds": round(odds_a, 1)},
        "b": {"name": name_b, "odds": round(odds_b, 1)},
        "quota": {},
        "searched": [],
        "manual": True,
    }


def _resolve_close_odds(bet):
    """Fetch current (≈closing) odds for a logged bet via The Odds API.

    Returns ((bet_side_close, other_side_close), None) or (None, error_message).
    Aligns the feed's resolved participants back to the bet's name_a/name_b.
    """
    from mma_sources import fold
    api_key_val = cfgmod.get_api_key()
    if not api_key_val:
        return None, "No Odds API key set."
    try:
        m = odds_fetcher.find_matchup(api_key_val, bet["sport"], bet["name_a"], bet["name_b"], CFG)
    except odds_fetcher.NoMatchup:
        return None, "Matchup not on the feed now (it may have already started/closed). Enter the close manually."
    except odds_fetcher.OddsError as e:
        return None, str(e)

    def same(x, y):
        fx, fy = fold(x or "").lower().strip(), fold(y or "").lower().strip()
        return bool(fx) and (fx == fy or fx in fy or fy in fx)

    ma, mb = m["a"], m["b"]
    if same(ma["name"], bet["name_a"]):
        odds_a, odds_b = ma["odds"], mb["odds"]
    elif same(mb["name"], bet["name_a"]):
        odds_a, odds_b = mb["odds"], ma["odds"]
    else:
        return None, "Found the event but couldn't match fighters by name. Enter the close manually."

    if bet.get("bet_side") == "a":
        return (odds_a, odds_b), None
    return (odds_b, odds_a), None


def _run_report(sport, matchup):
    """Gather per-variable data for a resolved matchup and build the edge report."""
    variables = cfgmod.variables_for_sport(sport)
    data = data_scrapers.gather(sport, matchup["a"]["name"], matchup["b"]["name"], matchup, variables)
    report = scoring_engine.build_report(sport, matchup, data, CFG)
    report["matchup"].pop("raw_event", None)        # trim bulky payload
    report["quota"] = matchup.get("quota", {})

    # History & Analytics: snapshot odds + edge score, hand the series back for charts.
    try:
        key, odds_entry, edge_entry = history_store.record_analysis(report)
        report["history_key"] = key
        report["odds_history"] = odds_entry
        report["edge_history"] = edge_entry
    except Exception:
        pass  # bookkeeping must never break the analysis itself
    return report


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(silent=True) or {}
    sport = body.get("sport", "")
    name_a = (body.get("name_a") or "").strip()
    name_b = (body.get("name_b") or "").strip()

    if sport not in cfgmod.SPORTS:
        return jsonify({"error": "Unknown sport."}), 400
    if not name_a or not name_b:
        return jsonify({"error": "Both names are required."}), 400

    # --- Manual-odds path: user supplied odds directly; skip all odds sources. ---
    if body.get("odds_a") is not None and body.get("odds_b") is not None:
        oa, ob = _parse_american(body.get("odds_a")), _parse_american(body.get("odds_b"))
        if oa is None or ob is None:
            return jsonify({"error": "Enter valid American odds for both sides "
                                     "(e.g. -150 and +130)."}), 400
        matchup = _manual_matchup(sport, name_a, name_b, oa, ob)
        return jsonify({"report": _run_report(sport, matchup), "odds_source": "manual"})

    api_key_val = cfgmod.get_api_key()
    if not api_key_val:
        return jsonify({"error": "No Odds API key set. Add your key first.", "need_key": True}), 400

    # --- Primary: The Odds API across every active league in the sport group. ---
    try:
        matchup = odds_fetcher.find_matchup(api_key_val, sport, name_a, name_b, CFG)
        return jsonify({"report": _run_report(sport, matchup), "odds_source": "The Odds API"})
    except odds_fetcher.NoMatchup:
        pass  # feed reached, no match — fall through to secondary sources
    except odds_fetcher.OddsError as e:
        return jsonify({"error": str(e)}), 502

    # --- Secondary (MMA only): scrape BestFightOdds for non-UFC promotions. ---
    if sport == "MMA":
        bfo = bestfightodds.find_matchup(name_a, name_b)
        if bfo:
            return jsonify({"report": _run_report(sport, bfo), "odds_source": "BestFightOdds"})

    # --- Last resort: no odds source had it. Offer manual entry; never hard-fail. ---
    return jsonify({
        "need_manual_odds": True,
        "sport": sport,
        "name_a": name_a,
        "name_b": name_b,
        "message": ("No odds source had this matchup. Enter the moneyline odds "
                    "manually to run the analysis on available stats."),
    })


# --------------------------------------------------------------------------- #
# History & Analytics
# --------------------------------------------------------------------------- #
@app.route("/api/storage", methods=["GET"])
def api_storage():
    """Current storage backend (supabase vs local json) for the settings UI."""
    url, _ = cfgmod.get_supabase()
    status = history_store.storage_status()
    status["url"] = url           # key is never echoed back
    return jsonify(status)


@app.route("/api/supabase", methods=["POST"])
def api_supabase():
    """Save Supabase URL + anon key to .env, then probe the connection."""
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    key = (body.get("key") or "").strip()
    if not url or not key:
        return jsonify({"ok": False, "error": "Enter both a Supabase URL and anon key."}), 400
    cfgmod.save_supabase(url, key)
    supabase_store.reset_active()
    ok, message = supabase_store.test_connection()
    if ok:
        presets_mod.seed_defaults()        # populate the presets table on first connect
    return jsonify({"ok": ok, "message": message, "storage": history_store.storage_status()})


@app.route("/api/bankroll", methods=["POST"])
def api_bankroll():
    val = (request.get_json(silent=True) or {}).get("bankroll")
    if not cfgmod.set_bankroll(CFG, val):
        return jsonify({"ok": False, "error": "Enter a valid bankroll amount."}), 400
    return jsonify({"ok": True, "bankroll": CFG["bankroll"]})


@app.route("/api/bets", methods=["GET"])
def api_bets_list():
    return jsonify({"bets": history_store.list_bets()})


@app.route("/api/bets", methods=["POST"])
def api_bets_add():
    body = request.get_json(silent=True) or {}
    required = ("sport", "name_a", "name_b", "bet_side", "bet_name", "bet_odds", "edge", "model_prob")
    if any(body.get(k) is None for k in required):
        return jsonify({"ok": False, "error": "Incomplete bet payload."}), 400
    bet = {
        "sport": body["sport"],
        "name_a": body["name_a"],
        "name_b": body["name_b"],
        "bet_side": body["bet_side"],            # 'a' | 'b'
        "bet_name": body["bet_name"],
        "bet_odds": body["bet_odds"],
        "odds_a": body.get("odds_a"),
        "odds_b": body.get("odds_b"),
        "edge": body["edge"],
        "model_prob": body["model_prob"],        # model win prob for the bet side
        "stake": body.get("stake"),
    }
    return jsonify({"ok": True, "bet": history_store.add_bet(bet)})


@app.route("/api/bets/<int:bet_id>/result", methods=["POST"])
def api_bets_result(bet_id):
    result = (request.get_json(silent=True) or {}).get("result", "")
    bet = history_store.set_bet_result(bet_id, result)
    if not bet:
        return jsonify({"ok": False, "error": "Unknown bet id or invalid result."}), 400
    return jsonify({"ok": True, "bet": bet})


@app.route("/api/bets/<int:bet_id>/close", methods=["POST"])
def api_bets_close(bet_id):
    """Manually record the closing line for a bet (free — no API call)."""
    body = request.get_json(silent=True) or {}
    close_side = _parse_american(body.get("close_side"))
    if close_side is None:
        return jsonify({"ok": False, "error": "Enter valid closing odds for your side "
                                               "(e.g. -120)."}), 400
    other_raw = body.get("other_close")
    other_close = _parse_american(other_raw) if other_raw not in (None, "") else None
    if other_raw not in (None, "") and other_close is None:
        return jsonify({"ok": False, "error": "Other-side closing odds are invalid."}), 400
    bet = history_store.set_bet_close(bet_id, close_side, other_close)
    if not bet:
        return jsonify({"ok": False, "error": "Unknown bet id."}), 400
    return jsonify({"ok": True, "bet": bet})


@app.route("/api/bets/<int:bet_id>/capture", methods=["POST"])
def api_bets_capture(bet_id):
    """Auto-capture the closing line from the live feed (spends Odds API quota)."""
    bet = next((b for b in history_store.list_bets() if b.get("id") == bet_id), None)
    if not bet:
        return jsonify({"ok": False, "error": "Unknown bet id."}), 400
    pair, err = _resolve_close_odds(bet)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    updated = history_store.set_bet_close(bet_id, pair[0], pair[1])
    return jsonify({"ok": True, "bet": updated})


@app.route("/api/clv", methods=["GET"])
def api_clv():
    return jsonify(history_store.clv())


@app.route("/api/calibration", methods=["GET"])
def api_calibration():
    return jsonify(history_store.calibration())


@app.route("/api/history/odds", methods=["GET"])
def api_history_odds():
    a, b = request.args.get("a", ""), request.args.get("b", "")
    sport = request.args.get("sport", "")
    return jsonify(history_store.odds_history(sport, a, b) or {"snapshots": []})


@app.route("/api/history/matchup", methods=["GET"])
def api_history_matchup():
    a, b = request.args.get("a", ""), request.args.get("b", "")
    sport = request.args.get("sport", "")
    return jsonify(history_store.matchup_history(sport, a, b) or {"points": []})


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """Replay the historical dataset through the engine with the current weights."""
    body = request.get_json(silent=True) or {}
    try:
        edge = float(body.get("edge_threshold", 0.02))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid edge threshold."}), 400
    edge = max(0.0, min(0.5, edge))
    date_from = (body.get("date_from") or "").strip() or None
    date_to = (body.get("date_to") or "").strip() or None
    try:
        scorecard = backtest_engine.run_backtest(
            CFG, edge_threshold=edge, date_from=date_from, date_to=date_to)
    except FileNotFoundError as e:
        return jsonify({"error": str(e), "need_dataset": True}), 400
    except Exception as e:
        return jsonify({"error": f"Backtest failed: {e}"}), 500
    return jsonify(scorecard)


@app.route("/api/tune", methods=["POST"])
def api_tune():
    """Walk-forward auto-tune: search train-slice weights, grade on unseen test."""
    body = request.get_json(silent=True) or {}
    try:
        edge = max(0.0, min(0.5, float(body.get("edge_threshold", 0.02))))
        train_frac = float(body.get("train_frac", 0.7))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid tuning parameters."}), 400
    objective = "log_loss" if body.get("objective") == "log_loss" else "roi"
    try:
        result = optimizer.walk_forward(
            CFG, train_frac=train_frac, edge_threshold=edge, objective=objective)
    except FileNotFoundError as e:
        return jsonify({"error": str(e), "need_dataset": True}), 400
    except Exception as e:
        return jsonify({"error": f"Auto-tune failed: {e}"}), 500
    return jsonify(result)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Live +EV scan vs the sharp line. Spends Odds API quota (one call/league)."""
    body = request.get_json(silent=True) or {}
    sport = body.get("sport", "")
    if sport not in cfgmod.SPORTS:
        return jsonify({"error": "Unknown sport."}), 400
    api_key_val = cfgmod.get_api_key()
    if not api_key_val:
        return jsonify({"error": "No Odds API key set. Add your key first.", "need_key": True}), 400
    try:
        min_ev = max(0.0, min(0.5, float(body.get("min_ev", 0.02))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid EV threshold."}), 400
    regions = (body.get("regions") or "us,eu").strip()
    try:
        max_keys = max(1, min(12, int(body.get("max_keys", 6))))
    except (TypeError, ValueError):
        max_keys = 6
    try:
        res = value_scanner.scan(api_key_val, sport, regions=regions, min_ev=min_ev,
                                 bankroll=CFG.get("bankroll", 1000.0), max_keys=max_keys,
                                 my_books=cfgmod.get_my_books(CFG))
    except odds_fetcher.OddsError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Scan failed: {e}"}), 500
    return jsonify(res)


@app.route("/api/books", methods=["GET"])
def api_books_get():
    """Available bookmakers for the filter + the user's current selection."""
    return jsonify({"available": value_scanner.KNOWN_BOOKS,
                    "selected": cfgmod.get_my_books(CFG)})


@app.route("/api/books", methods=["POST"])
def api_books_set():
    keys = (request.get_json(silent=True) or {}).get("books")
    if not cfgmod.set_my_books(CFG, keys or []):
        return jsonify({"ok": False, "error": "Expected a list of bookmaker keys."}), 400
    return jsonify({"ok": True, "selected": CFG["my_books"]})


@app.route("/api/arb", methods=["POST"])
def api_arb():
    """Live arbitrage scan across books. Spends Odds API quota (one call/league)."""
    body = request.get_json(silent=True) or {}
    sport = body.get("sport", "")
    if sport not in cfgmod.SPORTS:
        return jsonify({"error": "Unknown sport."}), 400
    api_key_val = cfgmod.get_api_key()
    if not api_key_val:
        return jsonify({"error": "No Odds API key set. Add your key first.", "need_key": True}), 400
    try:
        min_profit = max(0.0, min(0.5, float(body.get("min_profit", 0.0))))
        total_stake = max(1.0, min(1_000_000.0, float(body.get("total_stake", 100.0))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid scan parameters."}), 400
    regions = (body.get("regions") or "us,eu").strip()
    try:
        max_keys = max(1, min(12, int(body.get("max_keys", 6))))
    except (TypeError, ValueError):
        max_keys = 6
    try:
        res = arb_scanner.scan(api_key_val, sport, regions=regions, min_profit=min_profit,
                               total_stake=total_stake, max_keys=max_keys,
                               my_books=cfgmod.get_my_books(CFG))
    except odds_fetcher.OddsError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Arb scan failed: {e}"}), 500
    return jsonify(res)


@app.route("/api/promo", methods=["POST"])
def api_promo():
    """Matched-betting calculator (pure math, no API quota)."""
    body = request.get_json(silent=True) or {}
    bet_type = "free_snr" if body.get("bet_type") == "free_snr" else "qualifying"
    res = promo_calc.matched_bet(body.get("back_odds"), body.get("lay_odds"),
                                 body.get("commission", 0.02), body.get("back_stake"),
                                 bet_type)
    if res is None:
        return jsonify({"error": "Enter valid decimal odds (>1), a positive stake, "
                                 "and commission 0–1."}), 400
    return jsonify(res)


@app.route("/api/pickem", methods=["POST"])
def api_pickem():
    """Pick'em entry EV (DraftKings Pick6 / Betr). Pure math, no quota."""
    body = request.get_json(silent=True) or {}
    legs = body.get("legs") or []
    if not isinstance(legs, list) or not legs:
        return jsonify({"error": "Add at least one leg."}), 400
    res = pickem_calc.evaluate(legs, body.get("multiplier", 3.0))
    if res["entry"] is None:
        return jsonify({"error": "Each leg needs valid sharp over/under odds, plus a "
                                 "payout multiplier.", "legs": res["legs"]}), 400
    return jsonify(res)


@app.route("/api/sweeps_ev", methods=["POST"])
def api_sweeps_ev():
    """Manual +EV check for a sweeps-book line vs a sharp reference. No quota."""
    body = request.get_json(silent=True) or {}
    res = sweeps_calc.manual_ev(body.get("your_odds"), body.get("ref_side_odds"),
                                body.get("ref_other_odds"), body.get("stake", 100.0))
    if res is None:
        return jsonify({"error": "Enter valid American odds for your bet and both "
                                 "sides of the sharp line."}), 400
    return jsonify(res)


@app.route("/api/sweeps_bonus", methods=["POST"])
def api_sweeps_bonus():
    """Estimate the cash value of a Sweeps Coins bonus. No quota."""
    body = request.get_json(silent=True) or {}
    res = sweeps_calc.bonus_value(body.get("sc"), body.get("playthrough", 1.0),
                                  body.get("edge", 0.045))
    if res is None:
        return jsonify({"error": "Enter a non-negative SC amount, playthrough, and edge 0–1."}), 400
    return jsonify(res)


@app.route("/api/crypto/token", methods=["POST"])
def api_crypto_token():
    """Token safety report (GoPlus + DexScreener). Free APIs, no quota."""
    body = request.get_json(silent=True) or {}
    address = body.get("address", "")
    chain = body.get("chain", "ethereum")
    now_ms = int(time.time() * 1000)
    try:
        report, err = crypto_safety.assess(address, chain, now_ms=now_ms)
    except Exception as e:
        return jsonify({"error": f"Check failed: {e}"}), 500
    if err:
        return jsonify({"error": err}), 400
    return jsonify(report)


@app.route("/api/crypto/screen", methods=["POST"])
def api_crypto_screen():
    """Trending meme-coin screener (DexScreener). Free, no quota."""
    body = request.get_json(silent=True) or {}
    chain = body.get("chain", "all")
    source = "top" if body.get("source") == "top" else "latest"
    sort = body.get("sort", "volume_24h")
    try:
        min_liq = max(0.0, float(body.get("min_liquidity", 0)))
    except (TypeError, ValueError):
        min_liq = 0.0
    now_ms = int(time.time() * 1000)
    try:
        res = crypto_screener.screen(chain=chain, source=source, min_liquidity=min_liq,
                                     sort=sort, now_ms=now_ms)
    except Exception as e:
        return jsonify({"error": f"Screen failed: {e}"}), 500
    return jsonify(res)


@app.route("/api/crypto/wallets", methods=["GET"])
def api_crypto_wallets_get():
    return jsonify({"wallets": cfgmod.get_whale_wallets(CFG)})


@app.route("/api/crypto/wallets", methods=["POST"])
def api_crypto_wallets_set():
    wallets = (request.get_json(silent=True) or {}).get("wallets")
    if not cfgmod.set_whale_wallets(CFG, wallets or []):
        return jsonify({"ok": False, "error": "Expected a list of wallets."}), 400
    return jsonify({"ok": True, "wallets": CFG["whale_wallets"]})


@app.route("/api/crypto/whale_keys", methods=["GET"])
def api_crypto_whale_keys_get():
    return jsonify({"etherscan": bool(cfgmod.get_chain_key("etherscan")),
                    "helius": bool(cfgmod.get_chain_key("helius"))})


@app.route("/api/crypto/whale_keys", methods=["POST"])
def api_crypto_whale_keys_set():
    body = request.get_json(silent=True) or {}
    if "etherscan" in body:
        cfgmod.save_chain_key("etherscan", body.get("etherscan"))
    if "helius" in body:
        cfgmod.save_chain_key("helius", body.get("helius"))
    return jsonify({"ok": True, "etherscan": bool(cfgmod.get_chain_key("etherscan")),
                    "helius": bool(cfgmod.get_chain_key("helius"))})


@app.route("/api/crypto/activity", methods=["POST"])
def api_crypto_activity():
    """Pull recent token moves across the watched wallets. Free (Etherscan/Helius)."""
    wallets = cfgmod.get_whale_wallets(CFG)
    if not wallets:
        return jsonify({"feed": [], "convergence": {}, "errors": [], "n_wallets": 0,
                        "note": "Add some wallets to your watchlist first."})
    try:
        res = whale_tracker.wallet_activity(
            wallets, cfgmod.get_chain_key("etherscan"), cfgmod.get_chain_key("helius"))
    except Exception as e:
        return jsonify({"error": f"Activity fetch failed: {e}"}), 500
    return jsonify(res)


@app.route("/api/crypto/discover", methods=["POST"])
def api_crypto_discover():
    """Discover early buyers of a winning token; updates the leaderboard. Free."""
    body = request.get_json(silent=True) or {}
    chain = body.get("chain", "ethereum")
    try:
        res, err = smart_wallets.discover(
            body.get("address", ""), chain,
            cfgmod.get_chain_key("etherscan"), cfgmod.get_chain_key("helius"))
    except Exception as e:
        return jsonify({"error": f"Discovery failed: {e}"}), 500
    if err:
        return jsonify({"error": err}), 400
    return jsonify(res)


@app.route("/api/crypto/leaderboard", methods=["GET"])
def api_crypto_leaderboard():
    return jsonify({"leaderboard": smart_wallets.leaderboard()})


@app.route("/api/crypto/leaderboard/clear", methods=["POST"])
def api_crypto_leaderboard_clear():
    smart_wallets.clear_tally()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# Stocks / options
# --------------------------------------------------------------------------- #
@app.route("/api/stocks/strategy", methods=["POST"])
def api_stocks_strategy():
    """Options strategy calculator (pure math, no quota)."""
    b = request.get_json(silent=True) or {}
    s = b.get("strategy", "")

    def fnum(*keys):
        out = []
        for k in keys:
            try:
                out.append(float(b.get(k)))
            except (TypeError, ValueError):
                out.append(None)
        return out

    contracts = int(b.get("contracts") or 1)
    days = b.get("days")
    days = int(days) if days not in (None, "") else None
    iv = b.get("iv")
    iv = float(iv) if iv not in (None, "") else None
    res = None
    try:
        if s == "covered_call":
            sp, k, p = fnum("stock_price", "strike", "premium")
            res = options_calc.covered_call(sp, k, p, contracts, days, iv)
        elif s == "cash_secured_put":
            k, p = fnum("strike", "premium")
            sp = fnum("stock_price")[0]
            res = options_calc.cash_secured_put(k, p, contracts, days, sp, iv)
        elif s in ("bull_call", "bear_put", "bull_put", "bear_call"):
            a, bb, p = fnum("strike_a", "strike_b", "premium")
            res = options_calc.vertical_spread(s, a, bb, p, contracts)
        elif s in ("long_call", "long_put"):
            k, p = fnum("strike", "premium")
            sp = fnum("stock_price")[0]
            res = options_calc.long_option(s.split("_")[1], k, p, contracts, sp, days, iv)
        else:
            return jsonify({"error": "Unknown strategy."}), 400
    except (TypeError, ValueError):
        res = None
    if res is None:
        return jsonify({"error": "Check your inputs (premium must be less than the strike width on spreads)."}), 400
    return jsonify(res)


@app.route("/api/stocks/quote", methods=["POST"])
def api_stocks_quote():
    ticker = (request.get_json(silent=True) or {}).get("ticker", "").strip()
    if not ticker:
        return jsonify({"error": "Enter a ticker."}), 400
    q, err = stock_data.quote(ticker)
    if err:
        return jsonify({"error": err}), 502
    return jsonify(q)


@app.route("/api/stocks/options", methods=["POST"])
def api_stocks_options():
    b = request.get_json(silent=True) or {}
    ticker = (b.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "Enter a ticker."}), 400
    ch, err = stock_data.options_chain(ticker, b.get("expiry"))
    if err:
        return jsonify({"error": err}), 502
    return jsonify(ch)


@app.route("/api/stocks/insider", methods=["POST"])
def api_stocks_insider():
    """Recent insider (SEC Form 4) transactions for a ticker. Free, no quota."""
    ticker = (request.get_json(silent=True) or {}).get("ticker", "").strip()
    if not ticker:
        return jsonify({"error": "Enter a ticker."}), 400
    try:
        rep, err = insider.insider_activity(ticker)
    except Exception as e:
        return jsonify({"error": f"Insider lookup failed: {e}"}), 500
    if err:
        return jsonify({"error": err}), 502
    return jsonify(rep)


# --------------------------------------------------------------------------- #
# Server bootstrap
# --------------------------------------------------------------------------- #
def _free_port(preferred=5000):
    for port in (preferred, 5001, 5002, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            chosen = s.getsockname()[1]
            s.close()
            return chosen
        except OSError:
            s.close()
            continue
    return preferred


def _refresh_events_cache():
    """Ensure the event cache is current (rebuilds only if >24h old)."""
    try:
        event_cache.get(cfgmod.get_api_key())
    except Exception:
        pass


def _start_event_cache():
    """On boot: build the cache in the background, then keep it fresh every 24h."""
    threading.Thread(target=_refresh_events_cache, daemon=True).start()
    # if Supabase is already configured, make sure the default presets are seeded
    threading.Thread(target=presets_mod.seed_defaults, daemon=True).start()

    def _tick():
        _refresh_events_cache()
        t = threading.Timer(event_cache.MAX_AGE_HOURS * 3600, _tick)
        t.daemon = True
        t.start()

    t = threading.Timer(event_cache.MAX_AGE_HOURS * 3600, _tick)
    t.daemon = True
    t.start()


def main():
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    _start_event_cache()
    threading.Timer(1.0, lambda: _open_browser(url)).start()
    print(f"\n  Edge Finder running at {url}")
    print("  (a browser tab should open automatically — Ctrl+C to stop)\n")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
