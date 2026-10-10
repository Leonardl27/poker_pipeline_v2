"""
Chart data builder for the interactive dashboard.

Assembles a single JSON-serializable payload consumed by the inline SVG
chart renderer embedded in index.html. All values are plain Python types
(no numpy scalars, no NaN — missing values are None) so json.dumps with
allow_nan=False always succeeds.
"""
from collections import defaultdict
from datetime import datetime

from hud_stats import calculate_hud_stats
from visualize import (
    get_player_statistics, get_hand_distributions, get_per_session_stats,
    _categorize_hand, _compute_trend,
)
from database import EVENT_TYPES

# Stats correlated against profit (key in hud row, display label)
STAT_KEYS = [
    ("conv_vpip_pct", "VPIP%"),
    ("pfr_pct", "PFR%"),
    ("ats_pct", "ATS%"),
    ("three_bet_pct", "3-Bet%"),
    ("flop_seen_pct", "Flop Seen%"),
    ("bb_defend_pct", "BB Def%"),
    ("wtsd_pct", "WTSD%"),
    ("wsd_pct", "W$SD%"),
    ("aggression_factor", "AF"),
    ("cbet_pct", "C-Bet%"),
    ("fold_to_cbet_pct", "Fold C-Bet%"),
]

HAND_RANKING = [
    "High Card", "Pair", "Two Pair", "Three of a Kind",
    "Straight", "Flush", "Full House", "Four of a Kind",
]


def _archetype_data(hud_by_name: dict, stats: list) -> dict:
    players = []
    for row in stats:
        h = hud_by_name.get(row["name"])
        if not h:
            continue
        players.append({
            "name": row["name"],
            "vpip": round(h["conv_vpip_pct"], 1),
            "pfr": round(h["pfr_pct"], 1),
            "hands": row["hands_played"],
            "profit": round(row["total_profit"] or 0, 2),
        })
    if not players:
        return {"players": [], "vpip_median": 0, "pfr_median": 0}

    from statistics import median
    return {
        "players": players,
        "vpip_median": round(median(p["vpip"] for p in players), 1),
        "pfr_median": round(median(p["pfr"] for p in players), 1),
    }


def _hand_analysis_data(db_path: str) -> dict:
    data = get_hand_distributions(db_path)

    category_counts = defaultdict(int)
    for row in data["hands"]:
        category_counts[_categorize_hand(row["hand_description"])] += row["count"]
    # Strongest hand first so the chart reads top-down
    hands = [
        {"label": h, "count": category_counts[h]}
        for h in reversed(HAND_RANKING) if h in category_counts
    ]

    actions = []
    for row in data["actions"]:
        name = EVENT_TYPES.get(row["event_type"])
        if name is None:
            continue
        actions.append({"label": name, "count": row["count"]})
    actions.sort(key=lambda a: a["count"], reverse=True)

    return {"hands": hands, "actions": actions}


def _keep(rows, active_names):
    """Drop rows for players outside the active set (None = keep all)."""
    if active_names is None:
        return list(rows)
    return [r for r in rows if r["name"] in active_names]


def _session_trends_data(db_path: str, min_games: int,
                         active_names: set = None) -> dict:
    rows = _keep(get_per_session_stats(db_path, use_enriched=True,
                                       min_games=min_games), active_names)
    if not rows:
        return {"labels": [], "featured": [], "names": [], "matrix": []}

    session_dates: dict = {}
    player_session_map: dict = defaultdict(dict)
    player_names: dict = {}
    for row in rows:
        gid = row["game_id"]
        player_names[row["player_id"]] = row["name"]
        player_session_map[row["player_id"]][gid] = row["session_profit"] or 0
        session_dates.setdefault(gid, row["session_start"])

    global_sessions = sorted(session_dates, key=lambda g: session_dates[g])
    session_index = {gid: i for i, gid in enumerate(global_sessions)}

    labels = []
    for gid in global_sessions:
        try:
            labels.append(datetime.fromtimestamp(
                session_dates[gid] / 1000).strftime("%m/%d"))
        except (ValueError, TypeError, OSError):
            labels.append(str(len(labels) + 1))

    sorted_players = sorted(
        player_session_map.items(), key=lambda kv: sum(kv[1].values()),
        reverse=True,
    )

    # Featured: top 3 winners + bottom 2 losers, cumulative P/L points
    top3 = sorted_players[:3]
    bottom2 = sorted_players[-2:] if len(sorted_players) > 3 else []
    featured_ids = list(dict.fromkeys(
        [pid for pid, _ in top3] + [pid for pid, _ in bottom2]))

    featured = []
    for pid in featured_ids:
        profit_map = player_session_map[pid]
        running = 0
        points = []
        for gid in global_sessions:
            if gid in profit_map:
                running += profit_map[gid]
                points.append({"x": session_index[gid],
                               "y": round(running, 2)})
        featured.append({"name": player_names[pid], "points": points})

    # Heatmap matrix: players (profit desc) x sessions, None where absent
    names = [player_names[pid] for pid, _ in sorted_players]
    matrix = []
    for pid, profit_map in sorted_players:
        matrix.append([
            round(profit_map[gid], 2) if gid in profit_map else None
            for gid in global_sessions
        ])

    return {"labels": labels, "featured": featured,
            "names": names, "matrix": matrix}


