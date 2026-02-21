"""
Player identity mapping module.

Handles loading player mappings from YAML config and resolving
raw player identities to canonical player names.
"""
import yaml
from pathlib import Path
from typing import Optional
from database import get_connection, init_database


DEFAULT_MAPPING_FILE = "player_map.yaml"


def load_mappings(yaml_path: str = DEFAULT_MAPPING_FILE, db_path: str = "poker.db") -> dict:
    """
    Load player mappings from YAML file into the database.

    Returns a summary of what was loaded.
    """
    init_database(db_path)

    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        return {"error": f"Mapping file not found: {yaml_path}"}

    with open(yaml_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    if not config or "canonical_players" not in config:
        return {"error": "Invalid YAML format: missing 'canonical_players' key"}

    conn = get_connection(db_path)
    cursor = conn.cursor()

    stats = {
        "canonical_players_added": 0,
        "mappings_added": 0,
        "errors": []
    }

    # Clear existing mappings (full sync from YAML)
    cursor.execute("DELETE FROM player_mappings")
    cursor.execute("DELETE FROM canonical_players")

    for player in config.get("canonical_players", []):
        name = player.get("name")
        if not name:
            stats["errors"].append("Player entry missing 'name' field")
            continue

        # Use provided ID or auto-generate
        player_id = player.get("id")

        # Insert canonical player (with explicit ID if provided)
        if player_id is not None:
            cursor.execute(
                "INSERT INTO canonical_players (id, name) VALUES (?, ?)",
                (player_id, name)
            )
            canonical_id = player_id
        else:
            cursor.execute(
                "INSERT INTO canonical_players (name) VALUES (?)",
                (name,)
            )
            canonical_id = cursor.lastrowid

        stats["canonical_players_added"] += 1

        # Insert all aliases
        for alias in player.get("aliases", []):
            raw_id = alias.get("id")
            nickname = alias.get("nickname")

            if not raw_id or not nickname:
                # Skip empty aliases silently (common when just starting)
                continue

            try:
                cursor.execute(
                    "INSERT INTO player_mappings (raw_player_id, nickname, canonical_id) VALUES (?, ?, ?)",
                    (raw_id, nickname, canonical_id)
                )
                stats["mappings_added"] += 1
            except Exception as e:
                stats["errors"].append(f"Failed to add mapping ({raw_id}, {nickname}): {e}")

    conn.commit()
    conn.close()

    return stats


def get_canonical_name(player_id: str, nickname: str, db_path: str = "poker.db") -> Optional[str]:
    """
    Look up the canonical name for a (player_id, nickname) pair.

    Returns None if no mapping exists.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT cp.name
        FROM player_mappings pm
        JOIN canonical_players cp ON pm.canonical_id = cp.id
        WHERE pm.raw_player_id = ? AND pm.nickname = ?
    """, (player_id, nickname))

    row = cursor.fetchone()
    conn.close()

    return row['name'] if row else None


def list_unmapped_players(db_path: str = "poker.db") -> list:
    """
    Return all (player_id, nickname) pairs that are not mapped to canonical players.

    Includes hand count for prioritization.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            p.id as player_id,
            p.name as nickname,
            COUNT(DISTINCT hp.hand_id) as hands_played
        FROM players p
        JOIN hand_players hp ON p.id = hp.player_id
        LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
        WHERE pm.id IS NULL
        GROUP BY p.id, p.name
        ORDER BY hands_played DESC
    """)

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results


