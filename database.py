"""
SQLite database schema and initialization for poker hand history.
"""
import sqlite3
from pathlib import Path
from typing import Optional


def get_connection(db_path: str = "poker.db") -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str = "poker.db") -> None:
    """Initialize the database with all required tables."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Games table - represents a poker session
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            generated_at TEXT,
            player_id TEXT,
            from_cache INTEGER
        )
    """)

    # Hands table - individual poker hands within a game
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hands (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            hand_number INTEGER,
            game_type TEXT,
            small_blind INTEGER,
            big_blind INTEGER,
            ante INTEGER,
            dealer_seat INTEGER,
            started_at INTEGER,
            player_net INTEGER,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    # Players table - unique players across all games
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)

    # Hand players table - player state for each hand
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hand_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            seat INTEGER,
            stack INTEGER,
            hole_card_1 TEXT,
            hole_card_2 TEXT,
            net_gain INTEGER,
            showed_cards INTEGER,
            FOREIGN KEY (hand_id) REFERENCES hands(id),
            FOREIGN KEY (player_id) REFERENCES players(id),
            UNIQUE(hand_id, player_id)
        )
    """)

    # Events table - all actions/events in a hand
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            event_time INTEGER,
            event_type INTEGER,
            seat INTEGER,
            value INTEGER,
            FOREIGN KEY (hand_id) REFERENCES hands(id)
        )
    """)

    # Community cards table - flop/turn/river
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS community_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            turn INTEGER,
            run INTEGER,
            card_1 TEXT,
            card_2 TEXT,
            card_3 TEXT,
            card_4 TEXT,
            card_5 TEXT,
            FOREIGN KEY (hand_id) REFERENCES hands(id)
        )
    """)

    # Hand results table - winners and their hands
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hand_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            seat INTEGER,
            player_id TEXT,
            pot INTEGER,
            value_won INTEGER,
            hole_card_1 TEXT,
            hole_card_2 TEXT,
            hand_description TEXT,
            combination TEXT,
            position INTEGER,
            run_number TEXT,
            hi_lo TEXT,
            FOREIGN KEY (hand_id) REFERENCES hands(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)

    # ==================== ENRICHED LAYER TABLES ====================

    # Canonical players - represents real people (manually mapped)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS canonical_players (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    """)

    # Player mappings - maps (raw_player_id, nickname) pairs to canonical players
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_player_id TEXT NOT NULL,
            nickname TEXT NOT NULL,
            canonical_id INTEGER NOT NULL,
            FOREIGN KEY (canonical_id) REFERENCES canonical_players(id),
            UNIQUE(raw_player_id, nickname)
        )
    """)

    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hands_game ON hands(game_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hand_players_hand ON hand_players(hand_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hand_players_player ON hand_players(player_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_hand ON events(hand_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hand_results_hand ON hand_results(hand_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hand_results_player ON hand_results(player_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_mappings_raw ON player_mappings(raw_player_id, nickname)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_mappings_canonical ON player_mappings(canonical_id)")

    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")


# Event type constants for readability
EVENT_TYPES = {
    0: "CHECK_CALL",
    2: "BIG_BLIND",
    3: "SMALL_BLIND",
    7: "RAISE",
    8: "BET",
    9: "COMMUNITY_CARDS",
    10: "HAND_RESULT",
    11: "FOLD",
    12: "SHOW_CARDS",
    15: "SHOWDOWN",
    16: "ALL_IN",
}


if __name__ == "__main__":
    init_database()