def _momentum_data(db_path: str, min_games: int,
                   active_names: set = None) -> dict:
    rows = _keep(get_per_session_stats(db_path, use_enriched=True,
                                       min_games=min_games), active_names)
    player_sessions: dict = defaultdict(list)
    player_names: dict = {}
    for row in rows:
        try:
            label = datetime.fromtimestamp(
                row["session_start"] / 1000).strftime("%m/%d")
        except (ValueError, TypeError, OSError):
            label = "?"
        player_sessions[row["player_id"]].append(
            {"label": label, "profit": round(row["session_profit"] or 0, 2)})
        player_names[row["player_id"]] = row["name"]

    sorted_players = sorted(
        player_sessions.items(),
        key=lambda kv: sum(s["profit"] for s in kv[1]),
        reverse=True,
    )

    players = []
    for pid, sessions in sorted_players:
        profits = [s["profit"] for s in sessions]
        trend = _compute_trend(profits)
        players.append({
            "name": player_names[pid],
            "trend": {"↑": "up", "↓": "down"}.get(trend, ""),
            "sessions": sessions,
        })
    return {"players": players}


def _eligible_hud(db_path: str, min_games: int,
                  active_names: set = None) -> list:
    hud = calculate_hud_stats(db_path)
    eligible = {r["name"] for r in
                _keep(get_player_statistics(db_path, use_enriched=True,
                                            min_games=min_games), active_names)}
    return [h for h in hud if h["name"] in eligible]


def _correlations_data(hud: list) -> dict:
    import numpy as np

    keys = STAT_KEYS + [("net_profit", "Profit")]
    n_stats = len(keys)
    matrix = np.full((len(hud), n_stats), np.nan)
    for i, h in enumerate(hud):
        for j, (key, _) in enumerate(keys):
            val = h.get(key)
            if val is not None:
                matrix[i, j] = val

    corr = []
    for i in range(n_stats):
        row = []
        for j in range(n_stats):
            mask = ~np.isnan(matrix[:, i]) & ~np.isnan(matrix[:, j])
            if mask.sum() >= 3:
                row.append(round(float(
                    np.corrcoef(matrix[mask, i], matrix[mask, j])[0, 1]), 3))
            else:
                row.append(None)
        corr.append(row)

    return {"labels": [label for _, label in keys], "matrix": corr}


def _profit_drivers_data(hud: list) -> dict:
    import numpy as np
    from scipy import stats as sp_stats

    correlations = []
    for key, label in STAT_KEYS:
        points = [
            {"name": h["name"], "x": round(h[key], 2),
             "y": round(h["net_profit"], 2)}
            for h in hud if h.get(key) is not None
        ]
        if len(points) >= 4:
            xs = np.array([p["x"] for p in points])
            ys = np.array([p["y"] for p in points])
            r = float(np.corrcoef(xs, ys)[0, 1])
            correlations.append((abs(r), key, label, points, xs, ys))

    correlations.sort(key=lambda c: c[0], reverse=True)

    panels = []
    for abs_r, key, label, points, xs, ys in correlations[:4]:
        reg = sp_stats.linregress(xs, ys)
        panels.append({
            "label": label,
            "points": points,
            "slope": round(float(reg.slope), 4),
            "intercept": round(float(reg.intercept), 4),
            "r2": round(float(reg.rvalue) ** 2, 3),
            "p": round(float(reg.pvalue), 4),
        })
    return {"panels": panels}


def build_chart_data(db_path: str = "poker.db", min_games: int = 3,
                     active_names: set = None) -> dict:
    """Build the full CHART_DATA payload for the interactive dashboard.

    active_names: if given, player-level charts only include these players
    (e.g. people who played in the last year). Session columns and the
    hand/action distributions still cover the full history.
    """
    stats = _keep(get_player_statistics(db_path, use_enriched=True,
                                        min_games=min_games), active_names)
    hud_by_name = {h["name"]: h for h in calculate_hud_stats(db_path)}
    hud_eligible = _eligible_hud(db_path, min_games, active_names)

    return {
        "archetypes": _archetype_data(hud_by_name, stats),
        "hand_analysis": _hand_analysis_data(db_path),
        "session_trends": _session_trends_data(db_path, min_games, active_names),
        "momentum": _momentum_data(db_path, min_games, active_names),
        "correlations": (_correlations_data(hud_eligible)
                         if len(hud_eligible) >= 3 else None),
        "profit_drivers": (_profit_drivers_data(hud_eligible)
                           if len(hud_eligible) >= 4 else None),
    }
