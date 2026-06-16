"""Edge calculation.

Pipeline:
  market odds  -> implied prob -> de-vig -> fair market prob
  per-variable scores (0-100) * weights -> signal composite -> signal prob
  model prob = blend(market, signal) weighted by how much real data we have
  edge = model prob - market prob
  -> confidence tier + driving variables
"""
from config_manager import variables_for_sport


def american_to_prob(odds):
    odds = float(odds)
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def devig(pa, pb):
    total = pa + pb
    if total <= 0:
        return 0.5, 0.5
    return pa / total, pb / total


def confidence_tier(edge, availability):
    e = abs(edge)
    if availability < 0.15 or e < 0.02:
        return "Low"
    if e < 0.05:
        return "Medium" if availability >= 0.4 else "Low"
    if e < 0.09:
        return "High" if availability >= 0.5 else "Medium"
    return "Strong" if availability >= 0.6 else "High"


def build_report(sport, matchup, data, cfg):
    a, b = matchup["a"], matchup["b"]
    raw_a, raw_b = american_to_prob(a["odds"]), american_to_prob(b["odds"])
    imp_a, imp_b = devig(raw_a, raw_b)

    weights = cfg["weights"]
    variables = variables_for_sport(sport)

    rows = []
    sig_a = sig_b = w_avail = total_w = 0.0
    for v in variables:
        key = v["key"]
        w = float(weights.get(key, 1.0))
        total_w += w
        res = data.get(key, {})
        ra, rb = res.get("a") or {}, res.get("b") or {}
        avail = bool(ra.get("available") and rb.get("available")
                     and ra.get("score") is not None and rb.get("score") is not None)
        if avail and w > 0:
            sig_a += w * ra["score"]
            sig_b += w * rb["score"]
            w_avail += w
        rows.append({
            "key": key, "label": v["label"], "weight": w, "available": avail,
            "score_a": ra.get("score"), "score_b": rb.get("score"),
            "detail_a": ra.get("detail", ""), "detail_b": rb.get("detail", ""),
            "source": ra.get("source", ""),
        })

    if w_avail > 0 and (sig_a + sig_b) > 0:
        signal_prob_a = sig_a / (sig_a + sig_b)
    else:
        signal_prob_a = imp_a  # no real data -> don't move off the market

    availability = (w_avail / total_w) if total_w > 0 else 0.0
    model_a = (1 - availability) * imp_a + availability * signal_prob_a
    model_b = 1 - model_a

    edge_a, edge_b = model_a - imp_a, model_b - imp_b
    if edge_a >= edge_b:
        rec = {"side": "a", "name": a["name"], "edge": edge_a}
    else:
        rec = {"side": "b", "name": b["name"], "edge": edge_b}
    rec["tier"] = confidence_tier(rec["edge"], availability)
    rec["bet"] = rec["edge"] >= 0.02

    drivers = []
    for r in rows:
        if not r["available"]:
            continue
        contrib = r["weight"] * (r["score_a"] - r["score_b"])
        favors = a["name"] if contrib >= 0 else b["name"]
        drivers.append({"label": r["label"], "mag": abs(contrib), "favors": favors})
    drivers.sort(key=lambda d: d["mag"], reverse=True)

    return {
        "sport": sport, "matchup": matchup,
        "implied": {"a": imp_a, "b": imp_b},
        "model": {"a": model_a, "b": model_b},
        "signal_prob_a": signal_prob_a,
        "edge": {"a": edge_a, "b": edge_b},
        "availability": availability,
        "rows": rows,
        "recommendation": rec,
        "drivers": drivers[:3],
    }