def export_players_template(db_path: str = "poker.db") -> str:
    """
    Generate a YAML template from existing players in the database.

    Each unique (player_id, nickname) becomes a separate canonical player
    that the user can then manually merge.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            p.id as player_id,
            p.name as nickname,
            COUNT(DISTINCT hp.hand_id) as hands_played
        FROM players p
        JOIN hand_players hp ON p.id = hp.player_id
        GROUP BY p.id, p.name
        ORDER BY hands_played DESC
    """)

    players = cursor.fetchall()
    conn.close()

    # Build YAML structure
    yaml_data = {
        "canonical_players": []
    }

    for player in players:
        yaml_data["canonical_players"].append({
            "name": player['nickname'],  # Default to nickname as canonical name
            "aliases": [
                {
                    "id": player['player_id'],
                    "nickname": player['nickname']
                }
            ]
        })

    # Add header comment
    output = "# Player Identity Mapping Configuration\n"
    output += "# \n"
    output += "# Edit this file to group player aliases under their real names.\n"
    output += "# Each canonical player can have multiple aliases (id + nickname pairs).\n"
    output += "#\n"
    output += "# Example: To merge 'Lenny' and 'LennyPoker' as the same person:\n"
    output += "#   - name: \"John Smith\"\n"
    output += "#     aliases:\n"
    output += "#       - id: \"abc123\"\n"
    output += "#         nickname: \"Lenny\"\n"
    output += "#       - id: \"xyz789\"\n"
    output += "#         nickname: \"LennyPoker\"\n"
    output += "#\n\n"
    output += yaml.dump(yaml_data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output


def resolve_player(player_id: str, nickname: str, conn) -> tuple:
    """
    Resolve a raw player identity to canonical identity.

    Returns (canonical_id_or_raw_id, canonical_name_or_nickname).
    If no mapping exists, returns the raw values.
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT cp.id, cp.name
        FROM player_mappings pm
        JOIN canonical_players cp ON pm.canonical_id = cp.id
        WHERE pm.raw_player_id = ? AND pm.nickname = ?
    """, (player_id, nickname))

    row = cursor.fetchone()

    if row:
        return (f"canonical_{row['id']}", row['name'])
    else:
        return (player_id, nickname)


def get_enriched_player_stats(db_path: str = "poker.db") -> list:
    """
    Get player statistics with canonical name resolution.

    Players with mappings are aggregated under their canonical name.
    Unmapped players appear with their raw nickname.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COALESCE(cp.name, p.name) as player_name,
            COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as player_key,
            COUNT(DISTINCT hp.hand_id) as hands_played,
            SUM(hp.net_gain) as total_profit,
            AVG(hp.net_gain) as avg_profit_per_hand,
            SUM(CASE WHEN hp.net_gain > 0 THEN 1 ELSE 0 END) as hands_won,
            SUM(CASE WHEN hp.showed_cards = 1 THEN 1 ELSE 0 END) as showdowns
        FROM players p
        JOIN hand_players hp ON p.id = hp.player_id
        LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
        LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
        GROUP BY player_key
        ORDER BY total_profit DESC
    """)

    results = cursor.fetchall()
    conn.close()
    return results


def get_enriched_session_data(db_path: str = "poker.db") -> list:
    """
    Get session progression data with canonical name resolution.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            h.hand_number,
            h.started_at,
            COALESCE('canonical_' || CAST(cp.id AS TEXT), p.id) as player_key,
            COALESCE(cp.name, p.name) as player_name,
            hp.net_gain,
            hp.stack
        FROM hands h
        JOIN hand_players hp ON h.id = hp.hand_id
        JOIN players p ON hp.player_id = p.id
        LEFT JOIN player_mappings pm ON p.id = pm.raw_player_id AND p.name = pm.nickname
        LEFT JOIN canonical_players cp ON pm.canonical_id = cp.id
        ORDER BY h.started_at, player_key
    """)

    results = cursor.fetchall()
    conn.close()
    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "load":
            yaml_file = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MAPPING_FILE
            stats = load_mappings(yaml_file)
            print(f"Loaded mappings from {yaml_file}")
            print(f"  Canonical players: {stats.get('canonical_players_added', 0)}")
            print(f"  Mappings: {stats.get('mappings_added', 0)}")
            if stats.get('errors'):
                print(f"  Errors: {len(stats['errors'])}")
                for err in stats['errors']:
                    print(f"    - {err}")

        elif command == "unmapped":
            unmapped = list_unmapped_players()
            print(f"\nUnmapped players ({len(unmapped)} total):")
            print("-" * 60)
            print(f"{'ID':<20} {'Nickname':<20} {'Hands':>10}")
            print("-" * 60)
            for p in unmapped:
                print(f"{p['player_id']:<20} {p['nickname']:<20} {p['hands_played']:>10}")

        elif command == "export":
            output = export_players_template()
            print(output)
    else:
        print("Usage:")
        print("  python mappings.py load [player_map.yaml]  - Load mappings from YAML")
        print("  python mappings.py unmapped                - List unmapped players")
        print("  python mappings.py export                  - Generate YAML template")
