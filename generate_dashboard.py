"""
Dashboard generator for poker analytics.
Runs the full pipeline and produces a self-contained index.html for GitHub Pages.

Usage:
    python generate_dashboard.py [output_dir]
    python generate_dashboard.py _site
"""
import matplotlib
matplotlib.use('Agg')  # Must be set before any other matplotlib imports

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

from database import get_connection
from ingest import ingest_directory
from mappings import load_mappings
from visualize import get_player_statistics, generate_all_visualizations
from hud_stats import calculate_hud_stats
from scouting import generate_scouting_report

DB_PATH = "poker.db"
RAW_DIR = "raw"
MAPPING_FILE = "player_map.yaml"
OUTPUT_DIR = "_site"
MIN_GAMES = 3  # Only show players who have played in at least this many sessions


def run_pipeline(db_path: str = DB_PATH) -> dict:
    """Execute the full data pipeline and return summary statistics."""
    # Remove stale DB (rebuild from scratch)
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()

    # Ingest all JSON from raw/
    ingest_results = ingest_directory(RAW_DIR, db_path)

    # Load player identity mappings
    load_mappings(MAPPING_FILE, db_path)

    # Gather summary counts
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total_games = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM hands")
    total_hands = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM canonical_players")
    total_players = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]

    conn.close()

    return {
        "files_ingested": len(ingest_results),
        "total_games": total_games,
        "total_hands": total_hands,
        "total_players": total_players,
        "total_events": total_events,
    }


def generate_chart_base64(db_path: str, output_dir: str) -> dict:
    """Generate all charts and return them as base64-encoded strings."""
    generate_all_visualizations(db_path, output_dir, min_games=MIN_GAMES)

    charts = {}
    for chart_name in ["player_statistics.png", "hand_analysis.png", "session_trends.png",
                       "momentum.png", "stat_correlations.png", "profit_drivers.png",
                       "pipeline_diagram.png"]:
        chart_path = Path(output_dir) / chart_name
        if chart_path.exists():
            with open(chart_path, "rb") as f:
                charts[chart_name] = base64.b64encode(f.read()).decode("utf-8")

    return charts


def get_table_data(db_path: str) -> list:
    """Get player statistics formatted for the HTML leaderboard table."""
    stats = get_player_statistics(db_path, use_enriched=True, min_games=MIN_GAMES)

    # Get aggregate HUD stats (VPIP/PFR/ATS across all sessions)
    hud = calculate_hud_stats(db_path)
    hud_by_name = {h["name"]: h for h in hud}

    rows = []
    for row in stats:
        hands_played = row["hands_played"]
        hands_won = row["hands_won"] or 0
        total_profit = row["total_profit"] or 0
        avg_profit = row["avg_profit_per_hand"] or 0
        win_rate = (hands_won / hands_played * 100) if hands_played > 0 else 0

        # Merge HUD stats for this player
        h = hud_by_name.get(row["name"], {})

        rows.append({
            "name": row["name"],
            "games_played": row["games_played"],
            "hands_played": hands_played,
            "hands_won": hands_won,
            "win_rate": round(win_rate, 1),
            "total_profit": round(total_profit, 2),
            "avg_profit": round(avg_profit, 2),
            "showdowns": row["showdowns"] or 0,
            "vpip_pct": round(h.get("vpip_pct", 0), 1),
            "conv_vpip_pct": round(h.get("conv_vpip_pct", 0), 1),
            "pfr_pct": round(h.get("pfr_pct", 0), 1),
            "ats_pct": h.get("ats_pct"),
            # New profile stats
            "flop_seen_pct": round(h.get("flop_seen_pct", 0), 1),
            "bb_defend_pct": (round(h["bb_defend_pct"], 1)
                              if h.get("bb_defend_pct") is not None else None),
            "bb_fold_to_steal_pct": (round(h["bb_fold_to_steal_pct"], 1)
                                     if h.get("bb_fold_to_steal_pct") is not None else None),
            "three_bet_pct": (round(h["three_bet_pct"], 1)
                              if h.get("three_bet_pct") is not None else None),
            # Post-flop & showdown stats
            "wtsd_pct": (round(h["wtsd_pct"], 1)
                         if h.get("wtsd_pct") is not None else None),
            "wsd_pct": (round(h["wsd_pct"], 1)
                        if h.get("wsd_pct") is not None else None),
            "aggression_factor": (round(h["aggression_factor"], 1)
                                  if h.get("aggression_factor") is not None else None),
            "cbet_pct": (round(h["cbet_pct"], 1)
                         if h.get("cbet_pct") is not None else None),
            "fold_to_cbet_pct": (round(h["fold_to_cbet_pct"], 1)
                                 if h.get("fold_to_cbet_pct") is not None else None),
        })
    return rows


