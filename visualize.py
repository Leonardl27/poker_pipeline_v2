"""
Visualization module for poker hand history analysis.
Uses Matplotlib for static charts.

By default, uses enriched data (canonical player names) when mappings exist.
Falls back to raw data for unmapped players.
"""
import sqlite3
from collections import defaultdict
from typing import Optional
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from database import get_connection, EVENT_TYPES


def get_player_statistics(db_path: str = "poker.db", use_enriched: bool = True) -> list:
    """
    Get comprehensive player statistics.

    Args:
        db_path: Path to database
        use_enriched: If True, aggregate by canonical player names when mapped
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if use_enriched:
        # Enriched query: use canonical names where available, aggregate by canonical identity
        cursor.execute("""
            SELECT
                COALESCE(cp.name, p.name) as name,
                COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as id,
                COUNT(DISTINCT hp.hand_id) as hands_played,
                SUM(hp.net_gain) as total_profit,
                AVG(hp.net_gain) as avg_profit_per_hand,
                SUM(CASE WHEN hp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
                SUM(CASE WHEN hp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns
            FROM players p
            JOIN hand_players hp ON p.id = hp.player_id
            LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
            LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
            GROUP BY COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id)
            ORDER BY total_profit DESC
        """)
    else:
        # Raw query: use original player identities
        cursor.execute("""
            SELECT
                p.id,
                p.name,
                COUNT(DISTINCT hp.hand_id) as hands_played,
                SUM(hp.net_gain) as total_profit,
                AVG(hp.net_gain) as avg_profit_per_hand,
                SUM(CASE WHEN hp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
                SUM(CASE WHEN hp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns
            FROM players p
            JOIN hand_players hp ON p.id = hp.player_id
            GROUP BY p.id
            ORDER BY total_profit DESC
        """)

    results = cursor.fetchall()
    conn.close()
    return results


def get_hand_distributions(db_path: str = "poker.db") -> dict:
    """Get hand strength distribution data."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Get winning hand descriptions
    cursor.execute("""
        SELECT hand_description, COUNT(*) as count
        FROM hand_results
        WHERE hand_description IS NOT NULL
        GROUP BY hand_description
        ORDER BY count DESC
    """)

    hand_dist = cursor.fetchall()

    # Get action distributions by event type
    cursor.execute("""
        SELECT event_type, COUNT(*) as count
        FROM events
        WHERE event_type IS NOT NULL
        GROUP BY event_type
        ORDER BY count DESC
    """)

    action_dist = cursor.fetchall()
    conn.close()

    return {
        "hands": hand_dist,
        "actions": action_dist
    }


def get_session_data(db_path: str = "poker.db", use_enriched: bool = True) -> list:
    """
    Get session progression data for stack tracking.

    Args:
        db_path: Path to database
        use_enriched: If True, use canonical player names when mapped
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if use_enriched:
        cursor.execute("""
            SELECT
                h.hand_number,
                h.started_at,
                COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as player_id,
                COALESCE(cp.name, p.name) as name,
                hp.net_gain,
                hp.stack
            FROM hands h
            JOIN hand_players hp ON h.id = hp.hand_id
            JOIN players p ON hp.player_id = p.id
            LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
            LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
            ORDER BY h.started_at, player_id
        """)
    else:
        cursor.execute("""
            SELECT
                h.hand_number,
                h.started_at,
                hp.player_id,
                p.name,
                hp.net_gain,
                hp.stack
            FROM hands h
            JOIN hand_players hp ON h.id = hp.hand_id
            JOIN players p ON hp.player_id = p.id
            ORDER BY h.started_at, hp.player_id
        """)

    results = cursor.fetchall()
    conn.close()
    return results


def get_pot_sizes(db_path: str = "poker.db") -> list:
    """Get pot size data for each hand."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            h.hand_number,
            h.started_at,
            MAX(hr.pot) as pot_size
        FROM hands h
        JOIN hand_results hr ON h.id = hr.hand_id
        GROUP BY h.id
        ORDER BY h.started_at
    """)

    results = cursor.fetchall()
    conn.close()
    return results


def plot_player_statistics(db_path: str = "poker.db", save_path: Optional[str] = None):
    """Create player statistics visualizations."""
    stats = get_player_statistics(db_path)

    if not stats:
        print("No data available for player statistics")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Player Statistics', fontsize=16, fontweight='bold')

    names = [row['name'] for row in stats]
    profits = [row['total_profit'] or 0 for row in stats]
    hands = [row['hands_played'] for row in stats]
    win_rates = [
        (row['hands_won'] / row['hands_played'] * 100) if row['hands_played'] > 0 else 0
        for row in stats
    ]
    avg_profits = [row['avg_profit_per_hand'] or 0 for row in stats]

    # Total profit bar chart
    ax1 = axes[0, 0]
    colors = ['green' if p >= 0 else 'red' for p in profits]
    ax1.barh(names, profits, color=colors)
    ax1.set_xlabel('Total Profit/Loss')
    ax1.set_title('Total Profit/Loss by Player')
    ax1.axvline(x=0, color='black', linestyle='-', linewidth=0.5)

    # Hands played bar chart
    ax2 = axes[0, 1]
    ax2.barh(names, hands, color='steelblue')
    ax2.set_xlabel('Number of Hands')
    ax2.set_title('Hands Played by Player')

    # Win rate bar chart
    ax3 = axes[1, 0]
    ax3.barh(names, win_rates, color='orange')
    ax3.set_xlabel('Win Rate (%)')
    ax3.set_title('Win Rate by Player (% of hands won)')

    # Average profit per hand
    ax4 = axes[1, 1]
    colors = ['green' if p >= 0 else 'red' for p in avg_profits]
    ax4.barh(names, avg_profits, color=colors)
    ax4.set_xlabel('Avg Profit per Hand')
    ax4.set_title('Average Profit per Hand')
    ax4.axvline(x=0, color='black', linestyle='-', linewidth=0.5)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def plot_hand_analysis(db_path: str = "poker.db", save_path: Optional[str] = None):
    """Create hand analysis visualizations."""
    data = get_hand_distributions(db_path)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Hand Analysis', fontsize=16, fontweight='bold')

    # Winning hand distribution
    ax1 = axes[0]
    if data["hands"]:
        hand_names = [row['hand_description'] for row in data["hands"]]
        hand_counts = [row['count'] for row in data["hands"]]
        ax1.barh(hand_names, hand_counts, color='purple')
        ax1.set_xlabel('Count')
        ax1.set_title('Winning Hand Distribution')
    else:
        ax1.text(0.5, 0.5, 'No hand data available', ha='center', va='center')

    # Action distribution
    ax2 = axes[1]
    if data["actions"]:
        action_names = [EVENT_TYPES.get(row['event_type'], f"Type {row['event_type']}")
                        for row in data["actions"]]
        action_counts = [row['count'] for row in data["actions"]]
        ax2.barh(action_names, action_counts, color='teal')
        ax2.set_xlabel('Count')
        ax2.set_title('Action Distribution')
    else:
        ax2.text(0.5, 0.5, 'No action data available', ha='center', va='center')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def plot_session_trends(db_path: str = "poker.db", save_path: Optional[str] = None):
    """Create session trend visualizations."""
    session_data = get_session_data(db_path)
    pot_data = get_pot_sizes(db_path)

    if not session_data:
        print("No session data available")
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('Session Trends', fontsize=16, fontweight='bold')

    # Calculate cumulative profit per player
    player_cumulative = defaultdict(lambda: {"hands": [], "cumulative": [], "name": ""})

    for row in session_data:
        player_id = row['player_id']
        hand_num = row['hand_number']
        net_gain = row['net_gain'] or 0
        name = row['name']

        player_cumulative[player_id]["name"] = name

        if player_cumulative[player_id]["cumulative"]:
            prev = player_cumulative[player_id]["cumulative"][-1]
        else:
            prev = 0

        player_cumulative[player_id]["hands"].append(hand_num)
        player_cumulative[player_id]["cumulative"].append(prev + net_gain)

    # Stack progression over time
    ax1 = axes[0]
    for player_id, data in player_cumulative.items():
        ax1.plot(data["hands"], data["cumulative"], label=data["name"], marker='o', markersize=3)

    ax1.set_xlabel('Hand Number')
    ax1.set_ylabel('Cumulative Profit/Loss')
    ax1.set_title('Stack Progression Over Session')
    ax1.legend(loc='best')
    ax1.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
    ax1.grid(True, alpha=0.3)

    # Pot size over time
    ax2 = axes[1]
    if pot_data:
        hand_nums = [row['hand_number'] for row in pot_data]
        pot_sizes = [row['pot_size'] or 0 for row in pot_data]
        ax2.bar(hand_nums, pot_sizes, color='gold', alpha=0.7)
        ax2.set_xlabel('Hand Number')
        ax2.set_ylabel('Pot Size')
        ax2.set_title('Pot Size by Hand')
        ax2.grid(True, alpha=0.3, axis='y')
    else:
        ax2.text(0.5, 0.5, 'No pot data available', ha='center', va='center')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def generate_all_visualizations(db_path: str = "poker.db", output_dir: str = "."):
    """Generate all visualizations and save to files."""
    from pathlib import Path

    output = Path(output_dir)
    output.mkdir(exist_ok=True)

    print("Generating visualizations...")

    plot_player_statistics(db_path, str(output / "player_statistics.png"))
    plot_hand_analysis(db_path, str(output / "hand_analysis.png"))
    plot_session_trends(db_path, str(output / "session_trends.png"))

    print("\nAll visualizations generated!")


if __name__ == "__main__":
    import sys

    db = sys.argv[1] if len(sys.argv) > 1 else "poker.db"

    print("Generating all visualizations...")
    generate_all_visualizations(db)

    # Also show interactive plots
    plot_player_statistics(db)
    plot_hand_analysis(db)
    plot_session_trends(db)
