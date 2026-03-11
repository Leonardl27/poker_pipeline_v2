"""
Visualization module for poker hand history analysis.
Uses Matplotlib for static charts.

By default, uses enriched data (canonical player names) when mappings exist.
Falls back to raw data for unmapped players.
"""
import itertools
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
        # Enriched query: use canonical names via v_hand_players view
        cursor.execute(f"""
            SELECT
                vhp.name,
                vhp.cid as id,
                COUNT(DISTINCT vhp.hand_id) as hands_played,
                SUM(vhp.net_gain) / 100.0 as total_profit,
                AVG(vhp.net_gain) / 100.0 as avg_profit_per_hand,
                SUM(CASE WHEN vhp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
                SUM(CASE WHEN vhp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns,
                COUNT(DISTINCT h.game_id) as games_played
            FROM v_hand_players vhp
            JOIN hands h ON vhp.hand_id = h.id
            GROUP BY vhp.cid
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
                SUM(hp.net_gain) / 100.0 as total_profit,
                AVG(hp.net_gain) / 100.0 as avg_profit_per_hand,
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
                vhp.cid as player_id,
                vhp.name,
                vhp.net_gain,
                vhp.stack
            FROM hands h
            JOIN v_hand_players vhp ON h.id = vhp.hand_id
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
            MAX(hr.pot) / 100.0 as pot_size
        FROM hands h
        JOIN hand_results hr ON h.id = hr.hand_id
        GROUP BY h.id
        ORDER BY h.started_at
    """)

    results = cursor.fetchall()
    conn.close()
    return results


