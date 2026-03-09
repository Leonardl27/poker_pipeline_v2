#!/usr/bin/env python3
"""
Verify HUD stats against pokernow.club reference values.

Usage:
    python verify_stats.py

Rebuilds the DB from scratch, calculates VPIP/PFR/ATS for the
March 6th session, and compares against known-good pokernow values.
"""
import json
from pathlib import Path

from database import get_connection
from ingest import ingest_directory
from mappings import load_mappings
from hud_stats import calculate_hud_stats

DB_PATH = "poker.db"
RAW_DIR = "raw"
MAPPING_FILE = "player_map.yaml"
GAME_ID = "pgluwioakfJ9_g1SApRa3xLF0"  # March 6th session
JSON_FILE = "raw/replay-pgluwioakfJ9_g1SApRa3xLF0.json"

# Reference values from pokernow.club screenshot (keyed by player_id)
# player_id -> {pokernow_name, hands, vpip, pfr, ats, net (cents)}
REFERENCE = {
    "3FpdwMZeVV": {"name": "kojo",       "hands": 133, "vpip": 66.2, "pfr": 3.0,  "ats": 5.9,  "net": 24446},
    "4HiZJGv1Zm": {"name": "Kevbot420",  "hands": 134, "vpip": 61.2, "pfr": 1.5,  "ats": 0.0,  "net": 23554},
    "IxqhiMgj9P": {"name": "Roscoe",     "hands": 133, "vpip": 54.9, "pfr": 3.0,  "ats": 0.0,  "net": -4000},
    "oJNWU-jnlA": {"name": "SMOKEY",     "hands": 76,  "vpip": 84.2, "pfr": 1.3,  "ats": 0.0,  "net": -4000},
    "a84xgZZ7Yr": {"name": "Steel",      "hands": 52,  "vpip": 26.9, "pfr": 9.6,  "ats": None, "net": -4000},
    "7cDe6-4038": {"name": "Blind Dan",  "hands": 22,  "vpip": 54.5, "pfr": 13.6, "ats": None, "net": -4000},
    "mrmMdPuwc-": {"name": "Lenny",      "hands": 105, "vpip": 46.7, "pfr": 10.5, "ats": 50.0, "net": -8000},
    "KsECv73vsi": {"name": "eric",       "hands": 96,  "vpip": 56.3, "pfr": 3.1,  "ats": 0.0,  "net": -8000},
    "VJU-hGD3L_": {"name": "BlitzRyan",  "hands": 64,  "vpip": 53.1, "pfr": 4.7,  "ats": None, "net": -8000},
    "XddyijEojw": {"name": "MastaChief", "hands": 36,  "vpip": 69.4, "pfr": 11.1, "ats": None, "net": -8000},
}

TOLERANCE = 0.5  # percentage points


def rebuild_db():
    """Rebuild database from scratch."""
    db_file = Path(DB_PATH)
    if db_file.exists():
        db_file.unlink()
    ingest_directory(RAW_DIR, DB_PATH)
    load_mappings(MAPPING_FILE, DB_PATH)


def main():
    print("Rebuilding database...")
    rebuild_db()

    print(f"Calculating HUD stats for game {GAME_ID}...\n")
    results = calculate_hud_stats(DB_PATH, game_id=GAME_ID, use_raw_names=True)

    # Index by player_id
    calc = {r["player_id"]: r for r in results}

    # Header
    hdr = (f"{'Name':<12} {'Hands':>5} {'VPIP%':>6} {'(exp)':>7} "
           f"{'PFR%':>6} {'(exp)':>7} {'ATS%':>6} {'(exp)':>7} "
           f"{'Net c':>8} {'(exp)':>8}  {'Status'}")
    print(hdr)
    print("-" * len(hdr))

    all_pass = True
    for pid, ref in REFERENCE.items():
        name = ref["name"]
        c = calc.get(pid)
        if c is None:
            print(f"{name:<12}  *** NOT FOUND IN RESULTS (pid={pid}) ***")
            all_pass = False
            continue

        # Compare values
        issues = []
        if c["hands"] != ref["hands"]:
            issues.append(f"hands {c['hands']}!={ref['hands']}")

        vpip_diff = abs(c["vpip_pct"] - ref["vpip"])
        if vpip_diff > TOLERANCE:
            issues.append(f"vpip d{vpip_diff:.1f}")

        pfr_diff = abs(c["pfr_pct"] - ref["pfr"])
        if pfr_diff > TOLERANCE:
            issues.append(f"pfr d{pfr_diff:.1f}")

        if ref["ats"] is not None and c["ats_pct"] is not None:
            ats_diff = abs(c["ats_pct"] - ref["ats"])
            if ats_diff > TOLERANCE:
                issues.append(f"ats d{ats_diff:.1f}")
        elif ref["ats"] is None and c["ats_pct"] is not None:
            issues.append(f"ats should be - (got {c['ats_pct']:.1f}%)")
        elif ref["ats"] is not None and c["ats_pct"] is None:
            issues.append(f"ats should be {ref['ats']}%")

        net_calc = round(c["net_profit"] * 100)
        if net_calc != ref["net"]:
            issues.append(f"net {net_calc}!={ref['net']}")

        status = "PASS" if not issues else f"FAIL: {', '.join(issues)}"
        if issues:
            all_pass = False

        ats_str = f"{c['ats_pct']:5.1f}%" if c["ats_pct"] is not None else "    -"
        ref_ats = f"{ref['ats']:5.1f}%" if ref["ats"] is not None else "    -"

        print(f"{name:<12} {c['hands']:>5} {c['vpip_pct']:>5.1f}% ({ref['vpip']:>5.1f}%) "
              f"{c['pfr_pct']:>5.1f}% ({ref['pfr']:>5.1f}%) "
              f"{ats_str} ({ref_ats}) "
              f"{c['net_profit']*100:>8.0f} ({ref['net']:>8})  {status}")

    print()
    # Show any players in results but NOT in reference
    for r in results:
        if r["player_id"] not in REFERENCE:
            print(f"  (extra player: pid={r['player_id']}, "
                  f"db_name={r['name']}, hands={r['hands']})")

    print()
    if all_pass:
        print("ALL STATS MATCH POKERNOW REFERENCE!")
    else:
        print("Some values differ -- see above for details.")


if __name__ == "__main__":
    main()
