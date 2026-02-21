"""
JSON ingestion pipeline for poker hand history files.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any
from database import get_connection, init_database


def ingest_file(json_path: str, db_path: str = "poker.db") -> dict:
    """
    Ingest a poker hand history JSON file into the database.

    Returns a summary of what was ingested.
    """
    # Initialize database if needed
    init_database(db_path)

    # Load JSON data
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    stats = {
        "game_id": data.get("gameId"),
        "hands_processed": 0,
        "players_added": 0,
        "events_added": 0,
        "results_added": 0,
    }

    # Insert game record
    game_id = data.get("gameId")
    cursor.execute("""
        INSERT OR REPLACE INTO games (id, generated_at, player_id, from_cache)
        VALUES (?, ?, ?, ?)
    """, (
        game_id,
        data.get("generatedAt"),
        data.get("playerId"),
        1 if data.get("fromCache") else 0
    ))

    # Track unique players
    all_players = {}

    # Process each hand
    for hand in data.get("hands", []):
        hand_id = hand.get("id")

        # Insert hand record
        cursor.execute("""
            INSERT OR REPLACE INTO hands
            (id, game_id, hand_number, game_type, small_blind, big_blind,
             ante, dealer_seat, started_at, player_net)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hand_id,
            game_id,
            int(hand.get("number", 0)),
            hand.get("gameType"),
            hand.get("smallBlind"),
            hand.get("bigBlind"),
            hand.get("ante"),
            hand.get("dealerSeat"),
            hand.get("startedAt"),
            hand.get("playerNet")
        ))

        # Process players in this hand
        seat_to_player = {}  # Map seat number to player_id for this hand
        for player in hand.get("players", []):
            player_id = player.get("id")
            player_name = player.get("name")
            seat = player.get("seat")
            seat_to_player[seat] = player_id

            # Track unique players
            if player_id not in all_players:
                all_players[player_id] = player_name
                cursor.execute("""
                    INSERT OR REPLACE INTO players (id, name)
                    VALUES (?, ?)
                """, (player_id, player_name))
                stats["players_added"] += 1

            # Insert hand_player record
            hole_cards = player.get("hand", [])
            cursor.execute("""
                INSERT OR REPLACE INTO hand_players
                (hand_id, player_id, seat, stack, hole_card_1, hole_card_2, net_gain, showed_cards)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hand_id,
                player_id,
                seat,
                player.get("stack"),
                hole_cards[0] if len(hole_cards) > 0 else None,
                hole_cards[1] if len(hole_cards) > 1 else None,
                player.get("netGain"),
                1 if player.get("show") else 0
            ))

        # Process events
        community_cards = {1: [], 2: [], 3: []}  # flop=1, turn=2, river=3

        for event in hand.get("events", []):
            payload = event.get("payload", {})
            event_type = payload.get("type")

            # Handle community cards separately
            if event_type == 9:
                turn = payload.get("turn", 1)
                cards = payload.get("cards", [])
                run = payload.get("run", 1)

                # Pad cards list to 5 elements
                while len(cards) < 5:
                    cards.append(None)

                cursor.execute("""
                    INSERT INTO community_cards
                    (hand_id, turn, run, card_1, card_2, card_3, card_4, card_5)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (hand_id, turn, run, cards[0], cards[1], cards[2],
                      cards[3] if len(cards) > 3 else None,
                      cards[4] if len(cards) > 4 else None))

            # Handle hand results
            elif event_type == 10:
                seat = payload.get("seat")
                player_id = seat_to_player.get(seat)
                hole_cards = payload.get("cards", [])
                combination = payload.get("combination", [])

                cursor.execute("""
                    INSERT INTO hand_results
                    (hand_id, seat, player_id, pot, value_won, hole_card_1, hole_card_2,
                     hand_description, combination, position, run_number, hi_lo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hand_id,
                    seat,
                    player_id,
                    payload.get("pot"),
                    payload.get("value"),
                    hole_cards[0] if len(hole_cards) > 0 else None,
                    hole_cards[1] if len(hole_cards) > 1 else None,
                    payload.get("handDescription"),
                    ",".join(combination) if combination else None,
                    payload.get("position"),
                    payload.get("runNumber"),
                    payload.get("hiLo")
                ))
                stats["results_added"] += 1

            # Insert regular events
            else:
                cursor.execute("""
                    INSERT INTO events (hand_id, event_time, event_type, seat, value)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    hand_id,
                    event.get("at"),
                    event_type,
                    payload.get("seat"),
                    payload.get("value")
                ))
                stats["events_added"] += 1

        stats["hands_processed"] += 1

    conn.commit()
    conn.close()

    return stats


def ingest_directory(dir_path: str, db_path: str = "poker.db") -> list:
    """Ingest all JSON files in a directory."""
    results = []
    path = Path(dir_path)

    for json_file in path.glob("*.json"):
        print(f"Processing: {json_file.name}")
        stats = ingest_file(str(json_file), db_path)
        results.append(stats)
        print(f"  - Hands: {stats['hands_processed']}, Players: {stats['players_added']}, Events: {stats['events_added']}")

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        target = sys.argv[1]
        if Path(target).is_dir():
            results = ingest_directory(target)
            print(f"\nIngested {len(results)} files")
        else:
            stats = ingest_file(target)
            print(f"\nIngestion complete:")
            print(f"  Game ID: {stats['game_id']}")
            print(f"  Hands: {stats['hands_processed']}")
            print(f"  Players: {stats['players_added']}")
            print(f"  Events: {stats['events_added']}")
            print(f"  Results: {stats['results_added']}")
    else:
        # Default: ingest all JSON files in current directory
        results = ingest_directory(".")
        print(f"\nIngested {len(results)} files")
