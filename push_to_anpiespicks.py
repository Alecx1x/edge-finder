#!/usr/bin/env python3
"""
Bridge: push Edge Finder's logged bets into the AnpiesPicks public track record.

Reads bets_log.json and POSTs each bet to AnpiesPicks' /api/picks/ingest.
AnpiesPicks dedupes by (source='edge-finder', ext_id=<bet id>), so running this
repeatedly is safe — new bets are added, and result/status changes update the
existing row (e.g. once you settle a bet to win/loss in the Edge Finder).

Usage:
    # one-off
    python push_to_anpiespicks.py

    # set the token once so you don't paste it each time:
    #   Windows PowerShell:  $env:ANPIESPICKS_TOKEN="VPoGTn3ayxA7a7hq"
    #   macOS/Linux:         export ANPIESPICKS_TOKEN=VPoGTn3ayxA7a7hq
    python push_to_anpiespicks.py

    # or point at a different log / base url
    python push_to_anpiespicks.py --log bets_log.json --url https://join.anpieo7.workers.dev
"""
import argparse
import json
import os
import sys

import requests

DEFAULT_URL = "https://join.anpieo7.workers.dev"
DEFAULT_LOG = "bets_log.json"
# Your AnpiesPicks ingest token (same one the phone updater uses). Prefer the env var.
DEFAULT_TOKEN = "VPoGTn3ayxA7a7hq"


def load_bets(path):
    if not os.path.exists(path):
        sys.exit(f"No bet log found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def unit_size(cli_unit):
    """Resolve $ value of 1 unit. Priority: --unit > $ANPIESPICKS_UNIT > 1% of
    bankroll in config.json > $10 fallback."""
    if cli_unit:
        return float(cli_unit)
    env = os.environ.get("ANPIESPICKS_UNIT")
    if env:
        return float(env)
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            bankroll = float(json.load(f).get("bankroll", 0))
        if bankroll > 0:
            return round(bankroll * 0.01, 2)  # 1 unit = 1% of bankroll
    except (OSError, ValueError):
        pass
    return 10.0


def to_units(bets, unit):
    """Edge Finder logs `stake` in DOLLARS; AnpiesPicks shows `stake` as UNITS.
    Convert a copy so the public record reads cleanly (e.g. $63 @ $10/u -> 6.3u)."""
    out = []
    for b in bets:
        b = dict(b)
        if unit > 0 and b.get("stake") is not None:
            try:
                b["stake"] = round(float(b["stake"]) / unit, 2) or 1
            except (TypeError, ValueError):
                b["stake"] = 1
        out.append(b)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("ANPIESPICKS_URL", DEFAULT_URL))
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--token", default=os.environ.get("ANPIESPICKS_TOKEN", DEFAULT_TOKEN))
    ap.add_argument("--unit", default=None, help="$ value of 1 unit (default: 1%% of bankroll from config.json)")
    args = ap.parse_args()

    bets = load_bets(args.log)
    if not bets:
        print("Bet log is empty — nothing to push.")
        return

    unit = unit_size(args.unit)
    bets = to_units(bets, unit)
    print(f"Using 1 unit = ${unit:.2f} (override with --unit or $ANPIESPICKS_UNIT).")

    # AnpiesPicks maps the edge-finder shape itself
    # (name_a/name_b -> event, bet_name -> selection, bet_odds -> odds, result -> status, id -> ext_id).
    endpoint = args.url.rstrip("/") + "/api/picks/ingest"
    try:
        resp = requests.post(endpoint, json={"token": args.token, "picks": bets}, timeout=20)
    except requests.RequestException as e:
        sys.exit(f"Request failed: {e}")

    if resp.status_code == 401:
        sys.exit("Rejected: bad token. Set ANPIESPICKS_TOKEN to your AnpiesPicks token.")
    try:
        out = resp.json()
    except ValueError:
        sys.exit(f"Unexpected response ({resp.status_code}): {resp.text[:200]}")

    if not out.get("ok"):
        sys.exit(f"Server error: {out.get('error', resp.text[:200])}")

    print(
        f"Pushed {len(bets)} bet(s) -> AnpiesPicks: "
        f"{out.get('added', 0)} added, {out.get('updated', 0)} updated, {out.get('skipped', 0)} skipped."
    )
    print(f"View them at {args.url.rstrip('/')}/record")


if __name__ == "__main__":
    main()