def get_per_session_stats(db_path: str = "poker.db", use_enriched: bool = True,
                          min_games: int = 3) -> list:
    """Get per-session profit/loss for each player.

    Returns rows ordered by (player_id, session_start) with:
        player_id, name, game_id, session_start, session_profit
    Only players with >= min_games sessions are included.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if use_enriched:
        query = """
            SELECT sub.player_id, sub.name, sub.game_id,
                   sub.session_start, sub.session_profit
            FROM (
                SELECT
                    vhp.cid                    AS player_id,
                    vhp.name,
                    h.game_id,
                    MIN(h.started_at)          AS session_start,
                    SUM(vhp.net_gain) / 100.0  AS session_profit,
                    COUNT(h.game_id) OVER (
                        PARTITION BY vhp.cid
                    ) AS games_played
                FROM v_hand_players vhp
                JOIN hands h ON vhp.hand_id = h.id
                GROUP BY vhp.cid, h.game_id
            ) sub
            WHERE sub.games_played >= ?
            ORDER BY sub.player_id, sub.session_start, sub.game_id
        """
    else:
        query = """
            SELECT sub.player_id, sub.name, sub.game_id,
                   sub.session_start, sub.session_profit
            FROM (
                SELECT
                    p.id AS player_id, p.name,
                    h.game_id,
                    MIN(h.started_at) AS session_start,
                    SUM(hp.net_gain) / 100.0  AS session_profit,
                    COUNT(h.game_id) OVER (PARTITION BY p.id) AS games_played
                FROM players p
                JOIN hand_players hp ON p.id = hp.player_id
                JOIN hands h         ON hp.hand_id = h.id
                GROUP BY p.id, h.game_id
            ) sub
            WHERE sub.games_played >= ?
            ORDER BY sub.player_id, sub.session_start, sub.game_id
        """

    cursor.execute(query, (min_games,))
    rows = cursor.fetchall()
    conn.close()
    return rows


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
    """Session trends: top-5 cumulative P/L lines + player-session heatmap.

    Top subplot shows cumulative profit/loss curves for the 3 biggest winners
    and 2 biggest losers, plotted at per-session granularity for clarity.

    Bottom subplot is a heatmap grid (players x sessions) with a diverging
    red-green colormap and dollar annotations inside each cell.
    """
    import numpy as np
    from matplotlib.colors import TwoSlopeNorm

    # --- colours matching the dashboard dark theme ---
    BG = '#1a1a2e'
    PANEL_BG = '#16213e'
    BORDER = '#0f3460'
    ACCENT = '#e94560'
    POSITIVE = '#4caf50'
    TEXT = '#eeeeee'
    NEUTRAL = '#aaaaaa'
    TOP_COLORS = ['#4caf50', '#2a9d8f', '#38bdf8', '#fb923c', '#e94560']

    rows = get_per_session_stats(db_path, use_enriched=True, min_games=min_games)
    if not rows:
        print("No session data available")
        return

    # Group by player, preserving chronological order
    player_sessions: dict = defaultdict(list)
    player_names: dict = {}
    for row in rows:
        player_sessions[row['player_id']].append(row['session_profit'] or 0)
        player_names[row['player_id']] = row['name']

    # Sort players by total profit descending
    sorted_players = sorted(
        player_sessions.items(),
        key=lambda kv: sum(kv[1]),
        reverse=True,
    )

    n_players = len(sorted_players)
    max_sessions = max(len(profits) for _, profits in sorted_players)

    # --- Pick top 3 winners + bottom 2 losers for cumulative chart ---
    top3 = sorted_players[:3]
    bottom2 = sorted_players[-2:] if n_players > 3 else []
    featured = top3 + [p for p in bottom2 if p not in top3]

    # ---- Figure layout ---------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(18, 14),
        gridspec_kw={'height_ratios': [1, 1.3]},
    )
    fig.patch.set_facecolor(BG)
    fig.suptitle('Session Trends', color=ACCENT, fontsize=16,
                 fontweight='bold', y=0.98)

    # ── Top subplot: cumulative P/L for featured players ──────────────────
    ax1.set_facecolor(PANEL_BG)

    for i, (player_id, profits) in enumerate(featured):
        cumulative = []
        running = 0
        for p in profits:
            running += p
            cumulative.append(running)

        x_vals = list(range(1, len(cumulative) + 1))
        color = TOP_COLORS[i % len(TOP_COLORS)]
        name = player_names[player_id]

        ax1.plot(x_vals, cumulative, color=color, linewidth=2.5, alpha=0.9,
                 marker='o', markersize=5)

        # End-of-line label instead of legend
        ax1.annotate(
            name,
            xy=(x_vals[-1], cumulative[-1]),
            xytext=(8, 0),
            textcoords='offset points',
            color=color,
            fontsize=9,
            fontweight='bold',
            va='center',
        )

    ax1.axhline(y=0, color=BORDER, linestyle='--', linewidth=1, alpha=0.7)
    ax1.set_xlabel('Session Number', color=TEXT, fontsize=11)
    ax1.set_ylabel('Cumulative Profit / Loss ($)', color=TEXT, fontsize=11)
    ax1.set_title('Cumulative P/L — Top 3 Winners & Bottom 2 Losers',
                  color=TEXT, fontsize=12, pad=8)
    ax1.set_xticks(range(1, max_sessions + 1))
    ax1.tick_params(colors=NEUTRAL)
    for spine in ax1.spines.values():
        spine.set_edgecolor(BORDER)
    ax1.grid(True, alpha=0.12, color=NEUTRAL)

    # ── Bottom subplot: player x session heatmap ──────────────────────────
    ax2.set_facecolor(PANEL_BG)

    # Build the data matrix (players sorted by total profit)
    names_ordered = [player_names[pid] for pid, _ in sorted_players]
    data_matrix = np.full((n_players, max_sessions), np.nan)
    for row_idx, (player_id, profits) in enumerate(sorted_players):
        for col_idx, val in enumerate(profits):
            data_matrix[row_idx, col_idx] = val

    # Diverging colormap centered at 0
    vmax = np.nanmax(np.abs(data_matrix)) if not np.all(np.isnan(data_matrix)) else 10
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

    # Use red-green diverging colors built from the theme palette
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list(
        'poker_rg', [ACCENT, PANEL_BG, POSITIVE], N=256
    )

    im = ax2.imshow(data_matrix, aspect='auto', cmap=cmap, norm=norm,
                    interpolation='nearest')

    # Annotate cells with dollar values
    for r in range(n_players):
        for c in range(max_sessions):
            val = data_matrix[r, c]
            if np.isnan(val):
                continue
            # Choose text color for readability
            txt_color = TEXT if abs(val) > vmax * 0.3 else NEUTRAL
            label = f'${val:+.0f}' if abs(val) >= 1 else f'${val:+.2f}'
            fontsize = 7 if max_sessions > 12 else 8
            ax2.text(c, r, label, ha='center', va='center',
                     color=txt_color, fontsize=fontsize, fontweight='bold')

    ax2.set_xticks(range(max_sessions))
    ax2.set_xticklabels(range(1, max_sessions + 1))
    ax2.set_yticks(range(n_players))
    ax2.set_yticklabels(names_ordered)
    ax2.set_xlabel('Session Number', color=TEXT, fontsize=11)
    ax2.set_title('Session Profit/Loss by Player',
                  color=TEXT, fontsize=12, pad=8)
    ax2.tick_params(colors=NEUTRAL, labelsize=9)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax2, pad=0.02, shrink=0.8)
    cbar.set_label('Profit / Loss ($)', color=TEXT, fontsize=10)
    cbar.ax.tick_params(colors=NEUTRAL)

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor=BG)
        print(f"Saved: {save_path}")
    else:
        plt.show()
    plt.close(fig)


def _compute_trend(profits: list) -> str:
    """Compare average of last 3 sessions to the 3 before that.

    Returns '↑' (improving), '↓' (declining), or '' (insufficient data / flat).
    Requires at least 4 sessions for a meaningful comparison.
    """
    n = len(profits)
    if n < 4:
        return ''
    recent = profits[-3:]
    prior = profits[-6:-3] if n >= 6 else profits[:-3]
    recent_avg = sum(recent) / len(recent)
    prior_avg = sum(prior) / len(prior)
    if recent_avg > prior_avg:
        return '↑'
    elif recent_avg < prior_avg:
        return '↓'
    return ''


def plot_momentum(db_path: str = "poker.db", save_path: Optional[str] = None,
                  min_games: int = 3):
    """Small-multiples grid of per-session profit/loss bars, one subplot per player.

    Each mini chart shows green bars for winning sessions and red bars for losing
    sessions.  Players with 4+ sessions get a trend arrow (↑ / ↓) in the title
    comparing recent form to earlier sessions.
    """
    import math

    # --- colours matching the dashboard dark theme ---
    BG = '#1a1a2e'
    PANEL_BG = '#16213e'
    BORDER = '#0f3460'
    ACCENT = '#e94560'
    POSITIVE = '#4caf50'
    TEXT = '#eeeeee'
    NEUTRAL = '#aaaaaa'

    rows = get_per_session_stats(db_path, use_enriched=True, min_games=min_games)
    if not rows:
        print("No momentum data available (insufficient sessions)")
        return

    # Group by player, preserving chronological order
    player_sessions: dict = defaultdict(list)
    player_names: dict = {}
    for row in rows:
        player_sessions[row['player_id']].append(row['session_profit'] or 0)
        player_names[row['player_id']] = row['name']

    # Sort players by total profit descending
    sorted_players = sorted(
        player_sessions.items(),
        key=lambda kv: sum(kv[1]),
        reverse=True,
    )

    n_players = len(sorted_players)
    ncols = 4
    nrows = math.ceil(n_players / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 3.5 * nrows))
    fig.patch.set_facecolor(BG)
    fig.suptitle('Player Momentum — Per-Session Profit / Loss',
                 color=ACCENT, fontsize=16, fontweight='bold', y=0.98)

    # Flatten axes for easy indexing
    if nrows == 1 and ncols == 1:
        axes_flat = [axes]
    else:
        axes_flat = axes.flatten()

    # Shared y-axis scale across all subplots
    all_profits = [p for _, profits in sorted_players for p in profits]
    y_max = max(abs(v) for v in all_profits) if all_profits else 10
    y_pad = y_max * 0.15
    max_sessions = max(len(profits) for _, profits in sorted_players)

    for idx, (player_id, profits) in enumerate(sorted_players):
        ax = axes_flat[idx]
        ax.set_facecolor(PANEL_BG)

        name = player_names[player_id]
        x_vals = list(range(1, len(profits) + 1))
        colors = [POSITIVE if v >= 0 else ACCENT for v in profits]

        ax.bar(x_vals, profits, color=colors, width=0.7, alpha=0.9)
        ax.axhline(y=0, color=BORDER, linestyle='-', linewidth=0.8, alpha=0.6)

        # Trend arrow in title
        trend = _compute_trend(profits)
        trend_str = ''
        if trend:
            trend_str = f'  {trend}'

        ax.set_title(f'{name}{trend_str}', color=TEXT, fontsize=10,
                     fontweight='bold', pad=4)
        ax.set_ylim(-y_max - y_pad, y_max + y_pad)
        ax.set_xticks(range(1, max_sessions + 1))
        ax.tick_params(colors=NEUTRAL, labelsize=7)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER)
        ax.grid(True, alpha=0.1, color=NEUTRAL, axis='y')

        # Only show axis labels on edge subplots
        if idx % ncols == 0:
            ax.set_ylabel('P/L ($)', color=NEUTRAL, fontsize=8)
        if idx >= (nrows - 1) * ncols:
            ax.set_xlabel('Session', color=NEUTRAL, fontsize=8)

    # Hide unused subplots
    for idx in range(n_players, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor=BG)
        print(f"Saved: {save_path}")
    else:
        plt.show()
    plt.close(fig)


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
    plot_momentum(db_path, str(output / "momentum.png"), min_games=min_games)
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