def _stat_bar_color(stat_name: str, value: float) -> str:
    """Return a CSS color for a stat bar based on poker stat ranges."""
    ranges = {
        "vpip":     [(25, "#5b9bd5"), (40, "#4caf50"), (100, "#e94560")],
        "pfr":      [(10, "#5b9bd5"), (20, "#4caf50"), (100, "#e94560")],
        "three_bet":[(5,  "#5b9bd5"), (10, "#4caf50"), (100, "#e94560")],
        "flop_seen":[(40, "#5b9bd5"), (60, "#4caf50"), (100, "#e94560")],
        "bb_defend":[(40, "#e94560"), (60, "#4caf50"), (100, "#5b9bd5")],
        "bb_fold":  [(30, "#4caf50"), (50, "#e9a945"), (100, "#e94560")],
        "ats":      [(25, "#5b9bd5"), (40, "#4caf50"), (100, "#e94560")],
        "wtsd":     [(20, "#5b9bd5"), (35, "#4caf50"), (100, "#e94560")],
        "wsd":      [(45, "#e94560"), (55, "#4caf50"), (100, "#5b9bd5")],
        "cbet":     [(50, "#5b9bd5"), (70, "#4caf50"), (100, "#e94560")],
        "fold_cbet":[(40, "#4caf50"), (55, "#e9a945"), (100, "#e94560")],
    }
    thresholds = ranges.get(stat_name, [(100, "#4caf50")])
    for limit, color in thresholds:
        if value <= limit:
            return color
    return thresholds[-1][1]


