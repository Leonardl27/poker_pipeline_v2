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


def get_player_statistics(db_path: str = "poker.db", use_enriched: bool = True,
                          min_games: int = 0) -> list:
    """
    Get comprehensive player statistics.

    Args:
        db_path: Path to database
        use_enriched: If True, aggregate by canonical player names when mapped
        min_games: Minimum number of game sessions a player must have participated in
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    having_clause = f"HAVING COUNT(DISTINCT h.game_id) >= {min_games}" if min_games > 0 else ""

    if use_enriched:
        # Enriched query: use canonical names where available, aggregate by canonical identity
        cursor.execute(f"""
            SELECT
                COALESCE(cp.name, p.name) as name,
                COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as id,
                COUNT(DISTINCT hp.hand_id) as hands_played,
                SUM(hp.net_gain) as total_profit,
                AVG(hp.net_gain) as avg_profit_per_hand,
                SUM(CASE WHEN hp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
                SUM(CASE WHEN hp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns,
                COUNT(DISTINCT h.game_id) as games_played
            FROM players p
            JOIN hand_players hp ON p.id = hp.player_id
            JOIN hands h ON hp.hand_id = h.id
            LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
            LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
            GROUP BY COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id)
            {having_clause}
            ORDER BY total_profit DESC
        """)
    else:
        # Raw query: use original player identities
        cursor.execute(f"""
            SELECT
                p.id,
                p.name,
                COUNT(DISTINCT hp.hand_id) as hands_played,
                SUM(hp.net_gain) as total_profit,
                AVG(hp.net_gain) as avg_profit_per_hand,
                SUM(CASE WHEN hp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
                SUM(CASE WHEN hp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns,
                COUNT(DISTINCT h.game_id) as games_played
            FROM players p
            JOIN hand_players hp ON p.id = hp.player_id
            JOIN hands h ON hp.hand_id = h.id
            GROUP BY p.id
            {having_clause}
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


def plot_player_statistics(db_path: str = "poker.db", save_path: Optional[str] = None,
                           min_games: int = 0):
    """Create player statistics visualizations."""
    stats = get_player_statistics(db_path, min_games=min_games)

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


def _categorize_hand(description: str) -> str:
    """Extract the hand category from a hand description like 'Pair, A's' -> 'Pair'."""
    for category in [
        "Four of a Kind", "Full House", "Flush", "Straight",
        "Three of a Kind", "Two Pair", "Pair"
    ]:
        if description.startswith(category):
            return category
    return "High Card"


def plot_hand_analysis(db_path: str = "poker.db", save_path: Optional[str] = None):
    """Create hand analysis visualizations."""
    data = get_hand_distributions(db_path)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Hand Analysis', fontsize=16, fontweight='bold')

    # Winning hand distribution — grouped by category
    ax1 = axes[0]
    if data["hands"]:
        # Aggregate counts by hand category
        category_counts = defaultdict(int)
        for row in data["hands"]:
            category = _categorize_hand(row['hand_description'])
            category_counts[category] += row['count']

        # Sort by poker hand ranking (weakest to strongest for bottom-to-top display)
        hand_ranking = [
            "High Card", "Pair", "Two Pair", "Three of a Kind",
            "Straight", "Flush", "Full House", "Four of a Kind"
        ]
        sorted_categories = [h for h in hand_ranking if h in category_counts]
        sorted_counts = [category_counts[h] for h in sorted_categories]

        colors = plt.cm.RdYlGn([i / (len(sorted_categories) - 1) for i in range(len(sorted_categories))])
        ax1.barh(sorted_categories, sorted_counts, color=colors)
        ax1.set_xlabel('Count')
        ax1.set_title('Winning Hand Distribution')

        # Add count labels on bars
        for i, (count, name) in enumerate(zip(sorted_counts, sorted_categories)):
            ax1.text(count + max(sorted_counts) * 0.01, i, str(count),
                     va='center', fontsize=9, fontweight='bold')
    else:
        ax1.text(0.5, 0.5, 'No hand data available', ha='center', va='center')

    # Action distribution — filter out unknown types
    ax2 = axes[1]
    if data["actions"]:
        action_names = []
        action_counts = []
        for row in data["actions"]:
            name = EVENT_TYPES.get(row['event_type'])
            if name is None:
                continue
            action_names.append(name)
            action_counts.append(row['count'])

        ax2.barh(action_names, action_counts, color='teal')
        ax2.set_xlabel('Count')
        ax2.set_title('Action Distribution')

        # Add count labels on bars
        for i, count in enumerate(action_counts):
            ax2.text(count + max(action_counts) * 0.01, i, f'{count:,}',
                     va='center', fontsize=9)
    else:
        ax2.text(0.5, 0.5, 'No action data available', ha='center', va='center')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def plot_session_trends(db_path: str = "poker.db", save_path: Optional[str] = None,
                        min_games: int = 0):
    """Create session trend visualizations with global hand indexing across sessions."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Get all hands ordered by timestamp, assign a global sequential index
    cursor.execute("""
        SELECT h.id as hand_id, h.game_id, h.hand_number, h.started_at
        FROM hands h
        ORDER BY h.started_at, h.hand_number
    """)
    all_hands = cursor.fetchall()

    if not all_hands:
        print("No session data available")
        conn.close()
        return

    # Build global index and detect session boundaries
    hand_id_to_global = {}
    session_boundaries = []
    prev_game_id = None
    for i, hand in enumerate(all_hands):
        hand_id_to_global[hand['hand_id']] = i + 1
        if hand['game_id'] != prev_game_id:
            if prev_game_id is not None:
                session_boundaries.append(i + 1)
            prev_game_id = hand['game_id']

    total_hands = len(all_hands)

    # Get player net gains per hand, with canonical names
    cursor.execute("""
        SELECT
            hp.hand_id,
            h.game_id,
            COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as player_id,
            COALESCE(cp.name, p.name) as name,
            hp.net_gain
        FROM hand_players hp
        JOIN hands h ON hp.hand_id = h.id
        JOIN players p ON hp.player_id = p.id
        LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
        LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
        ORDER BY h.started_at, h.hand_number
    """)
    player_data = cursor.fetchall()

    # Count games per player for filtering
    cursor.execute("""
        SELECT
            COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as player_id,
            COUNT(DISTINCT h.game_id) as games_played
        FROM players p
        JOIN hand_players hp ON p.id = hp.player_id
        JOIN hands h ON hp.hand_id = h.id
        LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
        LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
        GROUP BY player_id
    """)
    player_games = {row['player_id']: row['games_played'] for row in cursor.fetchall()}

    # Get pot sizes with global index
    cursor.execute("""
        SELECT h.id as hand_id, MAX(hr.pot) as pot_size
        FROM hands h
        JOIN hand_results hr ON h.id = hr.hand_id
        GROUP BY h.id
    """)
    pot_by_hand = {row['hand_id']: row['pot_size'] or 0 for row in cursor.fetchall()}

    conn.close()

    # Build cumulative profit per player (filtered by min_games)
    player_cumulative = defaultdict(lambda: {"indices": [], "cumulative": [], "name": ""})

    for row in player_data:
        pid = row['player_id']
        if min_games > 0 and player_games.get(pid, 0) < min_games:
            continue

        global_idx = hand_id_to_global.get(row['hand_id'])
        if global_idx is None:
            continue

        net_gain = row['net_gain'] or 0
        player_cumulative[pid]["name"] = row['name']

        prev = player_cumulative[pid]["cumulative"][-1] if player_cumulative[pid]["cumulative"] else 0
        player_cumulative[pid]["indices"].append(global_idx)
        player_cumulative[pid]["cumulative"].append(prev + net_gain)

    # Sort players by final profit for consistent legend ordering
    sorted_players = sorted(player_cumulative.items(),
                            key=lambda x: x[1]["cumulative"][-1] if x[1]["cumulative"] else 0,
                            reverse=True)

    fig, axes = plt.subplots(2, 1, figsize=(16, 10))
    fig.suptitle('Session Trends', fontsize=16, fontweight='bold')

    # Top: Cumulative profit across all sessions
    ax1 = axes[0]
    for pid, data in sorted_players:
        ax1.plot(data["indices"], data["cumulative"], label=data["name"], linewidth=1.5, alpha=0.85)

    # Draw session boundary lines
    for boundary in session_boundaries:
        ax1.axvline(x=boundary, color='gray', linestyle=':', linewidth=0.5, alpha=0.5)

    ax1.set_xlabel(f'Hand (sequential across {len(session_boundaries) + 1} sessions)')
    ax1.set_ylabel('Cumulative Profit/Loss')
    ax1.set_title('All-Time Cumulative Profit/Loss')
    ax1.legend(loc='upper left', fontsize=8, ncol=2, framealpha=0.9)
    ax1.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
    ax1.grid(True, alpha=0.2)

    # Bottom: Pot size across all sessions
    ax2 = axes[1]
    global_pot_indices = []
    global_pot_sizes = []
    for hand in all_hands:
        gidx = hand_id_to_global[hand['hand_id']]
        pot = pot_by_hand.get(hand['hand_id'], 0)
        if pot > 0:
            global_pot_indices.append(gidx)
            global_pot_sizes.append(pot)

    if global_pot_sizes:
        ax2.bar(global_pot_indices, global_pot_sizes, color='gold', alpha=0.7, width=1.0)
        for boundary in session_boundaries:
            ax2.axvline(x=boundary, color='gray', linestyle=':', linewidth=0.5, alpha=0.5)
        ax2.set_xlabel(f'Hand (sequential across {len(session_boundaries) + 1} sessions)')
        ax2.set_ylabel('Pot Size')
        ax2.set_title('Pot Size by Hand')
        ax2.grid(True, alpha=0.2, axis='y')
    else:
        ax2.text(0.5, 0.5, 'No pot data available', ha='center', va='center')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def plot_pipeline_diagram(save_path: Optional[str] = None):
    """Create a visual diagram of the data pipeline architecture."""
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis('off')
    fig.patch.set_facecolor('#1a1a2e')

    # Colors
    bg = '#16213e'
    border = '#0f3460'
    accent = '#e94560'
    teal = '#2a9d8f'
    gold = '#e9c46a'
    text_color = '#eee'
    arrow_color = '#aaa'

    def draw_box(x, y, w, h, label, sublabel=None, color=border, fc=bg):
        rect = plt.Rectangle((x, y), w, h, linewidth=2, edgecolor=color,
                              facecolor=fc, zorder=2, clip_on=False)
        ax.add_patch(rect)
        if sublabel:
            ax.text(x + w/2, y + h/2 + 0.15, label, ha='center', va='center',
                    fontsize=11, fontweight='bold', color=text_color, zorder=3)
            ax.text(x + w/2, y + h/2 - 0.2, sublabel, ha='center', va='center',
                    fontsize=8, color='#aaa', zorder=3, style='italic')
        else:
            ax.text(x + w/2, y + h/2, label, ha='center', va='center',
                    fontsize=11, fontweight='bold', color=text_color, zorder=3)

    def draw_arrow(x1, y1, x2, y2):
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle='->', color=arrow_color,
                                    lw=2, connectionstyle='arc3,rad=0'),
                    zorder=1)

    # Title
    ax.text(7, 6.5, 'Poker Pipeline Architecture', ha='center', va='center',
            fontsize=18, fontweight='bold', color=accent)

    # Row 1: Data Sources
    ax.text(2.5, 5.7, 'DATA SOURCES', ha='center', fontsize=9, color=gold,
            fontweight='bold')
    draw_box(0.5, 4.8, 4, 0.8, 'JSON Replay Files', 'raw/*.json', color=teal)

    ax.text(9, 5.7, 'CONFIGURATION', ha='center', fontsize=9, color=gold,
            fontweight='bold')
    draw_box(7, 4.8, 4, 0.8, 'Player Mappings', 'player_map.yaml', color=teal)

    # Row 2: Processing
    ax.text(5.5, 4.1, 'PROCESSING PIPELINE', ha='center', fontsize=9, color=gold,
            fontweight='bold')
    draw_box(0.5, 3.0, 2.8, 0.8, 'Ingest', 'ingest.py', color=accent)
    draw_box(4.1, 3.0, 2.8, 0.8, 'Map Players', 'mappings.py', color=accent)
    draw_box(7.7, 3.0, 2.8, 0.8, 'Visualize', 'visualize.py', color=accent)

    # Arrows: sources -> processing
    draw_arrow(2.5, 4.8, 1.9, 3.8)
    draw_arrow(9, 4.8, 5.5, 3.8)

    # Arrows between processing steps
    draw_arrow(3.3, 3.4, 4.1, 3.4)
    draw_arrow(6.9, 3.4, 7.7, 3.4)

    # Row 3: Storage
    draw_box(3.5, 1.5, 3.5, 0.8, 'SQLite Database', 'poker.db', color=gold, fc='#1e2a3e')
    draw_arrow(1.9, 3.0, 5.25, 2.3)
    draw_arrow(5.5, 3.0, 5.25, 2.3)
    draw_arrow(5.25, 2.3, 9.1, 3.0)

    # Row 3: Output
    ax.text(11.8, 4.1, 'OUTPUT', ha='center', fontsize=9, color=gold,
            fontweight='bold')
    draw_box(10.8, 3.0, 2.5, 0.8, 'Dashboard', 'index.html', color='#4caf50')

    # Arrow: visualize -> dashboard
    draw_arrow(10.5, 3.4, 10.8, 3.4)

    # Row 4: Deployment
    draw_box(10.8, 1.5, 2.5, 0.8, 'GitHub Pages', 'Auto-deploy', color='#4caf50')
    draw_arrow(12.05, 3.0, 12.05, 2.3)

    # CI/CD label
    ax.text(7, 0.6, 'Triggered by: git push to raw/ or player_map.yaml', ha='center',
            fontsize=9, color='#666', style='italic')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
        print(f"Saved: {save_path}")
    else:
        plt.show()


def generate_all_visualizations(db_path: str = "poker.db", output_dir: str = ".",
                                min_games: int = 0):
    """Generate all visualizations and save to files."""
    from pathlib import Path

    output = Path(output_dir)
    output.mkdir(exist_ok=True)

    print("Generating visualizations...")

    plot_player_statistics(db_path, str(output / "player_statistics.png"), min_games=min_games)
    plot_hand_analysis(db_path, str(output / "hand_analysis.png"))
    plot_session_trends(db_path, str(output / "session_trends.png"), min_games=min_games)
    plot_pipeline_diagram(str(output / "pipeline_diagram.png"))

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
