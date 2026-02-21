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
    for chart_name in ["player_statistics.png", "hand_analysis.png", "session_trends.png", "pipeline_diagram.png"]:
        chart_path = Path(output_dir) / chart_name
        if chart_path.exists():
            with open(chart_path, "rb") as f:
                charts[chart_name] = base64.b64encode(f.read()).decode("utf-8")

    return charts


def get_table_data(db_path: str) -> list:
    """Get player statistics formatted for the HTML leaderboard table."""
    stats = get_player_statistics(db_path, use_enriched=True, min_games=MIN_GAMES)
    rows = []
    for row in stats:
        hands_played = row["hands_played"]
        hands_won = row["hands_won"] or 0
        total_profit = row["total_profit"] or 0
        avg_profit = row["avg_profit_per_hand"] or 0
        win_rate = (hands_won / hands_played * 100) if hands_played > 0 else 0

        rows.append({
            "name": row["name"],
            "games_played": row["games_played"],
            "hands_played": hands_played,
            "hands_won": hands_won,
            "win_rate": round(win_rate, 1),
            "total_profit": total_profit,
            "avg_profit": round(avg_profit, 1),
            "showdowns": row["showdowns"] or 0,
        })
    return rows


def build_html(summary: dict, charts: dict, table_data: list) -> str:
    """Build the complete HTML dashboard as a string."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build player stats table rows
    table_rows = ""
    for row in table_data:
        profit_class = "positive" if row["total_profit"] >= 0 else "negative"
        profit_display = f"+{row['total_profit']}" if row["total_profit"] > 0 else str(row["total_profit"])
        avg_class = "positive" if row["avg_profit"] >= 0 else "negative"
        avg_display = f"+{row['avg_profit']:.1f}" if row["avg_profit"] > 0 else f"{row['avg_profit']:.1f}"

        table_rows += f"""
                <tr>
                    <td>{row['name']}</td>
                    <td>{row['games_played']}</td>
                    <td>{row['hands_played']}</td>
                    <td>{row['hands_won']}</td>
                    <td>{row['win_rate']:.1f}%</td>
                    <td class="{profit_class}">{profit_display}</td>
                    <td class="{avg_class}">{avg_display}</td>
                    <td>{row['showdowns']}</td>
                </tr>"""

    # Build chart sections
    chart_sections = ""
    chart_configs = [
        ("player_statistics.png", "Player Statistics",
         "Profit/loss, hands played, win rates, and average profit per hand for each player."),
        ("hand_analysis.png", "Hand Analysis",
         "Distribution of winning hand types and action frequency across all sessions."),
        ("session_trends.png", "Session Trends",
         "Cumulative profit/loss progression and pot sizes across all hands."),
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
                        <th onclick="sortTable(5, 'number')">Profit/Loss &#8597;</th>
                        <th onclick="sortTable(6, 'number')">Avg/Hand &#8597;</th>
                        <th onclick="sortTable(7, 'number')">Showdowns &#8597;</th>
                    </tr>
                </thead>
                <tbody>{table_rows}
                </tbody>
            </table>
        </section>

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