def build_player_profiles_html(table_data: list) -> str:
    """Generate collapsible player profile cards."""
    profiles = ""
    for row in table_data:
        name = row["name"]
        slug = name.lower().replace(" ", "-").replace("'", "")
        profit = row["total_profit"]
        profit_class = "positive" if profit >= 0 else "negative"
        profit_display = f"+${profit:.2f}" if profit > 0 else f"-${abs(profit):.2f}" if profit < 0 else "$0.00"

        # Build stat rows for each category
        def stat_row(label, value, stat_key, suffix="%"):
            if value is None:
                return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:0%;"></div></div>
                        <span class="stat-value stat-na">--</span>
                    </div>'''
            color = _stat_bar_color(stat_key, value)
            width = min(value, 100)
            return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:{width}%; background:{color};"></div></div>
                        <span class="stat-value">{value:.1f}{suffix}</span>
                    </div>'''

        preflop_stats = (
            stat_row("VPIP%", row["conv_vpip_pct"], "vpip")
            + stat_row("PFR%", row["pfr_pct"], "pfr")
            + stat_row("3-Bet%", row["three_bet_pct"], "three_bet")
            + stat_row("Flop Seen%", row["flop_seen_pct"], "flop_seen")
        )

        bb_stats = (
            stat_row("BB Defense%", row["bb_defend_pct"], "bb_defend")
            + stat_row("BB Fold to Steal%", row["bb_fold_to_steal_pct"], "bb_fold")
        )

        steal_stats = stat_row("ATS%", row["ats_pct"], "ats")

        # AF is a ratio (not percentage) — needs special rendering
        def ratio_row(label, value, max_scale=5.0):
            if value is None:
                return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:0%;"></div></div>
                        <span class="stat-value stat-na">--</span>
                    </div>'''
            width = min(value / max_scale * 100, 100)
            color = "#5b9bd5" if value < 1.5 else "#4caf50" if value < 3.5 else "#e94560"
            return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:{width}%; background:{color};"></div></div>
                        <span class="stat-value">{value:.1f}</span>
                    </div>'''

        postflop_stats = (
            stat_row("C-Bet%", row["cbet_pct"], "cbet")
            + stat_row("Fold to C-Bet%", row["fold_to_cbet_pct"], "fold_cbet")
            + ratio_row("Aggression Factor", row["aggression_factor"])
        )

        showdown_stats = (
            stat_row("WTSD%", row["wtsd_pct"], "wtsd")
            + stat_row("W$SD%", row["wsd_pct"], "wsd")
        )

        scouting_bullets = generate_scouting_report(row)
        scouting_li = "\n                            ".join(
            f"<li>{b}</li>" for b in scouting_bullets
        )

        profiles += f'''
            <div class="player-profile">
                <div class="profile-header" onclick="toggleProfile('{slug}')">
                    <h3>{name}</h3>
                    <span class="profile-summary">{row['games_played']} sessions &middot; {row['hands_played']} hands &middot; <span class="{profit_class}">{profit_display}</span></span>
                </div>
                <div class="profile-body" id="profile-body-{slug}">
                    <div class="profile-stats-grid">
                        <div class="stat-category">
                            <h4>Preflop Tendencies</h4>
                            {preflop_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Big Blind Play</h4>
                            {bb_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Steal Game</h4>
                            {steal_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Postflop Play</h4>
                            {postflop_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Showdown</h4>
                            {showdown_stats}
                        </div>
                    </div>
                    <div class="scouting-report">
                        <h4>Scouting Report</h4>
                        <ul class="scouting-bullets">
                            {scouting_li}
                        </ul>
                    </div>
                </div>
            </div>'''

    return f'''
        <section class="player-profiles-section">
            <h2>Player Profiles</h2>
            <p class="profiles-hint">Click a player name to expand their profile, or click a row in the leaderboard above.</p>
            {profiles}
        </section>'''


