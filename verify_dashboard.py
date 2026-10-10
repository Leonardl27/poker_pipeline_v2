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
    get_activity, get_past_players, slugify, DB_PATH, MIN_GAMES, ACTIVE_WINDOW_DAYS,
    HIDE_LOSSES_OVER,
)
from visualize import get_latest_session_summary, get_session_records
from starting_hands import FULL_FOLD_COVERAGE
from chart_data import build_chart_data

# Only the architecture diagrams are pre-rendered PNGs; data charts are
# interactive inline SVG rendered client-side from CHART_DATA.
EXPECTED_CHARTS = [
    "pipeline_diagram.png",
    "cicd_diagram.png",
]

EXPECTED_CHART_DIVS = [
    "chart-archetypes",
    "chart-hand-analysis",
    "chart-session-trends",
    "chart-momentum",
    "chart-correlations",
    "chart-profit-drivers",
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
        activity_info = get_activity(DB_PATH)
        active_names = activity_info["active_names"]
        private_names = activity_info["private_names"]
        past_players = get_past_players(activity_info)
        print(f"      {len(active_names)} active in last {ACTIVE_WINDOW_DAYS} days, "
              f"{len(past_players)} past players")
    except Exception as e:
        errors.append(f"Pipeline failed: {e}")
        return errors, warnings

    # History must be kept: every player in the DB is either active or past
    if len(active_names) + len(past_players) != len(activity_info["activity"]):
        errors.append("Activity split lost players (active + past != all players)")

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
        table_data = get_table_data(DB_PATH, active_names)
    except Exception as e:
        errors.append(f"Table data generation failed: {e}")
        return errors, warnings

    if len(table_data) == 0:
        errors.append("No players in leaderboard (table_data is empty)")
    else:
        print(f"      {len(table_data)} players in leaderboard")

    # Activity filter: nobody outside the window may appear on the leaderboard
    cutoff_ms = activity_info["cutoff_ms"]
    for row in table_data:
        if row["name"] not in active_names or (row.get("last_played_ms") or 0) < cutoff_ms:
            errors.append(f"{row['name']}: on leaderboard but inactive for "
                          f"more than {ACTIVE_WINDOW_DAYS} days")

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
        latest_session = get_latest_session_summary(DB_PATH)
        chart_data = build_chart_data(DB_PATH, min_games=MIN_GAMES,
                                      active_names=active_names,
                                      private_names=private_names)
        records = get_session_records(DB_PATH, active_names,
                                      exclude_names=private_names)
        html = build_html(summary, charts, table_data, latest_session, chart_data,
                          past_players=past_players, records=records,
                          now_ms=activity_info["now_ms"],
                          private_names=private_names)
    except Exception as e:
        errors.append(f"HTML build failed: {e}")
        return errors, warnings

    # Interactive chart checks: payload + container divs + renderer present
    if "window.CHART_DATA" not in html:
        errors.append("CHART_DATA payload missing from HTML")
    for div_id in EXPECTED_CHART_DIVS:
        if f'id="{div_id}"' not in html:
            errors.append(f"Missing interactive chart container: {div_id}")
    if "renderArchetypes" not in html:
        errors.append("Chart renderer JS (static/charts.js) missing from HTML")

    # Charts must only feature active players
    chart_names = set()
    chart_names.update(p["name"] for p in chart_data["archetypes"]["players"])
    chart_names.update(chart_data["session_trends"]["names"])
    chart_names.update(p["name"] for p in chart_data["momentum"]["players"])
    for name in sorted(chart_names - active_names):
        errors.append(f"Inactive player '{name}' appears in chart data")

    # Check for key sections
    sections = ["Latest Session", "Player Leaderboard", "Player Profiles",
                "Scouting Report"]
    if past_players:
        sections.append("Past Players")
    for section_name in sections:
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

    # Improvement advice: one "How to improve" block per player, each with
    # at most 3 leak cards (or the no-leaks message) and a "Try this" per leak
    coaching_blocks = re.findall(
        r'<div class="coaching">(.*?)<h4 class="breakdown-title">',
        html_no_base64, re.DOTALL,
    )
    if len(coaching_blocks) != len(table_data):
        errors.append(
            f"Expected {len(table_data)} 'How to improve' sections, found {len(coaching_blocks)}"
        )
    for i, block in enumerate(coaching_blocks):
        leaks = block.count('<article class="leak">')
        if leaks > 3:
            errors.append(f"'How to improve' #{i+1} has {leaks} leaks (max 3)")
        if leaks == 0 and 'class="leak-none"' not in block:
            errors.append(f"'How to improve' #{i+1} is empty")
        if block.count("Try this:") != leaks:
            errors.append(f"'How to improve' #{i+1}: every leak needs a 'Try this' tip")

    # Starting hands panel: one per profile, each a full 13x13 grid, and the
    # play-vs-fold view only where most folds are actually visible
    panels = re.findall(r'<div class="hands-panel" data-mode="(\w+)">(.*?)<h4 class="breakdown-title">',
                        html_no_base64, re.DOTALL)
    if len(panels) != len(table_data):
        errors.append(f"Expected {len(table_data)} starting-hands panels, found {len(panels)}")
    for i, (mode, body) in enumerate(panels):
        cells = len(re.findall(r'<span class="hc[ "]', body))
        if cells != 169:
            errors.append(f"Starting-hands grid #{i+1} has {cells} cells (expected 169)")
        m = re.search(r'Folds we can see</span>.*?<span>(\d+)%</span>', body, re.DOTALL)
        if mode == "full" and m and int(m.group(1)) < FULL_FOLD_COVERAGE * 100:
            errors.append(f"Starting-hands grid #{i+1} uses fold data with only {m.group(1)}% folds visible")

    # Hidden amounts: players who lost more than HIDE_LOSSES_OVER must have
    # no dollar figure anywhere (rendered text, chart payload or page source)
    errors.extend(check_private_amounts(
        html_no_base64, chart_data, table_data, latest_session, records,
        private_names, activity_info["activity"]))

    # Write the HTML
    output_path = Path(output_dir) / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = output_path.stat().st_size / 1024
    print(f"      Dashboard written: {output_path} ({size_kb:.1f} KB)")

    return errors, warnings


def check_private_amounts(html, chart_data, table_data, latest_session,
                          records, private_names, activity) -> list:
    """Return errors if any hidden player's dollar amount can be seen."""
    import re
    errs = []
    if not private_names:
        return errs
    print(f"      Amounts hidden for {len(private_names)} player(s) "
          f"(lifetime loss > ${HIDE_LOSSES_OVER})")

    # 1. Their lifetime and per-hand numbers never appear in the page
    #    (stylesheet excluded; match standalone numbers, not e.g. "1.02rem")
    page = re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)
    rows = {r["name"]: r for r in table_data}
    for name in private_names:
        # Lifetime total: distinctive (> HIDE_LOSSES_OVER), match bare number
        v = abs(activity[name]["profit"])
        patterns = [f"{v:.2f}", f"{v:,.2f}"]
        # Per-hand average: small numbers collide with other stats, so only
        # match the signed/dollar form it would be displayed in
        if name in rows:
            a = rows[name]["avg_profit"]
            patterns += [f"{a:+.2f}", f"-${abs(a):.2f}"]
        for txt in set(patterns):
            if re.search(rf"(?<![\d.,]){re.escape(txt)}(?![\d%a-z])", page):
                errs.append(f"Hidden amount for {name} ({txt}) found in HTML")

    # 2. Leaderboard row and profile header contain no $ or signed amounts
    for name in private_names & set(rows):
        slug = slugify(name)
        m = re.search(rf'<tr[^>]*data-slug="{slug}".*?</tr>', html, re.DOTALL)
        if m and re.search(r'\$|[+-]\d+\.\d\d<', m.group(0)):
            errs.append(f"Leaderboard row for {name} shows a dollar amount")
        m = re.search(rf'id="profile-btn-{slug}".*?</button>', html, re.DOTALL)
        if m and "$" in m.group(0):
            errs.append(f"Profile header for {name} shows a dollar amount")

    # 3. Chart payload: no profit values for hidden players
    for p in chart_data["archetypes"]["players"]:
        if p["name"] in private_names and p["profit"] is not None:
            errs.append(f"Archetype chart exposes profit for {p['name']}")
    st = chart_data["session_trends"]
    for f in st["featured"]:
        if f["name"] in private_names:
            errs.append(f"Session trend line features {f['name']}")
    for name, row in zip(st["names"], st["matrix"]):
        if name in private_names and any(isinstance(v, (int, float)) for v in row):
            errs.append(f"Session heatmap exposes amounts for {name}")
    for p in chart_data["momentum"]["players"]:
        if p["name"] in private_names:
            errs.append(f"Momentum chart includes {p['name']}")
    for panel in (chart_data.get("profit_drivers") or {}).get("panels", []):
        for pt in panel["points"]:
            if pt["name"] in private_names:
                errs.append(f"Profit drivers chart plots {pt['name']}")

    # 4. Latest session seat and records
    if latest_session:
        for p in latest_session["players"]:
            if p["name"] in private_names:
                m = re.search(rf'<span class="seat-name">{re.escape(p["name"])}</span>(.*?)</button>',
                              html, re.DOTALL)
                if m and "$" in m.group(1):
                    errs.append(f"Latest-session seat shows an amount for {p['name']}")
    for key in ("best_night", "worst_night", "hot_streak"):
        rec = (records or {}).get(key)
        if rec and rec.get("name") in private_names:
            errs.append(f"Record '{key}' names {rec['name']}")
    return errs


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
