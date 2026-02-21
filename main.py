"""
Main entry point for the Poker Hand History Pipeline.

Usage:
    python main.py                      # Ingest all JSON files and generate visualizations
    python main.py ingest <file.json>   # Ingest a specific file
    python main.py ingest <directory>   # Ingest all JSON files in directory
    python main.py visualize            # Generate visualizations from existing database
    python main.py stats                # Print summary statistics
    python main.py load-mappings        # Load player mappings from player_map.yaml
    python main.py unmapped             # List players not yet mapped to canonical identities
    python main.py export-players       # Generate YAML template from existing players
"""
import sys
from pathlib import Path
from database import init_database, get_connection
from ingest import ingest_file, ingest_directory
from visualize import generate_all_visualizations, plot_player_statistics, plot_hand_analysis, plot_session_trends
from mappings import load_mappings, list_unmapped_players, export_players_template


DB_PATH = "poker.db"


def print_stats(db_path: str = DB_PATH):
    """Print summary statistics from the database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    print("\n" + "=" * 50)
    print("POKER DATABASE SUMMARY")
    print("=" * 50)

    # Count games
    cursor.execute("SELECT COUNT(*) FROM games")
    games = cursor.fetchone()[0]
    print(f"\nGames (sessions): {games}")

    # Count hands
    cursor.execute("SELECT COUNT(*) FROM hands")
    hands = cursor.fetchone()[0]
    print(f"Total hands: {hands}")

    # Count players
    cursor.execute("SELECT COUNT(*) FROM players")
    players = cursor.fetchone()[0]
    print(f"Unique players: {players}")

    # Count events
    cursor.execute("SELECT COUNT(*) FROM events")
    events = cursor.fetchone()[0]
    print(f"Total events: {events}")

    # Player summary
    print("\n" + "-" * 50)
    print("PLAYER SUMMARY")
    print("-" * 50)

    cursor.execute("""
        SELECT
            p.name,
            COUNT(DISTINCT hp.hand_id) as hands,
            COALESCE(SUM(hp.net_gain), 0) as profit
        FROM players p
        JOIN hand_players hp ON p.id = hp.player_id
        GROUP BY p.id
        ORDER BY profit DESC
    """)

    print(f"{'Player':<20} {'Hands':>10} {'Profit/Loss':>15}")
    print("-" * 45)
    for row in cursor.fetchall():
        profit = row['profit']
        profit_str = f"+{profit}" if profit > 0 else str(profit)
        print(f"{row['name']:<20} {row['hands']:>10} {profit_str:>15}")

    # Top winning hands
    print("\n" + "-" * 50)
    print("WINNING HAND DISTRIBUTION")
    print("-" * 50)

    cursor.execute("""
        SELECT hand_description, COUNT(*) as count
        FROM hand_results
        WHERE hand_description IS NOT NULL
        GROUP BY hand_description
        ORDER BY count DESC
        LIMIT 10
    """)

    for row in cursor.fetchall():
        print(f"{row['hand_description']:<30} {row['count']:>5} wins")

    conn.close()
    print("\n" + "=" * 50)


def run_full_pipeline(db_path: str = DB_PATH):
    """Run the full pipeline: ingest and visualize."""
    print("=" * 50)
    print("POKER HAND HISTORY PIPELINE")
    print("=" * 50)

    # Find and ingest JSON files
    json_files = list(Path(".").glob("*.json"))

    if not json_files:
        print("\nNo JSON files found in current directory.")
        print("Usage: python main.py ingest <file.json>")
        return

    print(f"\nFound {len(json_files)} JSON file(s) to process:")
    for f in json_files:
        print(f"  - {f.name}")

    print("\n" + "-" * 50)
    print("INGESTING DATA")
    print("-" * 50)

    for json_file in json_files:
        print(f"\nProcessing: {json_file.name}")
        stats = ingest_file(str(json_file), db_path)
        print(f"  Hands: {stats['hands_processed']}")
        print(f"  Players: {stats['players_added']}")
        print(f"  Events: {stats['events_added']}")
        print(f"  Results: {stats['results_added']}")

    # Print statistics
    print_stats(db_path)

    # Generate visualizations
    print("\n" + "-" * 50)
    print("GENERATING VISUALIZATIONS")
    print("-" * 50)
    generate_all_visualizations(db_path)


def main():
    if len(sys.argv) < 2:
        # Default: run full pipeline
        run_full_pipeline()
        return

    command = sys.argv[1].lower()

    if command == "ingest":
        if len(sys.argv) < 3:
            print("Usage: python main.py ingest <file.json|directory>")
            return

        target = sys.argv[2]
        if Path(target).is_dir():
            results = ingest_directory(target, DB_PATH)
            print(f"\nIngested {len(results)} files")
        else:
            stats = ingest_file(target, DB_PATH)
            print(f"\nIngested: {stats['game_id']}")
            print(f"  Hands: {stats['hands_processed']}")

    elif command == "visualize":
        print("Generating visualizations...")
        generate_all_visualizations(DB_PATH)
        print("\nShowing interactive plots...")
        plot_player_statistics(DB_PATH)
        plot_hand_analysis(DB_PATH)
        plot_session_trends(DB_PATH)

    elif command == "stats":
        print_stats(DB_PATH)

    elif command == "load-mappings":
        yaml_file = sys.argv[2] if len(sys.argv) > 2 else "player_map.yaml"
        print(f"Loading player mappings from {yaml_file}...")
        stats = load_mappings(yaml_file, DB_PATH)

        if "error" in stats:
            print(f"Error: {stats['error']}")
        else:
            print(f"\nLoaded successfully:")
            print(f"  Canonical players: {stats['canonical_players_added']}")
            print(f"  Mappings: {stats['mappings_added']}")
            if stats.get('errors'):
                print(f"\nWarnings ({len(stats['errors'])}):")
                for err in stats['errors']:
                    print(f"  - {err}")

    elif command == "unmapped":
        unmapped = list_unmapped_players(DB_PATH)
        if not unmapped:
            print("\nAll players are mapped!")
        else:
            print(f"\nUnmapped players ({len(unmapped)} total):")
            print("-" * 65)
            print(f"{'Player ID':<25} {'Nickname':<25} {'Hands':>10}")
            print("-" * 65)
            for p in unmapped:
                print(f"{p['player_id']:<25} {p['nickname']:<25} {p['hands_played']:>10}")
            print("-" * 65)
            print("\nTo map these players, edit player_map.yaml and run: python main.py load-mappings")

    elif command == "export-players":
        output_file = sys.argv[2] if len(sys.argv) > 2 else "player_map.yaml"
        template = export_players_template(DB_PATH)

        if Path(output_file).exists():
            print(f"Warning: {output_file} already exists.")
            response = input("Overwrite? (y/N): ").strip().lower()
            if response != 'y':
                print("Aborted. Printing to stdout instead:\n")
                print(template)
                return

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(template)
        print(f"Exported player template to {output_file}")
        print("Edit this file to group player aliases, then run: python main.py load-mappings")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