def build_html(summary: dict, charts: dict, table_data: list) -> str:
    """Build the complete HTML dashboard as a string."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build player stats table rows
    table_rows = ""
    for row in table_data:
        profit_class = "positive" if row["total_profit"] >= 0 else "negative"
        profit_display = f"+{row['total_profit']:.2f}" if row["total_profit"] > 0 else f"{row['total_profit']:.2f}"
        avg_class = "positive" if row["avg_profit"] >= 0 else "negative"
        avg_display = f"+{row['avg_profit']:.2f}" if row["avg_profit"] > 0 else f"{row['avg_profit']:.2f}"

        ats_display = f"{row['ats_pct']:.1f}%" if row['ats_pct'] is not None else "-"
        slug = row['name'].lower().replace(' ', '-').replace("'", "")

        table_rows += f"""
                <tr onclick="toggleProfile('{slug}')" style="cursor:pointer;" title="Click to view {row['name']}'s profile">
                    <td>{row['name']}</td>
                    <td>{row['games_played']}</td>
                    <td>{row['hands_played']}</td>
                    <td>{row['hands_won']}</td>
                    <td>{row['win_rate']:.1f}%</td>
                    <td>{row['vpip_pct']:.1f}%</td>
                    <td>{row['conv_vpip_pct']:.1f}%</td>
                    <td>{row['pfr_pct']:.1f}%</td>
                    <td>{ats_display}</td>
                    <td class="{profit_class}">{profit_display}</td>
                    <td class="{avg_class}">{avg_display}</td>
                    <td>{row['showdowns']}</td>
                </tr>"""

    # Build player profiles section
    player_profiles_section = build_player_profiles_html(table_data)

    # Build chart sections
    chart_sections = ""
    chart_configs = [
        ("player_statistics.png", "Player Statistics",
         "Profit/loss, hands played, win rates, and average profit per hand for each player."),
        ("hand_analysis.png", "Hand Analysis",
         "Distribution of winning hand types and action frequency across all sessions."),
        ("session_trends.png", "Session Trends",
         "Top chart tracks cumulative profit/loss for the 3 biggest winners and 2 biggest losers. "
         "Bottom heatmap shows every player\u2019s profit/loss per session at a glance."),
        ("momentum.png", "Player Momentum",
         "Individual per-session profit/loss for each player. Green bars = winning sessions, "
         "red bars = losing sessions. \u2191/\u2193 arrows indicate recent trend direction."),
        ("stat_correlations.png", "Stat Correlations",
         "Pearson correlation matrix between all HUD stats and total profit. "
         "Green indicates positive correlation, red indicates negative."),
        ("profit_drivers.png", "Profit Drivers",
         "Regression analysis showing which HUD stats most strongly predict profit. "
         "Each panel shows scatter plot with best-fit line, R\u00b2, and p-value."),
        ("pipeline_diagram.png", "Pipeline Architecture",
         "How data flows from raw JSON replay files through the processing pipeline to this dashboard."),
    ]
    for filename, title, description in chart_configs:
        if filename in charts:
            chart_sections += f"""
        <section class="chart-section">
            <h2>{title}</h2>
            <p class="chart-description">{description}</p>
            <img src="data:image/png;base64,{charts[filename]}" alt="{title}" />
        </section>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Poker Analytics Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
            background: #1a1a2e;
            color: #eee;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            text-align: center;
            padding: 40px 20px;
            border-bottom: 2px solid #0f3460;
        }}
        header h1 {{
            font-size: 2.2rem;
            color: #e94560;
            margin-bottom: 8px;
        }}
        .subtitle {{
            color: #aaa;
            font-size: 1rem;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px 20px;
        }}
        .card {{
            background: #16213e;
            border: 1px solid #0f3460;
            border-radius: 10px;
            padding: 24px;
            text-align: center;
        }}
        .card-value {{
            font-size: 2.4rem;
            font-weight: bold;
            color: #e94560;
            font-family: 'Courier New', monospace;
        }}
        .card-label {{
            color: #aaa;
            font-size: 0.9rem;
            margin-top: 6px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .table-section {{
            padding: 30px 20px;
            overflow-x: auto;
        }}
        .table-section h2 {{
            color: #e94560;
            margin-bottom: 16px;
            font-size: 1.5rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #16213e;
            border-radius: 8px;
            overflow: hidden;
        }}
        thead {{
            background: #0f3460;
        }}
        th {{
            padding: 14px 16px;
            text-align: left;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
            white-space: nowrap;
            color: #eee;
        }}
        th:hover {{
            background: #1a4a8a;
        }}
        td {{
            padding: 12px 16px;
            border-bottom: 1px solid #0f3460;
            font-family: 'Courier New', monospace;
        }}
        tr:nth-child(even) {{
            background: #1a1a2e;
        }}
        tr:hover {{
            background: #1e2a4a;
        }}
        td:first-child {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-weight: 500;
        }}
        .positive {{
            color: #4caf50;
            font-weight: bold;
        }}
        .negative {{
            color: #e94560;
            font-weight: bold;
        }}
        .chart-section {{
            padding: 30px 20px;
            border-top: 1px solid #0f3460;
        }}
        .chart-section h2 {{
            color: #e94560;
            margin-bottom: 8px;
            font-size: 1.5rem;
        }}
        .chart-description {{
            color: #aaa;
            margin-bottom: 16px;
            font-size: 0.9rem;
        }}
        .chart-section img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            border: 1px solid #0f3460;
        }}
        footer {{
            text-align: center;
            padding: 30px 20px;
            border-top: 1px solid #0f3460;
            color: #666;
            font-size: 0.85rem;
        }}
        footer p {{
            margin: 4px 0;
        }}
        .player-profiles-section {{
            padding: 30px 20px;
            border-top: 1px solid #0f3460;
        }}
        .player-profiles-section h2 {{
            color: #e94560;
            margin-bottom: 8px;
            font-size: 1.5rem;
        }}
        .profiles-hint {{
            color: #aaa;
            font-size: 0.9rem;
            margin-bottom: 16px;
        }}
        .player-profile {{
            background: #16213e;
            border: 1px solid #0f3460;
            border-radius: 10px;
            margin-bottom: 12px;
            overflow: hidden;
        }}
        .profile-header {{
            padding: 16px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .profile-header:hover {{
            background: #1e2a4a;
        }}
        .profile-header h3 {{
            color: #e94560;
            font-size: 1.1rem;
            margin: 0;
        }}
        .profile-summary {{
            color: #aaa;
            font-size: 0.85rem;
        }}
        .profile-body {{
            padding: 0 20px;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease, padding 0.3s ease;
        }}
        .profile-body.open {{
            padding: 20px;
            max-height: 800px;
            border-top: 1px solid #0f3460;
        }}
        .profile-stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 20px;
        }}
        .stat-category h4 {{
            color: #e94560;
            font-size: 0.95rem;
            margin-bottom: 12px;
            border-bottom: 1px solid #0f3460;
            padding-bottom: 6px;
        }}
        .stat-row {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            gap: 10px;
        }}
        .stat-label {{
            color: #aaa;
            font-size: 0.85rem;
            min-width: 130px;
        }}
        .stat-bar-container {{
            flex: 1;
            height: 8px;
            background: #0f3460;
            border-radius: 4px;
            overflow: hidden;
        }}
        .stat-bar {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }}
        .stat-value {{
            color: #eee;
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            min-width: 55px;
            text-align: right;
        }}
        .stat-na {{
            color: #666;
            font-style: italic;
        }}
        .scouting-report {{
            margin-top: 20px;
            padding: 16px 20px;
            background: #1a1a2e;
            border-left: 3px solid #e94560;
            border-radius: 0 8px 8px 0;
        }}
        .scouting-report h4 {{
            color: #e94560;
            font-size: 0.95rem;
            margin-bottom: 10px;
            border-bottom: 1px solid #0f3460;
            padding-bottom: 6px;
        }}
        .scouting-bullets {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .scouting-bullets li {{
            color: #eee;
            font-size: 0.88rem;
            line-height: 1.5;
            padding: 6px 0 6px 20px;
            position: relative;
            border-bottom: 1px solid rgba(15, 52, 96, 0.5);
        }}
        .scouting-bullets li:last-child {{
            border-bottom: none;
        }}
        .scouting-bullets li::before {{
            content: "\\25B6";
            color: #e94560;
            position: absolute;
            left: 0;
            font-size: 0.7rem;
            top: 8px;
        }}
        @media (max-width: 768px) {{
            header h1 {{
                font-size: 1.6rem;
            }}
            .summary-cards {{
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
            }}
            .card-value {{
                font-size: 1.8rem;
            }}
            table {{
                font-size: 0.85rem;
            }}
            th, td {{
                padding: 8px 10px;
            }}
            .profile-header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 4px;
            }}
            .profile-stats-grid {{
                grid-template-columns: 1fr;
            }}
            .scouting-report {{
                margin-top: 16px;
                padding: 12px 16px;
            }}
            .scouting-bullets li {{
                font-size: 0.82rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>&#9824; Poker Analytics Dashboard</h1>
            <p class="subtitle">Auto-generated from {summary['files_ingested']} session files &middot; Players with {MIN_GAMES}+ games</p>
        </header>

        <section class="summary-cards">
            <div class="card">
                <div class="card-value">{summary['total_games']}</div>
                <div class="card-label">Sessions</div>
            </div>
            <div class="card">
                <div class="card-value">{summary['total_hands']:,}</div>
                <div class="card-label">Total Hands</div>
            </div>
            <div class="card">
                <div class="card-value">{summary['total_players']}</div>
                <div class="card-label">Players</div>
            </div>
            <div class="card">
                <div class="card-value">{summary['total_events']:,}</div>
                <div class="card-label">Events Tracked</div>
            </div>
        </section>

        <section class="table-section">
            <h2>Player Leaderboard</h2>
            <table id="playerTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0, 'string')">Player &#8597;</th>
                        <th onclick="sortTable(1, 'number')">Games &#8597;</th>
                        <th onclick="sortTable(2, 'number')">Hands &#8597;</th>
                        <th onclick="sortTable(3, 'number')">Wins &#8597;</th>
                        <th onclick="sortTable(4, 'number')">Win Rate &#8597;</th>
                        <th onclick="sortTable(5, 'number')" title="PokerNow VPIP: voluntary money on any street (preflop + postflop)">PN VPIP% &#8597;</th>
                        <th onclick="sortTable(6, 'number')" title="Conventional VPIP: voluntary money preflop only">VPIP% &#8597;</th>
                        <th onclick="sortTable(7, 'number')" title="Pre-Flop Raise">PFR% &#8597;</th>
                        <th onclick="sortTable(8, 'number')" title="Attempt to Steal">ATS% &#8597;</th>
                        <th onclick="sortTable(9, 'number')">Profit/Loss &#8597;</th>
                        <th onclick="sortTable(10, 'number')">Avg/Hand &#8597;</th>
                        <th onclick="sortTable(11, 'number')">Showdowns &#8597;</th>
                    </tr>
                </thead>
                <tbody>{table_rows}
                </tbody>
            </table>
        </section>

        {player_profiles_section}

        {chart_sections}

        <footer>
            <p>Last updated: {timestamp}</p>
            <p>Built automatically by GitHub Actions</p>
        </footer>
    </div>

    <script>
        function sortTable(colIdx, type) {{
            var table = document.getElementById("playerTable");
            var tbody = table.querySelector("tbody");
            var rows = Array.from(tbody.querySelectorAll("tr"));

            if (!table.dataset.sortCol || parseInt(table.dataset.sortCol) !== colIdx) {{
                table.dataset.sortDir = "desc";
            }} else {{
                table.dataset.sortDir = table.dataset.sortDir === "asc" ? "desc" : "asc";
            }}
            table.dataset.sortCol = colIdx;
            var dir = table.dataset.sortDir === "asc" ? 1 : -1;

            rows.sort(function(a, b) {{
                var aVal = a.cells[colIdx].textContent.replace(/[+%,]/g, "").trim();
                var bVal = b.cells[colIdx].textContent.replace(/[+%,]/g, "").trim();
                if (type === "number") {{
                    return (parseFloat(aVal) - parseFloat(bVal)) * dir;
                }}
                return aVal.localeCompare(bVal) * dir;
            }});

            rows.forEach(function(row) {{ tbody.appendChild(row); }});
        }}

        function toggleProfile(name) {{
            var body = document.getElementById('profile-body-' + name);
            if (body) {{
                var wasOpen = body.classList.contains('open');
                body.classList.toggle('open');
                if (!wasOpen) {{
                    body.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
                }}
            }}
        }}
    </script>
</body>
</html>"""

    return html


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else OUTPUT_DIR
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("POKER DASHBOARD GENERATOR")
    print("=" * 50)

    # Step 1: Run full pipeline
    print("\n[1/4] Running data pipeline...")
    summary = run_pipeline(DB_PATH)
    print(f"  Ingested {summary['files_ingested']} files")
    print(f"  {summary['total_hands']} hands, {summary['total_players']} players")

    # Step 2: Generate charts as base64
    print("\n[2/4] Generating charts...")
    charts = generate_chart_base64(DB_PATH, output_dir)
    print(f"  Generated {len(charts)} charts")

    # Step 3: Get table data
    print("\n[3/4] Building player leaderboard...")
    table_data = get_table_data(DB_PATH)
    print(f"  {len(table_data)} players in leaderboard")

    # Step 4: Generate HTML
    print("\n[4/4] Generating HTML dashboard...")
    html = build_html(summary, charts, table_data)

    output_path = Path(output_dir) / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n  Dashboard written to: {output_path}")
    print(f"  File size: {size_kb:.1f} KB")
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
