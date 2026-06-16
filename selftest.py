"""Offline smoke test: exercises scoring + display with a synthetic matchup.
No network / API key needed.  Run:  python selftest.py
"""
import config_manager as cfgmod
import scoring_engine
import display as ui


def fake_data():
    def r(score, detail):
        return {"score": score, "available": True, "detail": detail, "source": "TEST"}

    def na(reason):
        return {"score": None, "available": False, "detail": reason, "source": "—"}

    return {
        "recent_form":      {"a": r(72, "8-2 L10, streak 3W"), "b": r(48, "5-5 L10, streak 1L")},
        "injuries":         {"a": r(92, "1 listed"),           "b": r(68, "4 listed")},
        "head_to_head":     {"a": na("no archive"),            "b": na("no archive")},
        "travel_fatigue":   {"a": r(60, "home (rested)"),      "b": r(42, "away (travel)")},
        "line_movement":    {"a": na("needs history"),         "b": na("needs history")},
        "social_sentiment": {"a": na("no free api"),           "b": na("no free api")},
    }


def main():
    cfg = cfgmod.load_config()
    matchup = {
        "sport": "Basketball", "league": "NBA (test)", "bookmaker_count": 6,
        "commence_time": "2026-06-05T00:00:00Z",
        "home_team": "Boston Celtics", "away_team": "Miami Heat",
        "a": {"name": "Boston Celtics", "odds": -110},
        "b": {"name": "Miami Heat", "odds": -110},
    }
    data = fake_data()
    report = scoring_engine.build_report("Basketball", matchup, data, cfg)
    ui.banner()
    ui.render_report(report)

    # sanity assertions
    assert abs(report["implied"]["a"] + report["implied"]["b"] - 1.0) < 1e-9, "devig broken"
    assert abs(report["model"]["a"] + report["model"]["b"] - 1.0) < 1e-9, "model not normalized"
    assert report["recommendation"]["name"] == "Boston Celtics", "expected edge on stronger side"
    ui.success("Self-test passed: probabilities normalized, edge on the stronger side.")


if __name__ == "__main__":
    main()
