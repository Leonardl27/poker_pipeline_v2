"""
Dashboard verification script for CI/CD pipeline.

Builds the dashboard and validates correctness:
- HTML structure completeness
- Stat sanity checks (0-100% ranges, VPIP >= PFR, etc.)
- Chart presence
- No error indicators

Usage:
    python verify_dashboard.py [output_dir]

Exit codes:
    0 = all checks passed
    1 = one or more checks failed
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

from generate_dashboard import (
    run_pipeline, generate_chart_base64, get_table_data, build_html,
    DB_PATH, MIN_GAMES,
)

EXPECTED_CHARTS = [
    "player_statistics.png",
    "hand_analysis.png",
    "session_trends.png",
    "momentum.png",
    "stat_correlations.png",
    "profit_drivers.png",
    "pipeline_diagram.png",
    "cicd_diagram.png",
]


def verify(output_dir: str = "_site") -> tuple[list[str], list[str]]:
    """Run full pipeline and validate the built dashboard.

    Returns (errors, warnings) lists.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    warnings: list[str] = []

    # ── Step 1: Run pipeline ──────────────────────────────────────────
    print("[1/5] Running pipeline...")
    try:
        summary = run_pipeline(DB_PATH)
        print(f"      Ingested {summary['files_ingested']} files, "
              f"{summary['total_hands']} hands, {summary['total_players']} players")
    except Exception as e:
        errors.append(f"Pipeline failed: {e}")
        return errors, warnings

    # ── Step 2: Generate charts ───────────────────────────────────────
    print("[2/5] Generating charts...")
    try:
        charts = generate_chart_base64(DB_PATH, output_dir)
    except Exception as e:
        errors.append(f"Chart generation failed: {e}")
        return errors, warnings

    for chart in EXPECTED_CHARTS:
        if chart not in charts:
            errors.append(f"Missing chart: {chart}")
    print(f"      Generated {len(charts)}/{len(EXPECTED_CHARTS)} charts")

    # ── Step 3: Get table data ────────────────────────────────────────
    print("[3/5] Building table data...")
    try:
        table_data = get_table_data(DB_PATH)
    except Exception as e:
        errors.append(f"Table data generation failed: {e}")
        return errors, warnings

    if len(table_data) == 0:
        errors.append("No players in leaderboard (table_data is empty)")
    else:
        print(f"      {len(table_data)} players in leaderboard")

    # ── Step 4: Stat sanity checks ────────────────────────────────────
    print("[4/5] Validating stats...")
    for row in table_data:
        name = row["name"]
        # Percentage range checks (non-nullable)
        for field in ["win_rate", "vpip_pct", "conv_vpip_pct", "pfr_pct", "flop_seen_pct"]:
            val = row.get(field, 0)
            if val is not None and (val < 0 or val > 100):
                errors.append(f"{name}: {field}={val} out of range [0, 100]")

        # Nullable percentage checks
        for field in ["ats_pct", "bb_defend_pct", "bb_fold_to_steal_pct", "three_bet_pct",
                      "wtsd_pct", "wsd_pct", "cbet_pct", "fold_to_cbet_pct"]:
            val = row.get(field)
            if val is not None and (val < 0 or val > 100):
                errors.append(f"{name}: {field}={val} out of range [0, 100]")

        # Aggression Factor is a ratio (not percentage) — reasonable range [0, 20]
        af = row.get("aggression_factor")
        if af is not None and (af < 0 or af > 20):
            errors.append(f"{name}: aggression_factor={af} out of range [0, 20]")

        # Logical constraint: conventional VPIP should be >= PFR
        if row["conv_vpip_pct"] + 0.1 < row["pfr_pct"]:
            warnings.append(
                f"{name}: VPIP ({row['conv_vpip_pct']}%) < PFR ({row['pfr_pct']}%)"
            )

    # ── Step 5: Build and validate HTML ───────────────────────────────
    print("[5/5] Building and validating HTML...")
    try:
        html = build_html(summary, charts, table_data)
    except Exception as e:
        errors.append(f"HTML build failed: {e}")
        return errors, warnings

    # Check for key sections
    for section_name in ["Player Leaderboard", "Player Profiles", "Scouting Report"]:
        if section_name not in html:
            errors.append(f"Missing '{section_name}' section in HTML")

    if "data:image/png;base64," not in html:
        errors.append("No embedded chart images found in HTML")

    # Check for NaN in HTML text (exclude base64 image data)
    import re
    html_no_base64 = re.sub(r'data:image/png;base64,[A-Za-z0-9+/=]+', '', html)
    if "NaN" in html_no_base64:
        errors.append("Found 'NaN' in HTML output")

    # Check scouting reports: one per player, each with 2-4 bullets
    scouting_count = html_no_base64.count('class="scouting-report"')
    if scouting_count != len(table_data):
        errors.append(
            f"Expected {len(table_data)} scouting reports, found {scouting_count}"
        )
    bullet_lists = re.findall(
        r'<ul class="scouting-bullets">(.*?)</ul>', html_no_base64, re.DOTALL
    )
    for i, bl in enumerate(bullet_lists):
        bullet_count = bl.count("<li>")
        if bullet_count < 2 or bullet_count > 4:
            warnings.append(
                f"Scouting report #{i+1} has {bullet_count} bullets (expected 2-4)"
            )

    # Write the HTML
    output_path = Path(output_dir) / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = output_path.stat().st_size / 1024
    print(f"      Dashboard written: {output_path} ({size_kb:.1f} KB)")

    return errors, warnings


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "_site"

    print("=" * 50)
    print("DASHBOARD VERIFICATION")
    print("=" * 50)

    errors, warnings = verify(output_dir)

    print()
    for w in warnings:
        print(f"  WARNING: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if errors:
        print(f"\nVERIFICATION FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    else:
        print(f"\nVERIFICATION PASSED: {len(warnings)} warning(s)")
        sys.exit(0)


if __name__ == "__main__":
    main()
